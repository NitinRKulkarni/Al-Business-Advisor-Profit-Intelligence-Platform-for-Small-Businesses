package com.omnicfo.controller;

import com.omnicfo.dto.DocumentResponseDTO;
import com.omnicfo.model.enums.FileType;
import com.omnicfo.service.DocumentService;
import org.springframework.http.HttpStatus;
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

@RestController
@RequestMapping("/api/v1/files")
public class DocumentController {

    private final DocumentService documentService;

    public DocumentController(DocumentService documentService) {
        this.documentService = documentService;
    }

    /** Upload a document. Tenant is taken from the mandatory X-Tenant-ID header. */
    @PostMapping("/upload")
    public ResponseEntity<DocumentResponseDTO> upload(
            @RequestHeader("X-Tenant-ID") UUID tenantId,
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "fileType", defaultValue = "Invoice") String fileType) {

        DocumentResponseDTO dto = documentService.uploadDocument(
                tenantId, file, FileType.fromString(fileType));
        return ResponseEntity.status(HttpStatus.CREATED).body(dto);
    }

    /** List a tenant's documents, optionally filtered by fileType, newest first. */
    @GetMapping
    public ResponseEntity<List<DocumentResponseDTO>> list(
            @RequestHeader("X-Tenant-ID") UUID tenantId,
            @RequestParam(value = "fileType", required = false) String fileType) {

        FileType type = (fileType == null || fileType.isBlank())
                ? null : FileType.fromString(fileType);
        return ResponseEntity.ok(documentService.listDocuments(tenantId, type));
    }
}
