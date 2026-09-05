package com.omnicfo.controller;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.omnicfo.model.dto.DemandInsightResponseDTO;
import com.omnicfo.model.entity.InventoryItem;
import com.omnicfo.model.entity.WhatsAppInsight;
import com.omnicfo.model.entity.WhatsAppQuery;
import com.omnicfo.repository.InventoryItemRepository;
import com.omnicfo.repository.WhatsAppInsightRepository;
import com.omnicfo.repository.WhatsAppQueryRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.*;
import java.util.stream.Collectors;

@Slf4j
@RestController
@RequestMapping("/api/v1/insights")
@RequiredArgsConstructor
public class DemandInsightController {

    private final WhatsAppInsightRepository whatsAppInsightRepository;
    private final InventoryItemRepository inventoryItemRepository;
    private final WhatsAppQueryRepository whatsAppQueryRepository;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @GetMapping({"/demand", "/inventory"})
    public ResponseEntity<DemandInsightResponseDTO> getDemandIntelligence(
            @RequestHeader("X-Tenant-ID") UUID tenantId) {

        log.info("Received request for Demand Intelligence insights for tenant={}", tenantId);

        Optional<WhatsAppInsight> latestInsightOpt = whatsAppInsightRepository.findTopByOrganizationIdOrderByCreatedAtDesc(tenantId);
        List<InventoryItem> loggedItems = inventoryItemRepository.findByOrganizationIdOrderByCreatedAtDesc(tenantId);
        List<WhatsAppQuery> queryEntities = whatsAppQueryRepository.findByOrganizationIdOrderByCreatedAtDesc(tenantId);

        List<Map<String, Object>> mappedItems = loggedItems.stream().map(item -> {
            Map<String, Object> map = new HashMap<>();
            map.put("id", item.getId());
            map.put("itemName", item.getItemName());
            map.put("item_name", item.getItemName());
            map.put("quantity", item.getQuantity());
            map.put("quantityUnit", item.getQuantityUnit());
            map.put("quantity_unit", item.getQuantityUnit());
            map.put("unitPrice", item.getUnitPrice());
            map.put("unit_price", item.getUnitPrice());
            map.put("reorderLevel", item.getReorderLevel());
            map.put("reorder_level", item.getReorderLevel());
            map.put("category", item.getCategory());
            map.put("mentionDate", item.getMentionDate());
            map.put("mentionTime", item.getMentionTime());
            map.put("description", item.getDescription());
            return map;
        }).collect(Collectors.toList());

        List<Map<String, Object>> mappedQueries = queryEntities.stream().map(q -> {
            Map<String, Object> map = new HashMap<>();
            map.put("id", q.getId());
            map.put("customer", q.getCustomerName());
            map.put("customerName", q.getCustomerName());
            map.put("sender", q.getSender());
            map.put("enquiry", q.getRawMessage());
            map.put("rawMessage", q.getRawMessage());
            map.put("intent", q.getIntent());
            map.put("itemDemanded", q.getItemDemanded());
            map.put("item_demanded", q.getItemDemanded());
            map.put("requestedQuantity", q.getRequestedQuantity());
            map.put("requested_quantity", q.getRequestedQuantity());
            map.put("requestedUnit", q.getRequestedUnit());
            map.put("requested_unit", q.getRequestedUnit());
            map.put("timeframe", q.getTimeframe());
            map.put("urgency", q.getUrgencyLevel());
            map.put("urgencyLevel", q.getUrgencyLevel());
            map.put("sentiment", q.getSentiment());
            map.put("createdAt", q.getCreatedAt());
            return map;
        }).collect(Collectors.toList());

        if (latestInsightOpt.isEmpty() && loggedItems.isEmpty() && queryEntities.isEmpty()) {
            return ResponseEntity.ok(buildEmptyResponse(tenantId));
        }

        WhatsAppInsight insight = latestInsightOpt.orElse(null);
        Map<String, Object> demandIntelMap = parseJsonMap(insight != null ? insight.getDemandIntelligence() : null);

        List<Map<String, Object>> stockoutRisks = getListFromObject(demandIntelMap.get("stockout_risks"));
        if (stockoutRisks.isEmpty()) {
            stockoutRisks = getListFromObject(demandIntelMap.get("stockoutRisks"));
        }
        List<Map<String, Object>> reorderRecommendations = getListFromObject(demandIntelMap.get("reorder_recommendations"));
        if (reorderRecommendations.isEmpty()) {
            reorderRecommendations = getListFromObject(demandIntelMap.get("reorderRecommendations"));
        }
        List<Map<String, Object>> unmetDemands = getListFromObject(demandIntelMap.get("unmet_demands"));
        if (unmetDemands.isEmpty()) {
            unmetDemands = getListFromObject(demandIntelMap.get("unmetDemands"));
        }

        Map<String, Object> summary = getMapFromObject(demandIntelMap.get("summary"));

        // Dynamic Mathematical Reconciler: If Python insight JSON is missing or empty, compute live from ground-truth tables
        if (stockoutRisks.isEmpty() && (!mappedItems.isEmpty() || !mappedQueries.isEmpty())) {
            Map<String, Object> dynamicResult = computeDynamicDemandIntelligence(mappedItems, mappedQueries);
            stockoutRisks = getListFromObject(dynamicResult.get("stockout_risks"));
            reorderRecommendations = getListFromObject(dynamicResult.get("reorder_recommendations"));
            unmetDemands = getListFromObject(dynamicResult.get("unmet_demands"));
            summary = getMapFromObject(dynamicResult.get("summary"));
        }

        // Normalize Summary Keys for both camelCase and snake_case
        normalizeSummaryMap(summary, stockoutRisks, reorderRecommendations, mappedItems);

        List<Map<String, Object>> customerSentiment = parseJsonList(insight != null ? insight.getCustomerSentiment() : null);
        List<Map<String, Object>> customerEnquiries = !mappedQueries.isEmpty() ? mappedQueries : parseJsonList(insight != null ? insight.getCustomerEnquiries() : null);

        DemandInsightResponseDTO response = DemandInsightResponseDTO.builder()
            .documentId(insight != null && insight.getDocument() != null ? insight.getDocument().getId() : null)
            .organizationId(tenantId)
            .generatedAt(insight != null ? insight.getCreatedAt() : java.time.Instant.now())
            .summary(summary)
            .stockoutRisks(stockoutRisks)
            .reorderRecommendations(reorderRecommendations)
            .unmetDemands(unmetDemands)
            .inventoryItems(mappedItems)
            .customerSentiment(customerSentiment)
            .customerEnquiries(customerEnquiries)
            .build();

        return ResponseEntity.ok(response);
    }

