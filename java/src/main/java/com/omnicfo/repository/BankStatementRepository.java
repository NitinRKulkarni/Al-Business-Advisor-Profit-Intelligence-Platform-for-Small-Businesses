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

    boolean existsByOrganizationIdAndTxnDateAndDescriptionAndAmountAndBalance(
        UUID organizationId,
        LocalDate txnDate,
        String description,
        BigDecimal amount,
        BigDecimal balance
    );

    List<BankStatement> findByOrganizationIdOrderByTxnDateDesc(UUID organizationId);

    List<BankStatement> findByOrganizationIdAndReconciliationStatus(UUID organizationId, String reconciliationStatus);

    List<BankStatement> findByOrganizationIdAndReconciliationStatusAndTxnType(UUID organizationId, String reconciliationStatus, String txnType);
}
