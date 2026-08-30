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
     * Retrieves all uploaded documents for a tenant, optionally filtered by fileType.
     *
     * @param organizationId UUID of the tenant organization
     * @param fileType optional file type filter
     * @return list of DocumentResponseDTO sorted by upload date descending
     */
    List<DocumentResponseDTO> getDocuments(UUID organizationId, String fileType);
}
