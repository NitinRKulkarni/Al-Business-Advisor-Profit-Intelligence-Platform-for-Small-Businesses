package com.omnicfo.repository;

import com.omnicfo.model.entity.Invoice;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface InvoiceRepository extends JpaRepository<Invoice, UUID> {

    List<Invoice> findByOrganizationIdOrderByCreatedAtDesc(UUID organizationId);

    List<Invoice> findByOrganizationIdAndPaymentStatus(UUID organizationId, String paymentStatus);

    Optional<Invoice> findByOrganizationIdAndInvoiceNumberIgnoreCase(UUID organizationId, String invoiceNumber);

    Optional<Invoice> findByDocumentId(UUID documentId);

    @Query("SELECT i FROM Invoice i WHERE i.organizationId = :orgId AND LOWER(:description) LIKE CONCAT('%', LOWER(i.invoiceNumber), '%') AND i.invoiceNumber IS NOT NULL AND LENGTH(i.invoiceNumber) >= 3")
    List<Invoice> findCandidatesByDescription(@Param("orgId") UUID orgId, @Param("description") String description);
}
