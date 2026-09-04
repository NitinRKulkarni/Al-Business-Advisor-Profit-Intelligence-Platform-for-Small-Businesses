package com.omnicfo.repository;

import com.omnicfo.model.entity.WhatsAppInsight;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface WhatsAppInsightRepository extends JpaRepository<WhatsAppInsight, UUID> {
    List<WhatsAppInsight> findByOrganizationIdOrderByCreatedAtDesc(UUID organizationId);
    Optional<WhatsAppInsight> findTopByOrganizationIdOrderByCreatedAtDesc(UUID organizationId);
    Optional<WhatsAppInsight> findByDocumentId(UUID documentId);
}
