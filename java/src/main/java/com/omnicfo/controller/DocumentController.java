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
        @RequestParam("fileType") String fileType
    ) {
        log.info("Received file upload request from tenant={} for fileName='{}', fileType='{}'",
            organizationId, file != null ? file.getOriginalFilename() : "null", fileType);

        DocumentUploadResponse response = documentService.uploadDocument(organizationId, file, fileType);

        return ResponseEntity.status(HttpStatus.CREATED).body(response);
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
}
