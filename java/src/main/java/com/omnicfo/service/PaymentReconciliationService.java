package com.omnicfo.service;

import com.omnicfo.model.entity.BankStatement;
import com.omnicfo.model.entity.Invoice;
import com.omnicfo.repository.BankStatementRepository;
import com.omnicfo.repository.InvoiceRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Service for automated payment reconciliation between bank statement transactions
 * and accounts receivable invoices.
 *
 * Matching rule:
 * Extracts invoice reference tokens from the transaction description/remark (e.g. "INV-2026-0847")
 * and matches against tenant invoices for incoming CREDIT transactions.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PaymentReconciliationService {

    private final InvoiceRepository invoiceRepository;
    private final BankStatementRepository bankStatementRepository;

    // Matches patterns like INV-2026-0847, INV_001, INV-12345, INV2026
    private static final Pattern INVOICE_PATTERN = Pattern.compile("\\b(INV[-_]?[A-Za-z0-9-_]+)\\b", Pattern.CASE_INSENSITIVE);

    /**
     * Reconciles a single newly ingested bank statement transaction.
     *
     * @param statement the bank statement row
     * @return true if successfully matched and reconciled, false otherwise
     */
    @Transactional
    public boolean reconcileStatement(BankStatement statement) {
        if (statement == null || !"CREDIT".equalsIgnoreCase(statement.getTxnType())) {
            return false;
        }

        if ("MATCHED".equalsIgnoreCase(statement.getReconciliationStatus())) {
            return true;
        }

        String description = statement.getDescription();
        if (description == null || description.trim().isEmpty()) {
            return false;
        }

        UUID orgId = statement.getOrganizationId();

        // 1. Try regex extraction first
        Matcher matcher = INVOICE_PATTERN.matcher(description);
        while (matcher.find()) {
            String candidateInvoiceNumber = matcher.group(1).trim();
            Optional<Invoice> invoiceOpt = invoiceRepository.findByOrganizationIdAndInvoiceNumberIgnoreCase(orgId, candidateInvoiceNumber);

            if (invoiceOpt.isPresent()) {
                applyReconciliation(statement, invoiceOpt.get());
                return true;
            }
        }

        // 2. Fallback: Search DB for any invoice whose invoiceNumber appears inside the description
        List<Invoice> candidates = invoiceRepository.findCandidatesByDescription(orgId, description);
        if (!candidates.isEmpty()) {
            Invoice bestMatch = candidates.get(0);
            applyReconciliation(statement, bestMatch);
            return true;
        }

        return false;
    }

    /**
     * Applies reconciliation updates to both the invoice and the bank statement atomically.
     */
    private void applyReconciliation(BankStatement statement, Invoice invoice) {
        log.info("Payment Reconciliation MATCH: statementId={} (desc='{}', amount={}) matched with invoiceId={} (num='{}', total={})",
            statement.getId(), statement.getDescription(), statement.getAmount(),
            invoice.getId(), invoice.getInvoiceNumber(), invoice.getTotalAmountWithTax());

        BigDecimal currentPaid = invoice.getPaidAmount() != null ? invoice.getPaidAmount() : BigDecimal.ZERO;
        BigDecimal newPaidAmount = currentPaid.add(statement.getAmount());
        BigDecimal totalRequired = invoice.getTotalAmountWithTax() != null ? invoice.getTotalAmountWithTax() : BigDecimal.ZERO;

        String newPaymentStatus = (totalRequired.compareTo(BigDecimal.ZERO) > 0 && newPaidAmount.compareTo(totalRequired) >= 0)
            ? "PAID"
            : "PARTIALLY_PAID";

        invoice.setPaymentStatus(newPaymentStatus);
        invoice.setPaidAmount(newPaidAmount);
        invoice.setPaidAt(statement.getTxnDate());
        invoice.setMatchedBankStatementId(statement.getId());
        invoiceRepository.save(invoice);

        statement.setReconciliationStatus("MATCHED");
        statement.setMatchedInvoiceId(invoice.getId());
        bankStatementRepository.save(statement);

        log.info("Successfully updated invoiceId={} paymentStatus='{}' and statementId={} reconciliationStatus='MATCHED'.",
            invoice.getId(), newPaymentStatus, statement.getId());
    }

    /**
     * Periodic scheduled pass (every 20 seconds) to reconcile any unmatched CREDIT statement rows
     * against newly extracted invoices.
     */
    @Scheduled(initialDelay = 5000, fixedDelay = 20000)
    @Transactional
    public void reconcileAllUnmatchedStatements() {
        List<BankStatement> allStatements = bankStatementRepository.findAll();
        for (BankStatement statement : allStatements) {
            if ("UNMATCHED".equalsIgnoreCase(statement.getReconciliationStatus()) 
                && "CREDIT".equalsIgnoreCase(statement.getTxnType())) {
                reconcileStatement(statement);
            }
        }
    }
}
