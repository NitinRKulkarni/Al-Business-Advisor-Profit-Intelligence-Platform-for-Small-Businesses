package com.omnicfo.repository;

import com.omnicfo.model.entity.Document;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface DocumentRepository extends JpaRepository<Document, UUID> {

    /**
     * Checks if a document with the given SHA-256 hash already exists for a specific tenant.
     *
     * @param organizationId tenant organization UUID
     * @param fileHash SHA-256 hex string of the file content
     * @return true if duplicate exists, false otherwise
     */
    boolean existsByOrganizationIdAndFileHash(UUID organizationId, String fileHash);

    /**
     * Retrieves a document by organization and file hash.
     */
    Optional<Document> findByOrganizationIdAndFileHash(UUID organizationId, String fileHash);

    /**
     * Retrieves all documents belonging to a specific organization.
     */
    List<Document> findByOrganizationId(UUID organizationId);

    /**
     * Fetch all documents for a tenant, sorted by newest first.
     */
    List<Document> findByOrganizationIdOrderByUploadDateDesc(UUID organizationId);

    /**
     * Fetch documents for a tenant filtered by type, sorted by newest first.
     */
    List<Document> findByOrganizationIdAndFileTypeOrderByUploadDateDesc(UUID organizationId, com.omnicfo.model.enums.FileType fileType);

    /**
     * Fetch top 10 documents in strict FIFO order (oldest first) matching processed status and file type.
     */
    List<Document> findTop10ByProcessedStatusAndFileTypeOrderByUploadDateAsc(
        com.omnicfo.model.enums.ProcessedStatus processedStatus,
        com.omnicfo.model.enums.FileType fileType
    );

    /**
     * Fetch top 5 documents in strict FIFO order (oldest first) matching processed status and file type.
     */
    List<Document> findTop5ByProcessedStatusAndFileTypeOrderByUploadDateAsc(
        com.omnicfo.model.enums.ProcessedStatus processedStatus,
        com.omnicfo.model.enums.FileType fileType
    );
}



