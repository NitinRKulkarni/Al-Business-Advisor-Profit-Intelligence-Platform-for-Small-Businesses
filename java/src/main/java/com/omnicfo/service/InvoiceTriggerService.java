package com.omnicfo.service;

import com.omnicfo.model.entity.Document;
import com.omnicfo.model.enums.FileType;
import com.omnicfo.model.enums.ProcessedStatus;
import com.omnicfo.repository.DocumentRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;

import java.util.List;

/**
 * Scheduled FIFO poller. Every 30s it picks up the oldest PENDING invoices,
 * flips them to PROCESSING (so no other node re-dispatches them), and calls the
 * external Python AI service at POST {base-url}{invoice-endpoint} with the
 * document_id as application/x-www-form-urlencoded.
 *
 * Fire-and-forget: on any error the document is marked FAILED. The Python
 * service itself updates the row to COMPLETED once extraction finishes.
 */
@Service
public class InvoiceTriggerService {

    private static final Logger log = LoggerFactory.getLogger(InvoiceTriggerService.class);

    private final DocumentRepository documentRepository;
    private final RestClient aiPythonRestClient;
    private final String invoiceEndpoint;

    public InvoiceTriggerService(
            DocumentRepository documentRepository,
            RestClient aiPythonRestClient,
            @Value("${ai.service.python.invoice-endpoint}") String invoiceEndpoint) {
        this.documentRepository = documentRepository;
        this.aiPythonRestClient = aiPythonRestClient;
        this.invoiceEndpoint = invoiceEndpoint;
    }

    @Scheduled(fixedDelay = 30000)
    public void pollAndDispatch() {
        List<Document> pending = fetchAndMarkProcessing();

        if (pending.isEmpty()) {
            return;
        }
        log.info("FIFO poller: dispatching {} pending invoice(s)", pending.size());

        for (Document doc : pending) {
            dispatch(doc);
        }
    }

    @Transactional
    public List<Document> fetchAndMarkProcessing() {
        List<Document> pending = documentRepository
                .findTop10ByProcessedStatusAndFileTypeOrderByUploadDateAsc(
                        ProcessedStatus.PENDING, FileType.INVOICE);

        for (Document doc : pending) {
            doc.setProcessedStatus(ProcessedStatus.PROCESSING);
            documentRepository.save(doc);
        }
        return pending;
    }

    private void dispatch(Document doc) {
        try {
            MultiValueMap<String, String> form = new LinkedMultiValueMap<>();
            form.add("document_id", doc.getId().toString());

            aiPythonRestClient.post()
                    .uri(invoiceEndpoint)
                    .body(form)
                    .retrieve()
                    .toBodilessEntity();

            log.info("Dispatched document_id={} to Python AI service", doc.getId());
        } catch (Exception ex) {
            log.error("Failed to dispatch document_id={}, marking FAILED", doc.getId(), ex);
            markFailed(doc.getId());
        }
    }

    @Transactional
    public void markFailed(java.util.UUID docId) {
        documentRepository.findById(docId).ifPresent(d -> {
            d.setProcessedStatus(ProcessedStatus.FAILED);
            documentRepository.save(d);
        });
    }
}
