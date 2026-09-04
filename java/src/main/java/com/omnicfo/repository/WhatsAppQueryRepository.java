package com.omnicfo.repository;

import com.omnicfo.model.entity.WhatsAppQuery;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface WhatsAppQueryRepository extends JpaRepository<WhatsAppQuery, UUID> {
    List<WhatsAppQuery> findByOrganizationIdOrderByCreatedAtDesc(UUID organizationId);
    List<WhatsAppQuery> findByDocumentIdOrderByCreatedAtDesc(UUID documentId);
}
