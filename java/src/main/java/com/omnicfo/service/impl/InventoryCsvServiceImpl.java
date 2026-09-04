package com.omnicfo.service.impl;

import com.omnicfo.model.entity.Document;
import com.omnicfo.model.entity.InventoryItem;
import com.omnicfo.model.entity.Organization;
import com.omnicfo.repository.InventoryItemRepository;
import com.omnicfo.repository.OrganizationRepository;
import com.omnicfo.service.InventoryCsvService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class InventoryCsvServiceImpl implements InventoryCsvService {

    private final InventoryItemRepository inventoryItemRepository;
    private final OrganizationRepository organizationRepository;

    @Override
    @Transactional
    public int ingestInventoryCsv(UUID organizationId, Document document, MultipartFile file) {
        log.info("Ingesting ground-truth Inventory CSV for tenantId={}, docId={}", organizationId, document.getId());

        Organization organization = organizationRepository.findById(organizationId)
                .orElseThrow(() -> new IllegalArgumentException("Organization not found: " + organizationId));

        List<InventoryItem> itemsToSave = new ArrayList<>();

        try (BufferedReader reader = new BufferedReader(new InputStreamReader(file.getInputStream(), StandardCharsets.UTF_8))) {
            String headerLine = reader.readLine();
            if (headerLine == null) {
                log.warn("Uploaded inventory CSV is empty");
                return 0;
            }

            String[] headers = headerLine.split(",");
            int nameIdx = -1, qtyIdx = -1, unitIdx = -1, priceIdx = -1, reorderIdx = -1, catIdx = -1;

            // Auto-detect column positions accurately
            for (int i = 0; i < headers.length; i++) {
                String h = headers[i].trim().toLowerCase().replace("_", " ").replace("-", " ");
                if (h.contains("item") || h.contains("product") || h.contains("sku") || h.contains("name")) {
                    if (nameIdx == -1) nameIdx = i;
                } else if (h.contains("reorder") || h.contains("min stock") || h.contains("threshold")) {
                    if (reorderIdx == -1) reorderIdx = i;
                } else if (h.contains("unit price") || h.contains("price") || h.contains("rate") || h.contains("cost")) {
                    if (priceIdx == -1) priceIdx = i;
                } else if (h.contains("unit") || h.contains("uom")) {
                    if (unitIdx == -1) unitIdx = i;
                } else if (h.contains("qty") || h.contains("quantity") || h.contains("stock") || h.contains("count")) {
                    if (qtyIdx == -1) qtyIdx = i;
                } else if (h.contains("category") || h.contains("type") || h.contains("group")) {
                    if (catIdx == -1) catIdx = i;
                }
            }

            // Fallback default index assignments if headers are missing
            if (nameIdx == -1) nameIdx = 0;
            if (qtyIdx == -1) qtyIdx = (headers.length > 1 ? 1 : -1);
            if (unitIdx == -1) unitIdx = (headers.length > 2 ? 2 : -1);
            if (priceIdx == -1) priceIdx = (headers.length > 3 ? 3 : -1);
            if (reorderIdx == -1 && headers.length > 4) reorderIdx = 4;
            if (catIdx == -1 && headers.length > 5) catIdx = 5;

            String line;
            while ((line = reader.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                String[] cols = line.split(",", -1);
                if (cols.length <= nameIdx || cols[nameIdx].trim().isEmpty()) continue;

                String itemName = cols[nameIdx].trim();
                BigDecimal quantity = (qtyIdx != -1 && cols.length > qtyIdx) ? parseNumeric(cols[qtyIdx]) : BigDecimal.ZERO;
                String unit = (unitIdx != -1 && cols.length > unitIdx && !cols[unitIdx].trim().isEmpty()) ? cols[unitIdx].trim() : "units";
                BigDecimal unitPrice = (priceIdx != -1 && cols.length > priceIdx) ? parseNumeric(cols[priceIdx]) : BigDecimal.ZERO;
                BigDecimal reorderLevel = (reorderIdx != -1 && cols.length > reorderIdx) ? parseNumeric(cols[reorderIdx]) : BigDecimal.ZERO;
                String category = (catIdx != -1 && cols.length > catIdx) ? cols[catIdx].trim() : "General";

                String description = "Unit Price: ₹" + unitPrice + " | Reorder Level: " + reorderLevel + (category.isEmpty() ? "" : " | Category: " + category);

                InventoryItem item = InventoryItem.builder()
                        .organizationId(organizationId)
                        .document(document)
                        .itemName(itemName)
                        .quantity(quantity)
                        .quantityUnit(unit)
                        .unitPrice(unitPrice)
                        .reorderLevel(reorderLevel)
                        .category(category)
                        .description(description)
                        .mentionDate(java.time.LocalDate.now().toString())
                        .mentionTime(java.time.LocalTime.now().toString())
                        .build();

                itemsToSave.add(item);
            }

            inventoryItemRepository.saveAll(itemsToSave);
            log.info("Successfully persisted {} inventory items from CSV for tenantId={}", itemsToSave.size(), organizationId);
            return itemsToSave.size();

        } catch (Exception e) {
            log.error("Failed to parse Inventory CSV: {}", e.getMessage(), e);
            throw new RuntimeException("Failed to parse Inventory CSV: " + e.getMessage(), e);
        }
    }

    private BigDecimal parseNumeric(String val) {
        if (val == null) return BigDecimal.ZERO;
        String clean = val.replaceAll("[^0-9.]", "").trim();
        try {
            return clean.isEmpty() ? BigDecimal.ZERO : new BigDecimal(clean);
        } catch (Exception e) {
            return BigDecimal.ZERO;
        }
    }
}
