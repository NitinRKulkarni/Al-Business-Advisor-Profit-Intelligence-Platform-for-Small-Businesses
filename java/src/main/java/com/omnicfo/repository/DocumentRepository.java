package com.omnicfo.repository;

import com.omnicfo.model.entity.Document;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface DocumentRepository extends JpaRepository<Document, UUID> {
    boolean existsByOrganizationIdAndFileHash(UUID organizationId, String fileHash);

    Optional<Document> findByOrganizationIdAndFileHash(UUID organizationId, String fileHash);

    List<Document> findByOrganizationId(UUID organizationId);

    List<Document> findByOrganizationIdOrderByUploadDateDesc(UUID organizationId);

    List<Document> findByOrganizationIdAndFileTypeOrderByUploadDateDesc(
        UUID organizationId,
        com.omnicfo.model.enums.FileType fileType
    );
}
