package com.omnicfo.service;

import com.omnicfo.model.entity.Document;
import com.omnicfo.model.enums.FileType;
import com.omnicfo.model.enums.ProcessedStatus;
import com.omnicfo.repository.DocumentRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.List;

/**
 * Scheduled FIFO poller service to trigger asynchronous Python AI extraction for pending invoices.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class InvoiceTriggerService {

    private final DocumentRepository documentRepository;
    private final RestClient aiPythonRestClient;

    @Value("${ai.service.python.invoice-endpoint}")
    private String invoiceEndpoint;

    /**
     * Polls the database every 30 seconds for the oldest PENDING invoices (FIFO),
     * marks them as PROCESSING, and triggers the Python AI service asynchronously.
     */
    @Scheduled(fixedDelay = 30000)
    public void pollAndTriggerInvoices() {
        List<Document> pendingInvoices = documentRepository.findTop10ByProcessedStatusAndFileTypeOrderByUploadDateAsc(
            ProcessedStatus.PENDING,
            FileType.INVOICE
        );

        if (pendingInvoices.isEmpty()) {
            return;
        }

        log.info("Found {} pending invoice(s) for AI processing queue.", pendingInvoices.size());

        for (Document document : pendingInvoices) {
            // 1. Immediately transition to PROCESSING to prevent double-polling
            document.setProcessedStatus(ProcessedStatus.PROCESSING);
            documentRepository.save(document);
            log.info("Marked documentId={} as PROCESSING.", document.getId());

            // 2. Prepare payload
            MultiValueMap<String, String> bodyMap = new LinkedMultiValueMap<>();
            bodyMap.add("document_id", document.getId().toString());

            // 3. Fire-and-forget HTTP POST to Python AI service
            try {
                aiPythonRestClient.post()
                    .uri(invoiceEndpoint)
                    .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                    .body(bodyMap)
                    .retrieve()
                    .toBodilessEntity();

                log.info("Successfully dispatched trigger to Python AI service for documentId={}", document.getId());
            } catch (RestClientException ex) {
                log.error("RestClientException calling Python AI service for documentId={}: {}", document.getId(), ex.getMessage());
                markAsFailed(document);
            } catch (Exception ex) {
                log.error("Unexpected error calling Python AI service for documentId={}: {}", document.getId(), ex.getMessage(), ex);
                markAsFailed(document);
            }
        }
    }

    private void markAsFailed(Document document) {
        document.setProcessedStatus(ProcessedStatus.FAILED);
        documentRepository.save(document);
        log.warn("Marked documentId={} as FAILED due to trigger failure.", document.getId());
    }
}
