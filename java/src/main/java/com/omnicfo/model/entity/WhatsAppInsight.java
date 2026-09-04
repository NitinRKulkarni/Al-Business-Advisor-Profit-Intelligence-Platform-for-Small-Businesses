package com.omnicfo.model.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

/**
 * Represents aggregate AI business intelligence and demand intelligence extracted from WhatsApp chats.
 */
@Entity
@Table(name = "whatsapp_insights")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class WhatsAppInsight {

    @Id
    @Column(name = "id", updatable = false, nullable = false)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "document_id", nullable = false, unique = true)
    private Document document;

    @Column(name = "organization_id", nullable = false)
    private UUID organizationId;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "demand_intelligence", columnDefinition = "JSONB")
    private String demandIntelligence;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "customer_enquiries", columnDefinition = "JSONB")
    private String customerEnquiries;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "customer_sentiment", columnDefinition = "JSONB")
    private String customerSentiment;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "unmet_demands", columnDefinition = "JSONB")
    private String unmetDemands;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "potential_leads", columnDefinition = "JSONB")
    private String potentialLeads;

    @Builder.Default
    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt = Instant.now();

    @PrePersist
    public void prePersist() {
        if (this.id == null) {
            this.id = UUID.randomUUID();
        }
        if (this.createdAt == null) {
            this.createdAt = Instant.now();
        }
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof WhatsAppInsight that)) return false;
        return id != null && Objects.equals(id, that.id);
    }

    @Override
    public int hashCode() {
        return getClass().hashCode();
    }
}
