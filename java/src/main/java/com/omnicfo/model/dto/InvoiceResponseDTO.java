package com.omnicfo.model.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class InvoiceResponseDTO {
    private UUID id;
    private UUID documentId;
    private UUID organizationId;
    private String invoiceNumber;
    private LocalDate invoiceDate;
    private LocalDate dueDate;
    private String customerName;
    private String gstNumber;
    private BigDecimal totalAmount;
    private BigDecimal tax;
    private BigDecimal totalAmountWithTax;
    private String paymentStatus;
    private BigDecimal paidAmount;
    private LocalDate paidAt;
    private UUID matchedBankStatementId;
    private String sourceType;
    private BigDecimal confidenceScore;
}
