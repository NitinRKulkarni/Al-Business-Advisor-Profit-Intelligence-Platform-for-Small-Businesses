package com.omnicfo.model.enums;

/**
 * Processing lifecycle states for ingested documents.
 */
public enum ProcessedStatus {
    PENDING,
    PROCESSING,
    COMPLETED,
    FAILED,
    PENDING_REVIEW
}