    private void normalizeSummaryMap(Map<String, Object> summary, List<Map<String, Object>> stockoutRisks, List<Map<String, Object>> reorders, List<Map<String, Object>> items) {
        long highRiskCount = stockoutRisks.stream().filter(r -> "HIGH".equalsIgnoreCase(String.valueOf(r.getOrDefault("risk_level", r.get("riskLevel"))))).count();
        long mediumRiskCount = stockoutRisks.stream().filter(r -> "MEDIUM".equalsIgnoreCase(String.valueOf(r.getOrDefault("risk_level", r.get("riskLevel"))))).count();

        Object totalSkus = summary.getOrDefault("totalSkusDemanded", summary.getOrDefault("total_skus_demanded", stockoutRisks.size() > 0 ? stockoutRisks.size() : items.size()));
        Object stockouts = summary.getOrDefault("highRiskStockouts", summary.getOrDefault("high_risk_stockouts", highRiskCount));
        Object suggestedReorders = summary.getOrDefault("suggestedReordersCount", summary.getOrDefault("suggested_reorders_count", reorders.size()));
        Object fastest = summary.getOrDefault("fastestMovingItem", summary.getOrDefault("fastest_moving_item", stockoutRisks.size() > 0 ? stockoutRisks.get(0).get("item_name") : (items.size() > 0 ? items.get(0).get("itemName") : "None")));
        Object volume = summary.getOrDefault("totalDemandVolume", summary.getOrDefault("total_demand_volume", stockoutRisks.stream().mapToDouble(r -> {
            Object q = r.getOrDefault("demanded_quantity", r.getOrDefault("demandedQuantity", r.get("quantity")));
            return q instanceof Number ? ((Number) q).doubleValue() : 0.0;
        }).sum()));

        summary.put("totalSkusDemanded", totalSkus);
        summary.put("total_skus_demanded", totalSkus);
        summary.put("highRiskStockouts", stockouts);
        summary.put("high_risk_stockouts", stockouts);
        summary.put("mediumRiskStockouts", mediumRiskCount);
        summary.put("medium_risk_stockouts", mediumRiskCount);
        summary.put("suggestedReordersCount", suggestedReorders);
        summary.put("suggested_reorders_count", suggestedReorders);
        summary.put("fastestMovingItem", fastest);
        summary.put("fastest_moving_item", fastest);
        summary.put("totalDemandVolume", volume);
        summary.put("total_demand_volume", volume);
    }

