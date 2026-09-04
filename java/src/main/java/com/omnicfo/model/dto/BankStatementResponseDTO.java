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
public class BankStatementResponseDTO {
    private UUID id;
    private UUID documentId;
    private UUID organizationId;
    private LocalDate txnDate;
    private String description;
    private String txnType;
    private BigDecimal amount;
    private BigDecimal balance;
    private String reconciliationStatus;
    private UUID matchedInvoiceId;
}
