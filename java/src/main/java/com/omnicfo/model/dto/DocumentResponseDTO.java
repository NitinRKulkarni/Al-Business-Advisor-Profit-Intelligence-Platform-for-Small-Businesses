package com.omnicfo.model.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;
import java.util.UUID;

/**
 * Response DTO representing an uploaded document and its processing status.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class DocumentResponseDTO {

    private UUID documentId;
    private String fileName;
    private String fileType;
    private String processedStatus;
    private Instant uploadDate;
}
