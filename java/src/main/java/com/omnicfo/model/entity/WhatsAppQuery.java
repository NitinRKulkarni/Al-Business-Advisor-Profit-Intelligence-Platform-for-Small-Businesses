package com.omnicfo.model.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "whatsapp_queries")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class WhatsAppQuery {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "document_id", nullable = false)
    private Document document;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "organization_id", nullable = false)
    private Organization organization;

    @Column(name = "customer_name")
    private String customerName;

    @Column(name = "sender", nullable = false)
    private String sender;

    @Column(name = "raw_message", nullable = false, columnDefinition = "TEXT")
    private String rawMessage;

    @Column(name = "intent", nullable = false)
    private String intent;

    @Column(name = "item_demanded")
    private String itemDemanded;

    @Column(name = "requested_quantity", precision = 12, scale = 3)
    private BigDecimal requestedQuantity;

    @Column(name = "requested_unit")
    private String requestedUnit;

    @Column(name = "timeframe")
    private String timeframe;

    @Column(name = "urgency_level")
    private String urgencyLevel;

    @Column(name = "sentiment")
    private String sentiment;

    @Column(name = "structured_payload", columnDefinition = "jsonb")
    private String structuredPayload;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;
}