    private Map<String, Object> computeDynamicDemandIntelligence(List<Map<String, Object>> items, List<Map<String, Object>> queries) {
        Map<String, Map<String, Object>> stockMap = new HashMap<>();
        for (Map<String, Object> item : items) {
            String name = String.valueOf(item.getOrDefault("itemName", item.get("item_name"))).trim().toLowerCase();
            stockMap.put(name, item);
        }

        Map<String, Double> demandBySku = new HashMap<>();
        Map<String, Integer> inquiryCountBySku = new HashMap<>();
        Map<String, Set<String>> customersBySku = new HashMap<>();

        double totalVolume = 0;

        for (Map<String, Object> q : queries) {
            String itemDemanded = String.valueOf(q.getOrDefault("itemDemanded", q.get("item_demanded"))).trim();
            if (itemDemanded.isEmpty() || "null".equalsIgnoreCase(itemDemanded) || "inquired item".equalsIgnoreCase(itemDemanded)) {
                continue;
            }

            double qty = 1.0;
            Object qObj = q.getOrDefault("requestedQuantity", q.get("requested_quantity"));
            if (qObj instanceof Number) {
                qty = ((Number) qObj).doubleValue();
            } else if (qObj != null) {
                try { qty = Double.parseDouble(String.valueOf(qObj)); } catch (Exception ignored) {}
            }

            totalVolume += qty;
            String key = itemDemanded.toLowerCase();

            // Match closest stock name
            for (String stockKey : stockMap.keySet()) {
                if (stockKey.contains(key) || key.contains(stockKey)) {
                    key = stockKey;
                    break;
                }
            }

            demandBySku.put(key, demandBySku.getOrDefault(key, 0.0) + qty);
            inquiryCountBySku.put(key, inquiryCountBySku.getOrDefault(key, 0) + 1);
            customersBySku.computeIfAbsent(key, k -> new HashSet<>()).add(String.valueOf(q.getOrDefault("customer", q.get("customerName"))));
        }

        List<Map<String, Object>> stockoutRisks = new ArrayList<>();
        List<Map<String, Object>> reorders = new ArrayList<>();
        List<Map<String, Object>> unmet = new ArrayList<>();

        if (!demandBySku.isEmpty()) {
            for (Map.Entry<String, Double> entry : demandBySku.entrySet()) {
                String skuKey = entry.getKey();
                double demandedQty = entry.getValue();
                Map<String, Object> inv = stockMap.get(skuKey);

                String itemName = inv != null ? String.valueOf(inv.getOrDefault("itemName", inv.get("item_name"))) : skuKey.substring(0, 1).toUpperCase() + skuKey.substring(1);
                double currentStock = 0.0;
                double reorderLevel = 10.0;
                String unit = inv != null ? String.valueOf(inv.getOrDefault("quantityUnit", inv.get("quantity_unit"))) : "units";
                double unitPrice = 100.0;

                if (inv != null) {
                    Object sObj = inv.get("quantity");
                    if (sObj instanceof Number) currentStock = ((Number) sObj).doubleValue();
                    Object rObj = inv.getOrDefault("reorderLevel", inv.get("reorder_level"));
                    if (rObj instanceof Number) reorderLevel = ((Number) rObj).doubleValue();
                    Object pObj = inv.getOrDefault("unitPrice", inv.get("unit_price"));
                    if (pObj instanceof Number) unitPrice = ((Number) pObj).doubleValue();
                }

                double shortfall = Math.max(0.0, demandedQty - currentStock);
                double postDemandStock = currentStock - demandedQty;

                String riskLevel;
                String priority;
                int urgencyScore;
                String reason;
                double suggestedReorderQty;

                if (currentStock == 0 || demandedQty > currentStock) {
                    riskLevel = "HIGH";
                    priority = "CRITICAL";
                    urgencyScore = (int) Math.min(98, Math.max(80, 80 + (shortfall / Math.max(1.0, demandedQty)) * 18));
                    reason = String.format("Incoming customer demand (%.1f %s) exceeds current stock (%.1f %s) by %.1f %s.", demandedQty, unit, currentStock, unit, shortfall, unit);
                    suggestedReorderQty = Math.round(shortfall * 1.25 + reorderLevel);
                } else if (postDemandStock <= reorderLevel || demandedQty >= currentStock * 0.4 || (reorderLevel > 0 && currentStock <= reorderLevel)) {
                    riskLevel = "MEDIUM";
                    priority = "HIGH";
                    urgencyScore = (int) Math.min(78, Math.max(52, 52 + ((reorderLevel - Math.max(0, postDemandStock)) / Math.max(1.0, reorderLevel)) * 24));
                    reason = String.format("Available stock (%.1f %s) will drop to %.1f %s (reorder threshold: %.1f %s) after fulfilling orders (%.1f %s).", currentStock, unit, postDemandStock, unit, reorderLevel, unit, demandedQty, unit);
                    suggestedReorderQty = Math.round(Math.max(0, reorderLevel * 1.5 - postDemandStock));
                } else {
                    riskLevel = "LOW";
                    priority = "NORMAL";
                    urgencyScore = (int) Math.min(45, Math.max(20, (demandedQty / Math.max(1.0, currentStock)) * 40));
                    reason = String.format("Stock is healthy (%.1f %s) with sufficient buffer for demand of %.1f %s.", currentStock, unit, demandedQty, unit);
                    suggestedReorderQty = Math.round(reorderLevel);
                }

                String supplierAction = String.format("Issue Purchase Order for %.1f %s of %s", suggestedReorderQty, unit, itemName);
                String customersStr = String.join(", ", customersBySku.getOrDefault(skuKey, Collections.singleton("Customer")));

                Map<String, Object> riskEntry = new HashMap<>();
                riskEntry.put("item_name", itemName);
                riskEntry.put("itemName", itemName);
                riskEntry.put("category", inv != null ? inv.get("category") : "Retail SKU");
                riskEntry.put("customer_name", customersStr);
                riskEntry.put("customerName", customersStr);
                riskEntry.put("demanded_quantity", demandedQty);
                riskEntry.put("demandedQuantity", demandedQty);
                riskEntry.put("total_quantity_demanded", demandedQty);
                riskEntry.put("totalQuantityDemanded", demandedQty);
                riskEntry.put("current_stock", currentStock);
                riskEntry.put("currentStock", currentStock);
                riskEntry.put("shortfall", shortfall);
                riskEntry.put("suggested_reorder_qty", suggestedReorderQty);
                riskEntry.put("suggestedReorderQty", suggestedReorderQty);
                riskEntry.put("reorder_quantity", suggestedReorderQty);
                riskEntry.put("unit", unit);
                riskEntry.put("quantityUnit", unit);
                riskEntry.put("demand_frequency", inquiryCountBySku.getOrDefault(skuKey, 1));
                riskEntry.put("demandFrequency", inquiryCountBySku.getOrDefault(skuKey, 1));
                riskEntry.put("risk_level", riskLevel);
                riskEntry.put("riskLevel", riskLevel);
                riskEntry.put("priority", priority);
                riskEntry.put("urgency_score", urgencyScore);
                riskEntry.put("urgencyScore", urgencyScore);
                riskEntry.put("reason", reason);
                riskEntry.put("supplier_action", supplierAction);
                riskEntry.put("supplierAction", supplierAction);

                stockoutRisks.add(riskEntry);

                if (suggestedReorderQty > 0 || "HIGH".equals(riskLevel) || "MEDIUM".equals(riskLevel)) {
                    reorders.add(riskEntry);
                }

                if (shortfall > 0) {
                    Map<String, Object> unmetEntry = new HashMap<>();
                    unmetEntry.put("customer", customersStr);
                    unmetEntry.put("item_name", itemName);
                    unmetEntry.put("itemName", itemName);
                    unmetEntry.put("quantity_requested", demandedQty);
                    unmetEntry.put("shortfall", shortfall);
                    unmetEntry.put("status", "UNFULFILLED");
                    unmetEntry.put("potential_revenue_loss", Math.round(shortfall * unitPrice * 100.0) / 100.0);
                    unmetEntry.put("reason", String.format("Shortfall of %.1f %s to fulfill inquiries.", shortfall, unit));
                    unmet.add(unmetEntry);
                }
            }
        } else if (!items.isEmpty()) {
            // Check for low-stock inventory items as base recommendations
            for (Map<String, Object> inv : items) {
                String itemName = String.valueOf(inv.getOrDefault("itemName", inv.get("item_name")));
                double qty = 0;
                Object qObj = inv.get("quantity");
                if (qObj instanceof Number) qty = ((Number) qObj).doubleValue();
                double reorderLevel = 0;
                Object rObj = inv.getOrDefault("reorderLevel", inv.get("reorder_level"));
                if (rObj instanceof Number) reorderLevel = ((Number) rObj).doubleValue();
                String unit = String.valueOf(inv.getOrDefault("quantityUnit", inv.get("quantity_unit")));

                if (reorderLevel > 0 && qty <= reorderLevel) {
                    double reorderQty = Math.round(reorderLevel * 2 - qty);
                    String riskLevel = qty == 0 ? "HIGH" : "MEDIUM";

                    Map<String, Object> riskEntry = new HashMap<>();
                    riskEntry.put("item_name", itemName);
                    riskEntry.put("itemName", itemName);
                    riskEntry.put("category", inv.get("category"));
                    riskEntry.put("customer_name", "Stock Level Monitor");
                    riskEntry.put("customerName", "Stock Level Monitor");
                    riskEntry.put("demanded_quantity", reorderLevel);
                    riskEntry.put("demandedQuantity", reorderLevel);
                    riskEntry.put("total_quantity_demanded", reorderLevel);
                    riskEntry.put("totalQuantityDemanded", reorderLevel);
                    riskEntry.put("current_stock", qty);
                    riskEntry.put("currentStock", qty);
                    riskEntry.put("shortfall", Math.max(0, reorderLevel - qty));
                    riskEntry.put("suggested_reorder_qty", reorderQty);
                    riskEntry.put("suggestedReorderQty", reorderQty);
                    riskEntry.put("reorder_quantity", reorderQty);
                    riskEntry.put("unit", unit);
                    riskEntry.put("quantityUnit", unit);
                    riskEntry.put("demand_frequency", 1);
                    riskEntry.put("demandFrequency", 1);
                    riskEntry.put("risk_level", riskLevel);
                    riskEntry.put("riskLevel", riskLevel);
                    riskEntry.put("priority", qty == 0 ? "CRITICAL" : "HIGH");
                    riskEntry.put("urgency_score", qty == 0 ? 95 : 65);
                    riskEntry.put("urgencyScore", qty == 0 ? 95 : 65);
                    riskEntry.put("reason", String.format("Current stock (%.1f %s) is below safety reorder threshold (%.1f %s).", qty, unit, reorderLevel, unit));
                    riskEntry.put("supplier_action", String.format("Issue Purchase Order for %.1f %s of %s", reorderQty, unit, itemName));
                    riskEntry.put("supplierAction", String.format("Issue Purchase Order for %.1f %s of %s", reorderQty, unit, itemName));

                    stockoutRisks.add(riskEntry);
                    reorders.add(riskEntry);
                }
            }
        }

        Map<String, Object> result = new HashMap<>();
        result.put("stockout_risks", stockoutRisks);
        result.put("reorder_recommendations", reorders);
        result.put("unmet_demands", unmet);

        Map<String, Object> summary = new HashMap<>();
        summary.put("total_skus_demanded", !demandBySku.isEmpty() ? demandBySku.size() : items.size());
        summary.put("totalSkusDemanded", !demandBySku.isEmpty() ? demandBySku.size() : items.size());
        summary.put("high_risk_stockouts", stockoutRisks.stream().filter(r -> "HIGH".equals(r.get("risk_level"))).count());
        summary.put("highRiskStockouts", stockoutRisks.stream().filter(r -> "HIGH".equals(r.get("risk_level"))).count());
        summary.put("suggested_reorders_count", reorders.size());
        summary.put("suggestedReordersCount", reorders.size());
        summary.put("fastest_moving_item", !stockoutRisks.isEmpty() ? stockoutRisks.get(0).get("item_name") : (!items.isEmpty() ? items.get(0).get("itemName") : "None"));
        summary.put("fastestMovingItem", !stockoutRisks.isEmpty() ? stockoutRisks.get(0).get("item_name") : (!items.isEmpty() ? items.get(0).get("itemName") : "None"));
        summary.put("total_demand_volume", Math.round(totalVolume * 100.0) / 100.0);
        summary.put("totalDemandVolume", Math.round(totalVolume * 100.0) / 100.0);

        result.put("summary", summary);
        return result;
    }

