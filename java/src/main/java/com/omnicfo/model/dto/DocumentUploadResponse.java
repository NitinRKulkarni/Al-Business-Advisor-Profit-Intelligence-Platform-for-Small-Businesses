package com.omnicfo.model.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.omnicfo.model.enums.ProcessedStatus;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;
import java.util.UUID;

/**
 * Response DTO returned upon successful document upload ingestion.
 */
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class DocumentUploadResponse {

    @JsonProperty("document_id")
    private UUID documentId;

    @JsonProperty("fileName")
    private String fileName;

    @JsonProperty("fileType")
    private String fileType;

    @JsonProperty("fileHash")
    private String fileHash;

    @JsonProperty("status")
    private ProcessedStatus status;

    @JsonProperty("uploadDate")
    private Instant uploadDate;

    @JsonProperty("message")
    private String message;
}
