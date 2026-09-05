package com.omnicfo.service;

import com.omnicfo.model.dto.DocumentResponseDTO;
import com.omnicfo.model.dto.DocumentUploadResponse;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.UUID;

/**
 * Service interface for handling document upload ingestion and deduplication.
 */
public interface DocumentService {

    /**
     * Uploads and ingests a document for a specific tenant organization.
     * Computes SHA-256 hash to prevent duplicate uploads per tenant.
     *
     * @param organizationId UUID of the tenant organization
     * @param file binary payload of the document
     * @param fileType business classification of the file (e.g., Invoice, WhatsAppChat, BankStmt, Inventory)
     * @return DTO with generated document ID, metadata, and ingestion status
     */
    DocumentUploadResponse uploadDocument(UUID organizationId, MultipartFile file, String fileType);

    /**
     * Uploads and ingests multiple documents in a batch for a specific tenant organization.
     *
     * @param organizationId UUID of the tenant organization
     * @param files list of binary files
     * @param fileTypes list of corresponding file types or single fallback type
     * @return list of DocumentUploadResponse DTOs
     */
    List<DocumentUploadResponse> uploadBatchDocuments(UUID organizationId, List<MultipartFile> files, List<String> fileTypes);

    /**
     * Uploads and ingests multiple documents in a batch for a specific tenant organization with a global sourceType fallback.
     */
    List<DocumentUploadResponse> uploadBatchDocuments(UUID organizationId, List<MultipartFile> files, List<String> fileTypes, String sourceType);

    /**
     * Retrieves all uploaded documents for a tenant, optionally filtered by fileType.
     *
     * @param organizationId UUID of the tenant organization
     * @param fileType optional file type filter
     * @return list of DocumentResponseDTO sorted by upload date descending
     */
    List<DocumentResponseDTO> getDocuments(UUID organizationId, String fileType);

    /**
     * Retrieves a specific document entity including fileData byte payload for a tenant.
     *
     * @param organizationId UUID of the tenant organization
     * @param documentId UUID of the document
     * @return Document entity
     */
    com.omnicfo.model.entity.Document getDocumentById(UUID organizationId, UUID documentId);

    /**
     * Resets a document's status to PENDING to trigger automated re-processing.
     *
     * @param organizationId UUID of the tenant organization
     * @param documentId UUID of the document
     * @return updated DocumentResponseDTO
     */
    DocumentResponseDTO retryDocument(UUID organizationId, UUID documentId);
}
