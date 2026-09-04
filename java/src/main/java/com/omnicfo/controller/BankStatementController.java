package com.omnicfo.controller;

import com.omnicfo.model.dto.BankStatementResponseDTO;
import com.omnicfo.model.entity.BankStatement;
import com.omnicfo.repository.BankStatementRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

@Slf4j
@RestController
@RequestMapping("/api/v1/bank-statements")
@RequiredArgsConstructor
public class BankStatementController {

    private final BankStatementRepository bankStatementRepository;

    @GetMapping
    public ResponseEntity<List<BankStatementResponseDTO>> getBankStatements(
            @RequestHeader("X-Tenant-ID") UUID tenantId) {
        log.info("Fetching bank statements for tenant={}", tenantId);

        List<BankStatement> statements = bankStatementRepository.findByOrganizationIdOrderByTxnDateDesc(tenantId);
        List<BankStatementResponseDTO> dtos = statements.stream()
                .map(this::mapToDto)
                .collect(Collectors.toList());

        return ResponseEntity.ok(dtos);
    }

    private BankStatementResponseDTO mapToDto(BankStatement stmt) {
        return BankStatementResponseDTO.builder()
                .id(stmt.getId())
                .documentId(stmt.getDocument() != null ? stmt.getDocument().getId() : null)
                .organizationId(stmt.getOrganizationId())
                .txnDate(stmt.getTxnDate())
                .description(stmt.getDescription())
                .txnType(stmt.getTxnType())
                .amount(stmt.getAmount())
                .balance(stmt.getBalance())
                .reconciliationStatus(stmt.getReconciliationStatus())
                .matchedInvoiceId(stmt.getMatchedInvoiceId())
                .build();
    }
}
