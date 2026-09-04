package com.omnicfo.controller;

import com.omnicfo.model.dto.InvoiceResponseDTO;
import com.omnicfo.model.entity.Invoice;
import com.omnicfo.repository.InvoiceRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

@Slf4j
@RestController
@RequestMapping("/api/v1/invoices")
@RequiredArgsConstructor
public class InvoiceController {

    private final InvoiceRepository invoiceRepository;

    @GetMapping
    public ResponseEntity<List<InvoiceResponseDTO>> getInvoices(
            @RequestHeader("X-Tenant-ID") UUID tenantId,
            @RequestParam(required = false) String paymentStatus) {

        log.info("Received request to list invoices for tenant={}, paymentStatus={}", tenantId, paymentStatus);

        List<Invoice> invoices = (paymentStatus != null && !paymentStatus.trim().isEmpty())
                ? invoiceRepository.findByOrganizationIdAndPaymentStatus(tenantId, paymentStatus.toUpperCase())
                : invoiceRepository.findByOrganizationIdOrderByCreatedAtDesc(tenantId);

        List<InvoiceResponseDTO> dtos = invoices.stream()
                .map(this::mapToDto)
                .collect(Collectors.toList());

        return ResponseEntity.ok(dtos);
    }

    @GetMapping("/{id}")
    public ResponseEntity<InvoiceResponseDTO> getInvoiceById(
            @RequestHeader("X-Tenant-ID") UUID tenantId,
            @PathVariable UUID id) {

        return invoiceRepository.findById(id)
                .filter(inv -> inv.getOrganizationId().equals(tenantId))
                .map(this::mapToDto)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    private InvoiceResponseDTO mapToDto(Invoice invoice) {
        return InvoiceResponseDTO.builder()
                .id(invoice.getId())
                .documentId(invoice.getDocument() != null ? invoice.getDocument().getId() : null)
                .organizationId(invoice.getOrganizationId())
                .invoiceNumber(invoice.getInvoiceNumber())
                .invoiceDate(invoice.getInvoiceDate())
                .dueDate(invoice.getDueDate())
                .customerName(invoice.getCustomerName())
                .gstNumber(invoice.getGstNumber())
                .totalAmount(invoice.getTotalAmount())
                .tax(invoice.getTax())
                .totalAmountWithTax(invoice.getTotalAmountWithTax())
                .paymentStatus(invoice.getPaymentStatus())
                .paidAmount(invoice.getPaidAmount())
                .paidAt(invoice.getPaidAt())
                .matchedBankStatementId(invoice.getMatchedBankStatementId())
                .sourceType(invoice.getSourceType())
                .confidenceScore(invoice.getConfidenceScore())
                .build();
    }
}
