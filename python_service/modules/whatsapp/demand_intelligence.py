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
    Mathematical Demand Intelligence Engine (100% Non-LLM):
    Cross-references extracted customer inquiries from WhatsApp against ground-truth stock 
    in the inventory_items PostgreSQL table to detect stockout risks and reorder requirements.
    """
    raw_messages = raw_messages or []
    inventory_stock: Dict[str, float] = {}
    inventory_units: Dict[str, str] = {}

    # 1. Fetch ground-truth stock from PostgreSQL
    try:
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT LOWER(item_name), COALESCE(SUM(quantity), 0), MAX(quantity_unit) 
                    FROM inventory_items 
                    WHERE organization_id = %s 
                    GROUP BY LOWER(item_name)
                    """,
                    (organization_id,)
                )
                for row in cur.fetchall():
                    inventory_stock[row[0]] = float(row[1])
                    inventory_units[row[0]] = row[2] or "units"
    except Exception as e:
        logger.warning("Could not query live inventory stock for org %s: %s", organization_id, e)

    stockout_risks = []
    reorder_recommendations = []
    unmet_demands = []
    total_demanded_volume = 0.0

    # 2. Match each customer query against stock
    for q in queries:
        item = (q.get("item_demanded") or "").strip()
        if not item or item.lower() in {"inquired item", "general inquiry", "unknown"}:
            continue

        demanded_qty = float(q.get("requested_quantity") or 1.0)
        total_demanded_volume += demanded_qty
        unit = q.get("requested_unit") or "units"
        customer = q.get("customer_name") or "Customer"
        timeframe = q.get("timeframe") or "upcoming"
        urgency = q.get("urgency_level") or "NORMAL"
        item_lower = item.lower()

        # Find best matching stock SKU
        available_stock = 0.0
        matched_stock_name = item
        for stock_sku, stock_qty in inventory_stock.items():
            if stock_sku in item_lower or item_lower in stock_sku:
                available_stock = stock_qty
                matched_stock_name = stock_sku.title()
                unit = inventory_units.get(stock_sku, unit)
                break

        # Calculate exact shortfall
        if demanded_qty > available_stock:
            shortfall = demanded_qty - available_stock
            reorder_qty = round(shortfall * 1.20, 1) # 20% safety stock buffer

            risk_entry = {
                "item_name": matched_stock_name,
                "category": "Retail SKU",
                "customer_name": customer,
                "demanded_quantity": demanded_qty,
                "current_stock": available_stock,
                "shortfall": round(shortfall, 2),
                "suggested_reorder_qty": reorder_qty,
                "unit": unit,
                "timeframe": timeframe,
                "risk_level": "HIGH" if (urgency == "HIGH" or shortfall > 20) else "MEDIUM",
                "priority": "CRITICAL" if urgency == "HIGH" else "HIGH",
                "reason": f"Customer {customer} requested {demanded_qty:.1f} {unit} for {timeframe}, but current stock is only {available_stock:.1f} {unit} (Shortfall: {shortfall:.1f} {unit}).",
                "supplier_action": f"Issue Purchase Order for {reorder_qty:.1f} {unit} of {matched_stock_name}"
            }
            stockout_risks.append(risk_entry)
            reorder_recommendations.append(risk_entry)
            unmet_demands.append({
                "customer": customer,
                "item_name": matched_stock_name,
                "quantity_requested": demanded_qty,
                "shortfall": shortfall,
                "status": "UNFULFILLED",
                "potential_revenue_loss": round(shortfall * 50.0, 2),
                "reason": f"Insufficient stock to satisfy {customer}'s inquiry for {timeframe}."
            })

    unique_skus = len(set(q.get("item_demanded") for q in queries if q.get("item_demanded")))
    fastest_moving = stockout_risks[0]["item_name"] if stockout_risks else (queries[0]["item_demanded"] if queries else "None")

    return {
        "summary": {
            "total_skus_demanded": unique_skus,
            "high_risk_stockouts": len(stockout_risks),
            "suggested_reorders_count": len(reorder_recommendations),
            "fastest_moving_item": fastest_moving,
            "total_demand_volume": round(total_demanded_volume, 2)
        },
        "stockout_risks": stockout_risks,
        "reorder_recommendations": reorder_recommendations,
        "unmet_demands": unmet_demands
    }

# Backward-compatibility alias
generate_demand_intelligence = compute_native_demand_intelligence
