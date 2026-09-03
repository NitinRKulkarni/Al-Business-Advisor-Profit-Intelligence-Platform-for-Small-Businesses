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
import com.omnicfo.service.WhatsAppProcessingService;
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
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentServiceImpl implements DocumentService {
    private final OrganizationRepository organizationRepository;
    private final DocumentRepository documentRepository;
    private final WhatsAppProcessingService whatsAppProcessingService;

    @Override
    @Transactional
    public DocumentUploadResponse uploadDocument(UUID organizationId, MultipartFile file, String fileType) {
        log.info("Initiating upload for tenantId={}, fileType={}", organizationId, fileType);
        if (organizationId == null) {
            throw new IllegalArgumentException("Tenant organization ID must not be null");
        }
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("Uploaded file must not be null or empty");
        }

        Organization organization = organizationRepository.findById(organizationId)
            .orElseThrow(() -> new OrganizationNotFoundException(
                "Organization not found with ID: " + organizationId));
        String fileHash = calculateSha256(file);
        if (documentRepository.existsByOrganizationIdAndFileHash(organizationId, fileHash)) {
            throw new DuplicateDocumentException(
                "A document with the exact same content (SHA-256: " + fileHash
                    + ") has already been uploaded for this organization.");
        }

        FileType parsedFileType = FileType.fromString(fileType);
        String rawFilename = file.getOriginalFilename();
        String cleanFileName = StringUtils.hasText(rawFilename)
            ? StringUtils.cleanPath(Objects.requireNonNull(rawFilename))
            : "unknown_file";

        Document document = Document.builder()
            .organization(organization)
            .fileName(cleanFileName)
            .fileType(parsedFileType)
            .fileHash(fileHash)
            .processedStatus(parsedFileType == FileType.WHATSAPP_CHAT
                ? ProcessedStatus.PROCESSING
                : ProcessedStatus.PENDING)
            .build();
        Document savedDocument = documentRepository.save(document);

        List<Map<String, Object>> items = List.of();
        if (parsedFileType == FileType.WHATSAPP_CHAT) {
            try {
                items = whatsAppProcessingService.process(file);
                savedDocument.setProcessedStatus(ProcessedStatus.COMPLETED);
                documentRepository.save(savedDocument);
            } catch (RuntimeException e) {
                savedDocument.setProcessedStatus(ProcessedStatus.FAILED);
                documentRepository.save(savedDocument);
                throw e;
            }
        }

        return DocumentUploadResponse.builder()
            .documentId(savedDocument.getId())
            .fileName(savedDocument.getFileName())
            .fileType(savedDocument.getFileType().getDisplayName())
            .fileHash(savedDocument.getFileHash())
            .status(savedDocument.getProcessedStatus())
            .uploadDate(savedDocument.getUploadDate())
            .message(parsedFileType == FileType.WHATSAPP_CHAT
                ? "WhatsApp chat processed successfully."
                : "File uploaded successfully and queued for processing.")
            .items(items)
            .build();
    }

    @Override
    @Transactional(readOnly = true)
    public List<DocumentResponseDTO> getDocuments(UUID organizationId, String fileType) {
        if (organizationId == null) {
            throw new IllegalArgumentException("Tenant organization ID must not be null");
        }
        List<Document> documents;
        if (StringUtils.hasText(fileType)) {
            FileType parsedFileType = FileType.fromString(fileType);
            documents = documentRepository.findByOrganizationIdAndFileTypeOrderByUploadDateDesc(
                organizationId, parsedFileType);
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

    private String calculateSha256(MultipartFile file) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(file.getBytes()));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 algorithm not available in current JVM runtime", e);
        } catch (IOException e) {
            throw new IllegalArgumentException(
                "Failed to read bytes from file: " + file.getOriginalFilename(), e);
        }
    }
}
