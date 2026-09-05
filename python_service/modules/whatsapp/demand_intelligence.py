import logging
from collections import defaultdict
from typing import Any, Dict, List
import psycopg
from python_service.config import settings

logger = logging.getLogger("demand_intelligence")

def compute_native_demand_intelligence(
    organization_id: str,
    queries: List[Dict[str, Any]],
    raw_messages: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Mathematical Demand Intelligence Engine (100% Deterministic & Data-Driven):
    Cross-references extracted customer inquiries from WhatsApp against ground-truth stock 
    in the inventory_items PostgreSQL table to detect stockout risks and reorder requirements.
    """
    raw_messages = raw_messages or []
    inventory_items_map: Dict[str, Dict[str, Any]] = {}

    # 1. Fetch ground-truth stock and reorder levels from PostgreSQL
    try:
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        LOWER(item_name), 
                        COALESCE(SUM(quantity), 0), 
                        MAX(quantity_unit),
                        COALESCE(MAX(reorder_level), 0),
                        COALESCE(MAX(unit_price), 0),
                        MAX(category),
                        MAX(item_name)
                    FROM inventory_items 
                    WHERE organization_id = %s 
                    GROUP BY LOWER(item_name)
                    """,
                    (organization_id,)
                )
                for row in cur.fetchall():
                    inventory_items_map[row[0]] = {
                        "canonical_name": row[6] or row[0].title(),
                        "quantity": float(row[1]),
                        "unit": row[2] or "units",
                        "reorder_level": float(row[3]),
                        "unit_price": float(row[4]),
                        "category": row[5] or "General"
                    }
    except Exception as e:
        logger.warning("Could not query live inventory stock for org %s: %s", organization_id, e)

    # 2. Group inquiries by demanded SKU to aggregate multi-customer demand
    sku_demand_aggregation: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "demanded_qty": 0.0,
        "inquiries_count": 0,
        "customers": set(),
        "timeframes": set(),
        "urgencies": [],
        "units": set(),
        "raw_names": []
    })

    total_demanded_volume = 0.0

    for q in queries:
        raw_item = (q.get("item_demanded") or "").strip()
        if not raw_item or raw_item.lower() in {"inquired item", "general inquiry", "unknown"}:
            continue

        demanded_qty = float(q.get("requested_quantity") or 1.0)
        total_demanded_volume += demanded_qty
        unit = q.get("requested_unit") or "units"
        customer = q.get("customer_name") or "Customer"
        timeframe = q.get("timeframe") or "upcoming"
        urgency = (q.get("urgency_level") or "NORMAL").upper()

        # Find best matching stock SKU
        item_lower = raw_item.lower()
        matched_key = item_lower
        for stock_key in inventory_items_map.keys():
            if stock_key in item_lower or item_lower in stock_key:
                matched_key = stock_key
                break

        agg = sku_demand_aggregation[matched_key]
        agg["demanded_qty"] += demanded_qty
        agg["inquiries_count"] += 1
        agg["customers"].add(customer)
        agg["timeframes"].add(timeframe)
        agg["urgencies"].append(urgency)
        agg["units"].add(unit)
        agg["raw_names"].append(raw_item)

    stockout_risks = []
    reorder_recommendations = []
    unmet_demands = []

    # 3. Data-driven classification of risks and reorders
    for sku_key, agg in sku_demand_aggregation.items():
        inv_data = inventory_items_map.get(sku_key, {
            "canonical_name": agg["raw_names"][0].title() if agg["raw_names"] else sku_key.title(),
            "quantity": 0.0,
            "unit": list(agg["units"])[0] if agg["units"] else "units",
            "reorder_level": 10.0,
            "unit_price": 100.0,
            "category": "Retail SKU"
        })

        item_name = inv_data["canonical_name"]
        available_stock = inv_data["quantity"]
        reorder_level = inv_data["reorder_level"]
        unit_price = inv_data["unit_price"] or 100.0
        category = inv_data["category"]
        unit = inv_data["unit"]
        total_qty_demanded = agg["demanded_qty"]
        inquiry_count = agg["inquiries_count"]
        cust_list = ", ".join(list(agg["customers"])[:2]) + (f" +{len(agg['customers'])-2} more" if len(agg["customers"]) > 2 else "")
        timeframe = ", ".join(list(agg["timeframes"])[:2])
        is_urgent = "HIGH" in agg["urgencies"]

        shortfall = max(0.0, total_qty_demanded - available_stock)
        post_demand_stock = available_stock - total_qty_demanded

        # Accurate, Data-Driven Risk Stratification
        if available_stock == 0 or total_qty_demanded > available_stock:
            risk_level = "HIGH"
            priority = "CRITICAL"
            urgency_score = min(98, max(80, int(80 + (shortfall / max(1.0, total_qty_demanded)) * 18)))
            reason = f"Incoming demand ({total_qty_demanded:g} {unit}) exceeds current inventory ({available_stock:g} {unit}) by {shortfall:g} {unit}."
            suggested_reorder_qty = round(shortfall * 1.25 + (reorder_level or 10.0), 1)
        elif post_demand_stock <= reorder_level or total_qty_demanded >= available_stock * 0.4 or (reorder_level > 0 and available_stock <= reorder_level):
            risk_level = "MEDIUM"
            priority = "HIGH"
            urgency_score = min(78, max(52, int(52 + ((reorder_level - max(0.0, post_demand_stock)) / max(1.0, reorder_level)) * 24)))
            reason = f"Available stock ({available_stock:g} {unit}) will drop to {post_demand_stock:g} {unit} (reorder threshold: {reorder_level:g} {unit}) after pending customer orders ({total_qty_demanded:g} {unit})."
            suggested_reorder_qty = round(max(0.0, reorder_level * 1.5 - post_demand_stock), 1)
        else:
            risk_level = "LOW"
            priority = "NORMAL"
            urgency_score = min(45, max(20, int((total_qty_demanded / max(1.0, available_stock)) * 40)))
            reason = f"Current stock ({available_stock:g} {unit}) is healthy with sufficient buffer for demand of {total_qty_demanded:g} {unit}."
            suggested_reorder_qty = round(reorder_level, 1)

        supplier_action = f"Issue Purchase Order for {suggested_reorder_qty:g} {unit} of {item_name}"

        risk_entry = {
            "item_name": item_name,
            "itemName": item_name,
            "category": category,
            "customer_name": cust_list,
            "customerName": cust_list,
            "demanded_quantity": total_qty_demanded,
            "demandedQuantity": total_qty_demanded,
            "total_quantity_demanded": total_qty_demanded,
            "totalQuantityDemanded": total_qty_demanded,
            "current_stock": available_stock,
            "currentStock": available_stock,
            "shortfall": round(shortfall, 2),
            "suggested_reorder_qty": suggested_reorder_qty,
            "suggestedReorderQty": suggested_reorder_qty,
            "reorder_quantity": suggested_reorder_qty,
            "unit": unit,
            "quantityUnit": unit,
            "timeframe": timeframe,
            "demand_frequency": inquiry_count,
            "demandFrequency": inquiry_count,
            "inquiry_count": inquiry_count,
            "risk_level": risk_level,
            "riskLevel": risk_level,
            "priority": priority,
            "urgency_score": urgency_score,
            "urgencyScore": urgency_score,
            "reason": reason,
            "supplier_action": supplier_action,
            "supplierAction": supplier_action
        }

        stockout_risks.append(risk_entry)

        if suggested_reorder_qty > 0 or risk_level in {"HIGH", "MEDIUM"}:
            reorder_recommendations.append(risk_entry)

        if shortfall > 0:
            unmet_demands.append({
                "customer": cust_list,
                "item_name": item_name,
                "itemName": item_name,
                "quantity_requested": total_qty_demanded,
                "shortfall": shortfall,
                "status": "UNFULFILLED",
                "potential_revenue_loss": round(shortfall * unit_price, 2),
                "reason": f"Shortfall of {shortfall:g} {unit} to fulfill customer inquiries."
            })

    # Sort stockout risks: HIGH risk first, then by urgency score descending
    risk_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    stockout_risks.sort(key=lambda r: (risk_rank.get(r["risk_level"], 0), r["urgency_score"]), reverse=True)
    reorder_recommendations.sort(key=lambda r: (risk_rank.get(r["risk_level"], 0), r["suggested_reorder_qty"]), reverse=True)

    high_risk_count = sum(1 for r in stockout_risks if r["risk_level"] == "HIGH")
    medium_risk_count = sum(1 for r in stockout_risks if r["risk_level"] == "MEDIUM")
    unique_skus = len(sku_demand_aggregation)
    fastest_moving = stockout_risks[0]["item_name"] if stockout_risks else (list(inventory_items_map.values())[0]["canonical_name"] if inventory_items_map else "None")

    return {
        "summary": {
            "total_skus_demanded": unique_skus,
            "totalSkusDemanded": unique_skus,
            "high_risk_stockouts": high_risk_count,
            "highRiskStockouts": high_risk_count,
            "medium_risk_stockouts": medium_risk_count,
            "mediumRiskStockouts": medium_risk_count,
            "suggested_reorders_count": len(reorder_recommendations),
            "suggestedReordersCount": len(reorder_recommendations),
            "fastest_moving_item": fastest_moving,
            "fastestMovingItem": fastest_moving,
            "total_demand_volume": round(total_demanded_volume, 2),
            "totalDemandVolume": round(total_demanded_volume, 2)
        },
        "stockout_risks": stockout_risks,
        "reorder_recommendations": reorder_recommendations,
        "unmet_demands": unmet_demands
    }

# Backward-compatibility alias
generate_demand_intelligence = compute_native_demand_intelligence
