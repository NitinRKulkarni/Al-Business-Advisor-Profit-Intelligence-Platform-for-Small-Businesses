package com.omnicfo.dto;

import jakarta.validation.constraints.NotBlank;

import java.time.Instant;
import java.util.UUID;

public class OrganizationDTO {

    public record CreateRequest(@NotBlank String businessName) {
    }

    public record Response(UUID id, String businessName, Instant createdAt) {
    }
}
