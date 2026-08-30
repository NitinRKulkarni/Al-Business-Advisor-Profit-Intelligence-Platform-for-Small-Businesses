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
 * checks,
 * tenant validation, and document persistence.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentServiceImpl implements DocumentService {

    private final OrganizationRepository organizationRepository;
    private final DocumentRepository documentRepository;

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

        // 2. Read MultipartFile bytes and compute SHA-256 hash
        String fileHash = calculateSha256(file);
        log.debug("Computed SHA-256 hash [{}] for file [{}]", fileHash, file.getOriginalFilename());

        // 3. Check if document already exists for this tenant
        if (documentRepository.existsByOrganizationIdAndFileHash(organizationId, fileHash)) {
            log.warn("Duplicate upload detected for tenantId={} with fileHash={}", organizationId, fileHash);
            throw new DuplicateDocumentException(
                    "A document with the exact same content (SHA-256: " + fileHash
                            + ") has already been uploaded for this organization.");
        }

        // Parse and validate FileType
        FileType parsedFileType = FileType.fromString(fileType);

        // Clean original file name
        String rawFilename = file.getOriginalFilename();
        String cleanFileName = StringUtils.hasText(rawFilename)
                ? StringUtils.cleanPath(Objects.requireNonNull(rawFilename))
                : "unknown_file";

        // Mock physical S3 upload (e.g.
        // s3://omnicfo-bucket/{tenantId}/{fileHash}_{fileName})
        mockS3Upload(organizationId, cleanFileName, fileHash);

        // 4. Construct Document entity
        Document document = Document.builder()
                .organization(organization)
                .fileName(cleanFileName)
                .fileType(parsedFileType)
                .fileHash(fileHash)
                .processedStatus(ProcessedStatus.PENDING)
                .build();

        // 5. Save entity to database
        Document savedDocument = documentRepository.save(document);
        log.info("Document successfully persisted with ID={} for tenantId={}", savedDocument.getId(), organizationId);

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

    /**
     * Computes the SHA-256 hash of a MultipartFile and converts it to a hexadecimal
     * string.
     */
    private String calculateSha256(MultipartFile file) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hashBytes = digest.digest(file.getBytes());
            return HexFormat.of().formatHex(hashBytes);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 algorithm not available in current JVM runtime", e);
        } catch (IOException e) {
            throw new IllegalArgumentException("Failed to read bytes from uploaded file: " + file.getOriginalFilename(),
                    e);
        }
    }

    /**
     * Mock placeholder for S3 physical file storage integration.
     */
    private void mockS3Upload(UUID organizationId, String fileName, String fileHash) {
        log.info("[MOCK S3] Storing file [{}] with hash [{}] under s3://omni-cfo-storage/{}/{}",
                fileName, fileHash, organizationId, fileName);
    }
}
