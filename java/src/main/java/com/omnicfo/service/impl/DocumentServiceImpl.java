package com.omnicfo.service.impl;

import com.omnicfo.exception.DuplicateDocumentException;
import com.omnicfo.exception.OrganizationNotFoundException;
import com.omnicfo.model.dto.DocumentResponseDTO;
import com.omnicfo.model.dto.DocumentUploadResponse;
import com.omnicfo.model.entity.Document;
import com.omnicfo.model.entity.Organization;
import com.omnicfo.model.enums.FileType;
import com.omnicfo.model.enums.ProcessedStatus;
import com.omnicfo.repository.DocumentRepository;
import com.omnicfo.repository.OrganizationRepository;
import com.omnicfo.service.DocumentService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * Implementation of DocumentService providing file hashing, deduplication
 * checks, tenant validation, and in-database BLOB document persistence.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentServiceImpl implements DocumentService {

    private final OrganizationRepository organizationRepository;
    private final DocumentRepository documentRepository;
    private final com.omnicfo.service.InventoryCsvService inventoryCsvService;

    @Override
    @Transactional
    public DocumentUploadResponse uploadDocument(UUID organizationId, MultipartFile file, String fileType) {
        log.info("Initiating upload for tenantId={}, fileType={}", organizationId, fileType);

        // 0. Preliminary input validation
        if (organizationId == null) {
            throw new IllegalArgumentException("Tenant organization ID must not be null");
        }
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("Uploaded file must not be null or empty");
        }

        // 1. Validate Organization exists
        Organization organization = organizationRepository.findById(organizationId)
                .orElseThrow(() -> new OrganizationNotFoundException(
                        "Organization not found with ID: " + organizationId));

        // 2. Read bytes and compute SHA-256 hash
        byte[] fileBytes;
        try {
            fileBytes = file.getBytes();
        } catch (IOException e) {
            throw new IllegalArgumentException("Failed to read bytes from uploaded file: " + file.getOriginalFilename(), e);
        }

        String fileHash = calculateSha256(fileBytes);
        log.debug("Computed SHA-256 hash [{}] for file [{}]", fileHash, file.getOriginalFilename());

        // Parse and validate FileType
        FileType parsedFileType = FileType.fromString(fileType);

        // Clean original file name
        String rawFilename = file.getOriginalFilename();
        String cleanFileName = StringUtils.hasText(rawFilename)
                ? StringUtils.cleanPath(Objects.requireNonNull(rawFilename))
                : "unknown_file";

        // 3. Deduplication & Failure-Recovery check
        java.util.Optional<Document> existingDocOpt = documentRepository.findByOrganizationIdAndFileHash(organizationId, fileHash);
        Document savedDocument;

        if (existingDocOpt.isPresent()) {
            Document existingDoc = existingDocOpt.get();
            if (existingDoc.getProcessedStatus() == ProcessedStatus.FAILED) {
                log.info("Allowing re-submission and overwriting previously FAILED document ID={} for tenantId={}", existingDoc.getId(), organizationId);
                existingDoc.setFileName(cleanFileName);
                existingDoc.setFileType(parsedFileType);
                existingDoc.setFileData(fileBytes);
                existingDoc.setProcessedStatus(ProcessedStatus.PENDING);
                existingDoc.setUploadDate(java.time.Instant.now());
                savedDocument = documentRepository.save(existingDoc);
            } else {
                log.warn("Duplicate upload detected for tenantId={} with fileHash={}, current status={}", 
                    organizationId, fileHash, existingDoc.getProcessedStatus());
                throw new DuplicateDocumentException(
                        "A document with the exact same content (SHA-256: " + fileHash
                                + ") has already been uploaded for this organization (Current status: " 
                                + existingDoc.getProcessedStatus() + ").");
            }
        } else {
            // 4. Construct Document entity with in-database BLOB bytes
            Document document = Document.builder()
                    .organization(organization)
                    .fileName(cleanFileName)
                    .fileType(parsedFileType)
                    .fileHash(fileHash)
                    .fileData(fileBytes)
                    .processedStatus(ProcessedStatus.PENDING)
                    .build();

            // 5. Save entity to database
            savedDocument = documentRepository.save(document);
            log.info("Document successfully persisted with ID={} (BLOB size={} bytes) for tenantId={}", 
                savedDocument.getId(), fileBytes.length, organizationId);
        }

        // 6. Direct routing for Ground-Truth CSV Inventory Stock
        String normalizedType = (fileType != null ? fileType : "").toLowerCase().replace("_", "");
        if (normalizedType.contains("inventory") || parsedFileType == FileType.CSV_INVENTORY || parsedFileType == FileType.INVENTORY) {
            try {
                int count = inventoryCsvService.ingestInventoryCsv(organizationId, savedDocument, file);
                savedDocument.setProcessedStatus(ProcessedStatus.COMPLETED);
                documentRepository.save(savedDocument);
                log.info("Directly ingested {} inventory stock items from CSV for docId={}", count, savedDocument.getId());
                return DocumentUploadResponse.builder()
                        .documentId(savedDocument.getId())
                        .fileName(savedDocument.getFileName())
                        .fileType(savedDocument.getFileType().getDisplayName())
                        .fileHash(savedDocument.getFileHash())
                        .status(ProcessedStatus.COMPLETED)
                        .uploadDate(savedDocument.getUploadDate())
                        .message("Inventory stock CSV parsed successfully (" + count + " items logged to inventory).")
                        .build();
            } catch (Exception e) {
                log.error("Failed to parse CSV inventory: {}", e.getMessage(), e);
            }
        }

        // Return saved Document DTO
        return DocumentUploadResponse.builder()
                .documentId(savedDocument.getId())
                .fileName(savedDocument.getFileName())
                .fileType(savedDocument.getFileType().getDisplayName())
                .fileHash(savedDocument.getFileHash())
                .status(savedDocument.getProcessedStatus())
                .uploadDate(savedDocument.getUploadDate())
                .message("File uploaded successfully and queued for processing.")
                .build();
    }

    @Override
    @Transactional
    public List<DocumentUploadResponse> uploadBatchDocuments(UUID organizationId, List<MultipartFile> files, List<String> fileTypes) {
        return uploadBatchDocuments(organizationId, files, fileTypes, null);
    }

    @Override
    @Transactional
    public List<DocumentUploadResponse> uploadBatchDocuments(UUID organizationId, List<MultipartFile> files, List<String> fileTypes, String sourceType) {
        log.info("Initiating batch upload for tenantId={}, fileCount={}, defaultSourceType={}", 
            organizationId, files != null ? files.size() : 0, sourceType);

        if (organizationId == null) {
            throw new IllegalArgumentException("Tenant organization ID must not be null");
        }
        if (files == null || files.isEmpty()) {
            throw new IllegalArgumentException("Uploaded files list must not be null or empty");
        }

        List<DocumentUploadResponse> responses = new java.util.ArrayList<>();

        for (int i = 0; i < files.size(); i++) {
            MultipartFile file = files.get(i);
            if (file == null || file.isEmpty()) continue;

            String type = (fileTypes != null && i < fileTypes.size() && StringUtils.hasText(fileTypes.get(i)))
                    ? fileTypes.get(i)
                    : (StringUtils.hasText(sourceType))
                    ? sourceType
                    : (fileTypes != null && !fileTypes.isEmpty() && StringUtils.hasText(fileTypes.get(0)))
                    ? fileTypes.get(0)
                    : "Invoice";

            try {
                DocumentUploadResponse res = uploadDocument(organizationId, file, type);
                responses.add(res);
            } catch (DuplicateDocumentException e) {
                log.warn("Duplicate file skipped in batch for file={}: {}", file.getOriginalFilename(), e.getMessage());
                responses.add(DocumentUploadResponse.builder()
                        .fileName(file.getOriginalFilename())
                        .fileType(type)
                        .message("Notice: Exact document content already uploaded and indexed.")
                        .build());
            } catch (Exception e) {
                log.error("Error uploading file {} in batch: {}", file.getOriginalFilename(), e.getMessage(), e);
                responses.add(DocumentUploadResponse.builder()
                        .fileName(file.getOriginalFilename())
                        .fileType(type)
                        .message("Error: " + e.getMessage())
                        .build());
            }
        }

        return responses;
    }

    @Override
    @Transactional(readOnly = true)
    public List<DocumentResponseDTO> getDocuments(UUID organizationId, String fileType) {
        log.info("Fetching documents for tenantId={}, fileTypeFilter='{}'", organizationId, fileType);

        if (organizationId == null) {
            throw new IllegalArgumentException("Tenant organization ID must not be null");
        }

        List<Document> documents;
        if (StringUtils.hasText(fileType)) {
            FileType parsedFileType = FileType.fromString(fileType);
            documents = documentRepository.findByOrganizationIdAndFileTypeOrderByUploadDateDesc(organizationId,
                    parsedFileType);
        } else {
            documents = documentRepository.findByOrganizationIdOrderByUploadDateDesc(organizationId);
        }

        return documents.stream()
                .map(doc -> DocumentResponseDTO.builder()
                        .documentId(doc.getId())
                        .fileName(doc.getFileName())
                        .fileType(doc.getFileType() != null ? doc.getFileType().getDisplayName() : null)
                        .processedStatus(doc.getProcessedStatus() != null ? doc.getProcessedStatus().name() : null)
                        .uploadDate(doc.getUploadDate())
                        .build())
                .toList();
    }

    @Override
    @Transactional(readOnly = true)
    public Document getDocumentById(UUID organizationId, UUID documentId) {
        log.info("Fetching document bytes for tenantId={}, docId={}", organizationId, documentId);
        if (organizationId == null) {
            throw new IllegalArgumentException("Tenant organization ID must not be null");
        }
        if (documentId == null) {
            throw new IllegalArgumentException("Document ID must not be null");
        }

        Document document = documentRepository.findById(documentId)
                .orElseThrow(() -> new IllegalArgumentException("Document not found with ID: " + documentId));

        if (!document.getOrganization().getId().equals(organizationId)) {
            throw new IllegalArgumentException("Unauthorized: Document does not belong to the requesting tenant organization");
        }

        return document;
    }

    @Override
    @Transactional
    public DocumentResponseDTO retryDocument(UUID organizationId, UUID documentId) {
        log.info("Retrying processing for tenantId={}, docId={}", organizationId, documentId);
        Document document = getDocumentById(organizationId, documentId);

        // Reset status to PENDING so background schedulers pick it up
        document.setProcessedStatus(ProcessedStatus.PENDING);
        document.setUploadDate(java.time.Instant.now());
        Document saved = documentRepository.save(document);

        return DocumentResponseDTO.builder()
                .documentId(saved.getId())
                .fileName(saved.getFileName())
                .fileType(saved.getFileType() != null ? saved.getFileType().getDisplayName() : null)
                .processedStatus(saved.getProcessedStatus() != null ? saved.getProcessedStatus().name() : null)
                .uploadDate(saved.getUploadDate())
                .build();
    }

    /**
     * Computes the SHA-256 hash of a byte array and converts it to a hexadecimal string.
     */
    private String calculateSha256(byte[] data) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hashBytes = digest.digest(data);
            return HexFormat.of().formatHex(hashBytes);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 algorithm not available in current JVM runtime", e);
        }
    }
}
