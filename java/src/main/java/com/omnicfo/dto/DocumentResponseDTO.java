package com.omnicfo.dto;

import com.omnicfo.model.enums.FileType;
import com.omnicfo.model.enums.ProcessedStatus;

import java.time.Instant;
import java.util.UUID;

/**
 * Response shape for document upload and listing endpoints.
 */
public record DocumentResponseDTO(
        UUID documentId,
        String fileName,
        FileType fileType,
        ProcessedStatus processedStatus,
        Instant uploadDate
) {
}