    private Map<String, Object> parseJsonMap(String json) {
        if (json == null || json.trim().isEmpty()) return new HashMap<>();
        try {
            return objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            log.warn("Failed to parse JSON map: {}", e.getMessage());
            return new HashMap<>();
        }
    }

    private List<Map<String, Object>> parseJsonList(String json) {
        if (json == null || json.trim().isEmpty()) return new ArrayList<>();
        try {
            return objectMapper.readValue(json, new TypeReference<List<Map<String, Object>>>() {});
        } catch (Exception e) {
            log.warn("Failed to parse JSON list: {}", e.getMessage());
            return new ArrayList<>();
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> getMapFromObject(Object obj) {
        if (obj instanceof Map) return (Map<String, Object>) obj;
        return new HashMap<>();
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> getListFromObject(Object obj) {
        if (obj instanceof List) return (List<Map<String, Object>>) obj;
        return new ArrayList<>();
    }

    private DemandInsightResponseDTO buildEmptyResponse(UUID tenantId) {
        return DemandInsightResponseDTO.builder()
            .organizationId(tenantId)
            .generatedAt(java.time.Instant.now())
            .summary(Map.of(
                "totalSkusDemanded", 0,
                "highRiskStockouts", 0,
                "suggestedReordersCount", 0,
                "fastestMovingItem", "None",
                "totalDemandVolume", 0
            ))
            .stockoutRisks(Collections.emptyList())
            .reorderRecommendations(Collections.emptyList())
            .unmetDemands(Collections.emptyList())
            .inventoryItems(Collections.emptyList())
            .customerSentiment(Collections.emptyList())
            .customerEnquiries(Collections.emptyList())
            .build();
    }
}
