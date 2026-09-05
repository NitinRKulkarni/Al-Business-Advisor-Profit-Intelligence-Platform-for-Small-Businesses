package com.omnicfo.controller;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.omnicfo.model.dto.DemandInsightResponseDTO;
import com.omnicfo.model.entity.InventoryItem;
import com.omnicfo.model.entity.WhatsAppInsight;
import com.omnicfo.repository.InventoryItemRepository;
import com.omnicfo.repository.WhatsAppInsightRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.stream.Collectors;

@Slf4j
@RestController
@RequestMapping("/api/v1/insights")
@RequiredArgsConstructor
public class DemandInsightController {

    private final WhatsAppInsightRepository whatsAppInsightRepository;
    private final InventoryItemRepository inventoryItemRepository;
    private final com.omnicfo.repository.WhatsAppQueryRepository whatsAppQueryRepository;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @GetMapping({"/demand", "/inventory"})
    public ResponseEntity<DemandInsightResponseDTO> getDemandIntelligence(
            @RequestHeader("X-Tenant-ID") UUID tenantId) {

        log.info("Received request for Demand Intelligence insights for tenant={}", tenantId);

        Optional<WhatsAppInsight> latestInsightOpt = whatsAppInsightRepository.findTopByOrganizationIdOrderByCreatedAtDesc(tenantId);
        List<InventoryItem> loggedItems = inventoryItemRepository.findByOrganizationIdOrderByCreatedAtDesc(tenantId);
        List<com.omnicfo.model.entity.WhatsAppQuery> queryEntities = whatsAppQueryRepository.findByOrganizationIdOrderByCreatedAtDesc(tenantId);

        List<Map<String, Object>> mappedItems = loggedItems.stream().map(item -> {
            Map<String, Object> map = new HashMap<>();
            map.put("id", item.getId());
            map.put("itemName", item.getItemName());
            map.put("quantity", item.getQuantity());
            map.put("quantityUnit", item.getQuantityUnit());
            map.put("unitPrice", item.getUnitPrice());
            map.put("reorderLevel", item.getReorderLevel());
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
            map.put("sender", q.getSender());
            map.put("enquiry", q.getRawMessage());
            map.put("intent", q.getIntent());
            map.put("itemDemanded", q.getItemDemanded());
            map.put("requestedQuantity", q.getRequestedQuantity());
            map.put("requestedUnit", q.getRequestedUnit());
            map.put("timeframe", q.getTimeframe());
            map.put("urgency", q.getUrgencyLevel());
            map.put("sentiment", q.getSentiment());
            map.put("createdAt", q.getCreatedAt());
            return map;
        }).collect(Collectors.toList());

        if (latestInsightOpt.isEmpty() && loggedItems.isEmpty() && queryEntities.isEmpty()) {
            return ResponseEntity.ok(buildEmptyResponse(tenantId));
        }

        WhatsAppInsight insight = latestInsightOpt.orElse(null);
        Map<String, Object> demandIntelMap = parseJsonMap(insight != null ? insight.getDemandIntelligence() : null);

        Map<String, Object> summary = getMapFromObject(demandIntelMap.get("summary"));
        if (summary.isEmpty() && !mappedItems.isEmpty()) {
            summary.put("totalSkusDemanded", mappedItems.size());
            summary.put("total_skus_demanded", mappedItems.size());
            summary.put("highRiskStockouts", 0);
            summary.put("high_risk_stockouts", 0);
            summary.put("suggestedReordersCount", mappedItems.size());
            summary.put("suggested_reorders_count", mappedItems.size());
            summary.put("fastestMovingItem", mappedItems.get(0).get("itemName"));
            summary.put("fastest_moving_item", mappedItems.get(0).get("itemName"));
            summary.put("totalDemandVolume", mappedItems.size());
            summary.put("total_demand_volume", mappedItems.size());
        } else if (!summary.isEmpty()) {
            Object totalSkus = summary.getOrDefault("totalSkusDemanded", summary.get("total_skus_demanded"));
            Object stockouts = summary.getOrDefault("highRiskStockouts", summary.get("high_risk_stockouts"));
            Object reorders = summary.getOrDefault("suggestedReordersCount", summary.get("suggested_reorders_count"));
            Object fastest = summary.getOrDefault("fastestMovingItem", summary.get("fastest_moving_item"));
            Object volume = summary.getOrDefault("totalDemandVolume", summary.get("total_demand_volume"));

            if (totalSkus != null) { summary.put("totalSkusDemanded", totalSkus); summary.put("total_skus_demanded", totalSkus); }
            if (stockouts != null) { summary.put("highRiskStockouts", stockouts); summary.put("high_risk_stockouts", stockouts); }
            if (reorders != null) { summary.put("suggestedReordersCount", reorders); summary.put("suggested_reorders_count", reorders); }
            if (fastest != null) { summary.put("fastestMovingItem", fastest); summary.put("fastest_moving_item", fastest); }
            if (volume != null) { summary.put("totalDemandVolume", volume); summary.put("total_demand_volume", volume); }
        }

        List<Map<String, Object>> stockoutRisks = getListFromObject(demandIntelMap.get("stockout_risks"));
        List<Map<String, Object>> reorderRecommendations = getListFromObject(demandIntelMap.get("reorder_recommendations"));
        List<Map<String, Object>> unmetDemands = getListFromObject(demandIntelMap.get("unmet_demands"));

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
