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
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Scheduled FIFO poller service to trigger asynchronous Python AI extraction
 * dynamically routing by source (invoice, image_invoice, whatsapp).
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AiDocumentTriggerService {

    private final DocumentRepository documentRepository;
    private final RestClient aiPythonRestClient;

    @Value("${ai.service.python.extract-endpoint:/api/v1/extract}")
    private String extractEndpoint;

    private static final Set<String> IMAGE_EXTENSIONS = Set.of("jpg", "jpeg", "png", "webp", "bmp", "tiff");

    /**
     * Polls the database every 10 seconds for pending AI documents in FIFO order,
     * marks them as PROCESSING, and triggers the Python AI service dynamically.
     */
    @Scheduled(initialDelay = 1000, fixedDelay = 10000)
    public void pollAndTriggerAiProcessing() {
        List<Document> pendingDocs = documentRepository.findTop10ByProcessedStatusAndFileTypeInOrderByUploadDateAsc(
            ProcessedStatus.PENDING,
            List.of(FileType.INVOICE, FileType.WHATSAPP_CHAT)
        );

        if (pendingDocs.isEmpty()) {
            return;
        }

        log.info("Found {} pending document(s) for AI processing queue.", pendingDocs.size());

        for (Document document : pendingDocs) {
            String source = resolveSource(document);
            if (source == null) {
                log.warn("Skipping documentId={} with unrecognized source mapping.", document.getId());
                continue;
            }

            // 1. Transition to PROCESSING
            document.setProcessedStatus(ProcessedStatus.PROCESSING);
            documentRepository.save(document);
            log.info("Marked documentId={} as PROCESSING (source={}).", document.getId(), source);

            // 2. Prepare JSON payload
            Map<String, String> requestPayload = Map.of(
                "document_id", document.getId().toString(),
                "source", source
            );

            // 3. Fire-and-forget HTTP POST to Python AI service
            try {
                aiPythonRestClient.post()
                    .uri(extractEndpoint)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(requestPayload)
                    .retrieve()
                    .toBodilessEntity();

                log.info("Successfully dispatched AI trigger for documentId={} with source={}", document.getId(), source);
            } catch (RestClientException ex) {
                log.error("RestClientException calling Python AI service for documentId={}: {}", document.getId(), ex.getMessage());
                markAsFailed(document);
            } catch (Exception ex) {
                log.error("Unexpected error calling Python AI service for documentId={}: {}", document.getId(), ex.getMessage(), ex);
                markAsFailed(document);
            }
        }
    }

    /**
     * Dynamically determines the source parameter based on fileType and extension.
     */
    public String resolveSource(Document document) {
        if (document.getFileType() == FileType.WHATSAPP_CHAT) {
            return "whatsapp";
        }

        if (document.getFileType() == FileType.INVOICE) {
            String fileName = document.getFileName() != null ? document.getFileName().toLowerCase() : "";
            int dotIdx = fileName.lastIndexOf('.');
            String ext = dotIdx > 0 ? fileName.substring(dotIdx + 1) : "";
            if (IMAGE_EXTENSIONS.contains(ext)) {
                return "image_invoice";
            }
            return "invoice"; // default to PDF invoice parser
        }

        return null;
    }

    private void markAsFailed(Document document) {
        document.setProcessedStatus(ProcessedStatus.FAILED);
        documentRepository.save(document);
        log.warn("Marked documentId={} as FAILED due to trigger failure.", document.getId());
    }
}
