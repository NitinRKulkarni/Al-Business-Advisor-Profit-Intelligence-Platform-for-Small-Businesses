package com.omnicfo.model.entity;

import com.omnicfo.model.enums.FileType;
import com.omnicfo.model.enums.ProcessedStatus;
import jakarta.persistence.Basic;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

/**
 * Represents an uploaded file/document record staged for ingestion and processing.
 * Unique constraint on (organization_id, file_hash) prevents duplicate uploads per tenant.
 */
@Entity
@Table(
    name = "documents",
    uniqueConstraints = {
        @UniqueConstraint(
            name = "uk_documents_organization_file_hash",
            columnNames = {"organization_id", "file_hash"}
        )
    }
)
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Document {

    @Id
    @Column(name = "id", updatable = false, nullable = false)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "organization_id", nullable = false)
    private Organization organization;

    @Column(name = "file_name", nullable = false)
    private String fileName;

    @Enumerated(EnumType.STRING)
    @Column(name = "file_type", nullable = false, length = 50)
    private FileType fileType;

    @Column(name = "file_hash", nullable = false, length = 64)
    private String fileHash;

    /**
     * Stored binary payload (BLOB) as PostgreSQL BYTEA.
     */
    @Basic(fetch = FetchType.LAZY)
    @Column(name = "file_data", columnDefinition = "BYTEA")
    private byte[] fileData;

    @Builder.Default
    @Enumerated(EnumType.STRING)
    @Column(name = "processed_status", nullable = false, length = 50)
    private ProcessedStatus processedStatus = ProcessedStatus.PENDING;

    @Builder.Default
    @CreationTimestamp
    @Column(name = "upload_date", nullable = false, updatable = false)
    private Instant uploadDate = Instant.now();

    @PrePersist
    public void prePersist() {
        if (this.id == null) {
            this.id = UUID.randomUUID();
        }
        if (this.uploadDate == null) {
            this.uploadDate = Instant.now();
        }
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Document document)) return false;
        return id != null && Objects.equals(id, document.id);
    }

    @Override
    public int hashCode() {
        return getClass().hashCode();
    }
}
