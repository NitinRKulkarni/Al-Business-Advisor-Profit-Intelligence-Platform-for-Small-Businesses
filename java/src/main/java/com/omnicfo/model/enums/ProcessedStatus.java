package com.omnicfo.model.enums;

/**
 * Lifecycle status of a document as it moves through the ingestion and
 * AI-extraction pipeline.
 *
 *   PENDING    -> uploaded, waiting for the poller to pick it up
 *   PROCESSING -> dispatched to the Python AI service (in flight)
 *   COMPLETED  -> extraction succeeded and results were persisted
 *   FAILED     -> extraction could not be completed
 */
public enum ProcessedStatus {
    PENDING,
    PROCESSING,
    COMPLETED,
    FAILED
}
