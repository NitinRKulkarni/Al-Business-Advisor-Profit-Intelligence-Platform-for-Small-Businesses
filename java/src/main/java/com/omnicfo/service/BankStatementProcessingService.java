package com.omnicfo.service;

import com.omnicfo.model.entity.BankStatement;
import com.omnicfo.model.entity.Document;
import com.omnicfo.model.enums.FileType;
import com.omnicfo.model.enums.ProcessedStatus;
import com.omnicfo.repository.BankStatementRepository;
import com.omnicfo.repository.DocumentRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

/**
 * Scheduled processor service for bank statement CSV files.
 * Performs row-level parsing and deduplication across overlapping statement files for the same tenant.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BankStatementProcessingService {

    private final DocumentRepository documentRepository;
    private final BankStatementRepository bankStatementRepository;

    /**
     * Polls every 45 seconds for the oldest PENDING bank statements (FIFO),
     * parses transaction rows, enforces row-level deduplication, and persists valid records.
     */
    @Scheduled(fixedDelay = 45000)
    public void processPendingBankStatements() {
        List<Document> pendingStatements = documentRepository.findTop5ByProcessedStatusAndFileTypeOrderByUploadDateAsc(
            ProcessedStatus.PENDING,
            FileType.BANK_STMT
        );

        if (pendingStatements.isEmpty()) {
            return;
        }

        log.info("Found {} pending Bank Statement(s) to process.", pendingStatements.size());

        for (Document document : pendingStatements) {
            processSingleBankStatement(document);
        }
    }

    private void processSingleBankStatement(Document document) {
        log.info("Starting processing for Bank Statement documentId={}, tenantId={}", 
            document.getId(), document.getOrganization().getId());

        try {
            // 1. Mark as PROCESSING immediately
            document.setProcessedStatus(ProcessedStatus.PROCESSING);
            documentRepository.save(document);

            // 2. Read CSV lines (Mock reader for now)
            List<String> csvLines = mockReadCsvLines(document);
            int insertedCount = 0;
            int skippedDuplicates = 0;

            UUID organizationId = document.getOrganization().getId();

            // 3. Parse and deduplicate each line
            for (String line : csvLines) {
                if (line == null || line.trim().isEmpty() || line.startsWith("#")) {
                    continue;
                }

                String[] parts = line.split(",");
                if (parts.length < 5) {
                    log.warn("Skipping invalid CSV line in documentId={}: '{}'", document.getId(), line);
                    continue;
                }

                LocalDate txnDate = LocalDate.parse(parts[0].trim());
                String description = parts[1].trim();
                String txnType = parts[2].trim().toUpperCase();
                BigDecimal amount = new BigDecimal(parts[3].trim());
                BigDecimal balance = new BigDecimal(parts[4].trim());

                // 4. Deduplication check: cross-file overlap detection
                boolean isDuplicate = bankStatementRepository
                    .existsByOrganizationIdAndTxnDateAndDescriptionAndAmountAndBalance(
                        organizationId,
                        txnDate,
                        description,
                        amount,
                        balance
                    );

                if (isDuplicate) {
                    skippedDuplicates++;
                    log.info("Duplicate transaction skipped for tenantId={}: [Date={}, Desc='{}', Amount={}, Balance={}]",
                        organizationId, txnDate, description, amount, balance);
                } else {
                    BankStatement statement = BankStatement.builder()
                        .organizationId(organizationId)
                        .document(document)
                        .txnDate(txnDate)
                        .description(description)
                        .txnType(txnType)
                        .amount(amount)
                        .balance(balance)
                        .build();

                    bankStatementRepository.save(statement);
                    insertedCount++;
                }
            }

            // 5. Mark document as COMPLETED
            document.setProcessedStatus(ProcessedStatus.COMPLETED);
            documentRepository.save(document);

            log.info("Successfully completed Bank Statement documentId={}. Inserted: {}, Skipped Duplicates: {}",
                document.getId(), insertedCount, skippedDuplicates);

        } catch (Exception ex) {
            log.error("Failed to process Bank Statement documentId={}: {}", document.getId(), ex.getMessage(), ex);
            document.setProcessedStatus(ProcessedStatus.FAILED);
            documentRepository.save(document);
        }
    }

    /**
     * Helper method returning mocked CSV lines for initial pipeline testing.
     * Contains an intentional duplicate line to verify deduplication.
     */
    public List<String> mockReadCsvLines(Document doc) {
        return List.of(
            "2026-08-30,Salary Credit,CREDIT,50000.00,150000.00",
            "2026-08-30,Salary Credit,CREDIT,50000.00,150000.00", // intentional duplicate
            "2026-08-31,Office Rent,DEBIT,15000.00,135000.00"
        );
    }
}
