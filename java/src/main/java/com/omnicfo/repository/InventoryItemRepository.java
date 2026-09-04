package com.omnicfo.repository;

import com.omnicfo.model.entity.InventoryItem;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface InventoryItemRepository extends JpaRepository<InventoryItem, UUID> {
    List<InventoryItem> findByOrganizationIdOrderByCreatedAtDesc(UUID organizationId);
    List<InventoryItem> findByDocumentId(UUID documentId);
}
