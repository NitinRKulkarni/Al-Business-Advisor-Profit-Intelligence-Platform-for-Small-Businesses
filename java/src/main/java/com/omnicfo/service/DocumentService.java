package com.omnicfo.service;

import com.omnicfo.dto.DocumentResponseDTO;
import com.omnicfo.exception.ApiExceptions;
import com.omnicfo.model.entity.Document;
import com.omnicfo.model.entity.Organization;
import com.omnicfo.model.enums.FileType;
import com.omnicfo.repository.DocumentRepository;
import com.omnicfo.repository.OrganizationRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;

/**
 * Handles document ingestion: tenant validation, SHA-256 dedup, and storage of
 * the raw PDF bytes so the Python AI service can later fetch them by id.
 */
@Service
public class DocumentService {

    private final DocumentRepository documentRepository;
    private final OrganizationRepository organizationRepository;

    public DocumentService(DocumentRepository documentRepository,
                           OrganizationRepository organizationRepository) {
        this.documentRepository = documentRepository;
        this.organizationRepository = organizationRepository;
    }

    @Transactional
    public DocumentResponseDTO uploadDocument(UUID tenantId, MultipartFile file, FileType fileType) {
        Organization org = organizationRepository.findById(tenantId)
                .orElseThrow(() -> new ApiExceptions.TenantNotFoundException(
                        "No organization found for tenant id " + tenantId));

        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("Uploaded file is empty.");
        }

        byte[] bytes = readBytes(file);
        String hash = sha256(bytes);

        documentRepository.findByOrganizationIdAndFileHash(tenantId, hash)
                .ifPresent(d -> {
                    throw new ApiExceptions.DuplicateFileException(
                            "A file with this SHA256 hash has already been uploaded.");
                });

        Document doc = Document.builder()
                .organization(org)
                .fileName(file.getOriginalFilename())
                .fileType(fileType)
                .fileHash(hash)
                .fileData(bytes)  // store bytes so the Python service can retrieve them
                .build();

        Document saved = documentRepository.save(doc);
        return toDto(saved);
    }

    @Transactional(readOnly = true)
    public List<DocumentResponseDTO> listDocuments(UUID tenantId, FileType fileType) {
        organizationRepository.findById(tenantId)
                .orElseThrow(() -> new ApiExceptions.TenantNotFoundException(
                        "No organization found for tenant id " + tenantId));

        List<Document> docs = (fileType == null)
                ? documentRepository.findByOrganizationIdOrderByUploadDateDesc(tenantId)
                : documentRepository.findByOrganizationIdAndFileTypeOrderByUploadDateDesc(tenantId, fileType);

        return docs.stream().map(this::toDto).toList();
    }

    private DocumentResponseDTO toDto(Document d) {
        return new DocumentResponseDTO(
                d.getId(), d.getFileName(), d.getFileType(),
                d.getProcessedStatus(), d.getUploadDate());
    }

    private static byte[] readBytes(MultipartFile file) {
        try {
            return file.getBytes();
        } catch (IOException e) {
            throw new IllegalStateException("Failed to read uploaded file", e);
        }
    }

    private static String sha256(byte[] data) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(md.digest(data));
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 not available", e);
        }
    }
}
