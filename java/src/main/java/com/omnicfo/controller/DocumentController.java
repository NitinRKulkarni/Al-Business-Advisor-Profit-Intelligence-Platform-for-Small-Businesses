package com.omnicfo.controller;

import com.omnicfo.model.dto.DocumentResponseDTO;
import com.omnicfo.model.dto.DocumentUploadResponse;
import com.omnicfo.service.DocumentService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.UUID;

/**
 * REST Controller for document ingestion workflows.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/files")
@RequiredArgsConstructor
public class DocumentController {

    private final DocumentService documentService;

    /**
     * Uploads and ingests a document for the tenant specified in the X-Tenant-ID header.
     *
     * @param organizationId tenant organization UUID provided via header
     * @param file binary payload of the document
     * @param fileType classification (e.g., Invoice, WhatsAppChat, BankStmt, Inventory)
     * @return 201 CREATED with DocumentUploadResponse DTO
     */
    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<DocumentUploadResponse> uploadDocument(
        @RequestHeader("X-Tenant-ID") UUID organizationId,
        @RequestParam("file") MultipartFile file,
        @RequestParam(value = "sourceType", required = false) String sourceType,
        @RequestParam(value = "fileType", required = false) String fileType
    ) {
        String effectiveType = (sourceType != null && !sourceType.isBlank()) ? sourceType : fileType;
        log.info("Received file upload request from tenant={} for fileName='{}', sourceType='{}'",
            organizationId, file != null ? file.getOriginalFilename() : "null", effectiveType);

        DocumentUploadResponse response = documentService.uploadDocument(organizationId, file, effectiveType);

        return ResponseEntity.status(HttpStatus.CREATED).body(response);
    }

    /**
     * Batch uploads and ingests multiple documents for the tenant specified in the X-Tenant-ID header.
     *
     * @param organizationId tenant organization UUID provided via header
     * @param files list of binary payloads of the documents
     * @param sourceType optional unified sourceType routing parameter
     * @param fileTypes optional list of classifications or fallback
     * @return 201 CREATED with list of DocumentUploadResponse DTOs
     */
    @PostMapping(value = "/batch-upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<List<DocumentUploadResponse>> uploadBatchDocuments(
        @RequestHeader("X-Tenant-ID") UUID organizationId,
        @RequestParam("files") List<MultipartFile> files,
        @RequestParam(value = "sourceType", required = false) String sourceType,
        @RequestParam(value = "fileTypes", required = false) List<String> fileTypes
    ) {
        log.info("Received batch upload request from tenant={} for {} file(s), sourceType={}",
            organizationId, files != null ? files.size() : 0, sourceType);

        List<DocumentUploadResponse> responses = documentService.uploadBatchDocuments(organizationId, files, fileTypes, sourceType);

        return ResponseEntity.status(HttpStatus.CREATED).body(responses);
    }

    /**
     * Fetches the list of uploaded documents and their processing statuses for a tenant.
     *
     * @param organizationId tenant organization UUID provided via header
     * @param fileType optional file type filter
     * @return 200 OK with list of DocumentResponseDTO
     */
    @GetMapping
    public ResponseEntity<List<DocumentResponseDTO>> getDocuments(
        @RequestHeader("X-Tenant-ID") UUID organizationId,
        @RequestParam(value = "fileType", required = false) String fileType
    ) {
        log.info("Received request to list documents for tenant={}, fileType='{}'", organizationId, fileType);

        List<DocumentResponseDTO> documents = documentService.getDocuments(organizationId, fileType);

        return ResponseEntity.ok(documents);
    }

    /**
     * Retrieves the raw file payload of an uploaded document for viewing or downloading.
     *
     * @param organizationId tenant organization UUID provided via header
     * @param documentId UUID of the document
     * @return 200 OK with binary file data and proper MIME headers
     */
    @GetMapping("/{documentId}/view")
    public ResponseEntity<byte[]> viewDocument(
        @RequestHeader("X-Tenant-ID") UUID organizationId,
        @org.springframework.web.bind.annotation.PathVariable("documentId") UUID documentId
    ) {
        log.info("Received request to view/stream file docId={} for tenant={}", documentId, organizationId);

        com.omnicfo.model.entity.Document document = documentService.getDocumentById(organizationId, documentId);

        byte[] fileBytes = document.getFileData();
        if (fileBytes == null || fileBytes.length == 0) {
            return ResponseEntity.noContent().build();
        }

        String fileName = document.getFileName() != null ? document.getFileName() : "document";
        String lowerName = fileName.toLowerCase();
        MediaType mediaType = MediaType.APPLICATION_OCTET_STREAM;

        if (lowerName.endsWith(".pdf")) {
            mediaType = MediaType.APPLICATION_PDF;
        } else if (lowerName.endsWith(".png")) {
            mediaType = MediaType.IMAGE_PNG;
        } else if (lowerName.endsWith(".jpg") || lowerName.endsWith(".jpeg")) {
            mediaType = MediaType.IMAGE_JPEG;
        } else if (lowerName.endsWith(".csv")) {
            mediaType = MediaType.parseMediaType("text/csv; charset=UTF-8");
        } else if (lowerName.endsWith(".txt")) {
            mediaType = MediaType.TEXT_PLAIN;
        } else if (lowerName.endsWith(".zip")) {
            mediaType = MediaType.parseMediaType("application/zip");
        }

        return ResponseEntity.ok()
                .contentType(mediaType)
                .header(org.springframework.http.HttpHeaders.CONTENT_DISPOSITION, "inline; filename=\"" + fileName + "\"")
                .header(org.springframework.http.HttpHeaders.ACCESS_CONTROL_EXPOSE_HEADERS, "Content-Disposition")
                .body(fileBytes);
    }

    /**
     * Retries processing for a previously uploaded or failed document.
     *
     * @param organizationId tenant organization UUID provided via header
     * @param documentId UUID of the document
     * @return 200 OK with updated DocumentResponseDTO
     */
    @PostMapping("/{documentId}/retry")
    public ResponseEntity<DocumentResponseDTO> retryDocument(
        @RequestHeader("X-Tenant-ID") UUID organizationId,
        @org.springframework.web.bind.annotation.PathVariable("documentId") UUID documentId
    ) {
        log.info("Received request to retry processing for docId={} and tenant={}", documentId, organizationId);
        DocumentResponseDTO response = documentService.retryDocument(organizationId, documentId);
        return ResponseEntity.ok(response);
    }
}
