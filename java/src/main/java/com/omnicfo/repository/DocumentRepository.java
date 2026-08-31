package com.omnicfo.repository;

import com.omnicfo.model.entity.Document;
import com.omnicfo.model.enums.FileType;
import com.omnicfo.model.enums.ProcessedStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface DocumentRepository extends JpaRepository<Document, UUID> {

    /** Dedup check: has this tenant already uploaded a file with this hash? */
    Optional<Document> findByOrganizationIdAndFileHash(UUID organizationId, String fileHash);

    /** Tenant document listing, newest first. */
    List<Document> findByOrganizationIdOrderByUploadDateDesc(UUID organizationId);

    /** Tenant document listing filtered by type, newest first. */
    List<Document> findByOrganizationIdAndFileTypeOrderByUploadDateDesc(
            UUID organizationId, FileType fileType);

    /**
     * FIFO poller query: the 10 oldest PENDING invoices to dispatch to the
     * Python AI extraction service.
     */
    List<Document> findTop10ByProcessedStatusAndFileTypeOrderByUploadDateAsc(
            ProcessedStatus processedStatus, FileType fileType);
}
