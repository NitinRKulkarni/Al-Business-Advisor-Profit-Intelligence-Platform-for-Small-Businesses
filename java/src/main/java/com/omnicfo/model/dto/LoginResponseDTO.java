package com.omnicfo.model.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class LoginResponseDTO {
    private boolean authenticated;
    private String token;
    private String username;
    private String brandName;
    private String message;
    private Instant timestamp;
}
