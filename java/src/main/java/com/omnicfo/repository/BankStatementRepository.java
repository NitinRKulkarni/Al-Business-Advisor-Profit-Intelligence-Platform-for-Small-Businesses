package com.omnicfo.repository;

import com.omnicfo.model.entity.BankStatement;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

@Repository
public interface BankStatementRepository extends JpaRepository<BankStatement, UUID> {

    /**
     * Checks if a transaction row with identical attributes already exists for the organization.
     * Prevents duplicate insertions across overlapping bank statement files.
     */
    boolean existsByOrganizationIdAndTxnDateAndDescriptionAndAmountAndBalance(
        UUID organizationId,
        LocalDate txnDate,
        String description,
        BigDecimal amount,
        BigDecimal balance
    );

    /**
     * Retrieves all bank statement transactions for a specific tenant.
     */
    List<BankStatement> findByOrganizationIdOrderByTxnDateDesc(UUID organizationId);
}
