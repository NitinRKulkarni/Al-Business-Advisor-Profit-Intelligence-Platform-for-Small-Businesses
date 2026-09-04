package com.omnicfo.model.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class DemandInsightResponseDTO {
    private UUID documentId;
    private UUID organizationId;
    private Instant generatedAt;
    private Map<String, Object> summary;
    private List<Map<String, Object>> stockoutRisks;
    private List<Map<String, Object>> reorderRecommendations;
    private List<Map<String, Object>> unmetDemands;
    private List<Map<String, Object>> inventoryItems;
    private List<Map<String, Object>> customerSentiment;
    private List<Map<String, Object>> customerEnquiries;
}
