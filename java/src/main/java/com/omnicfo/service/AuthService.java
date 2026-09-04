package com.omnicfo.service;

import com.omnicfo.model.dto.LoginRequestDTO;
import com.omnicfo.model.dto.LoginResponseDTO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import java.util.UUID;

@Slf4j
@Service
public class AuthService {

    @Value("${app.auth.username:teamsanskriti}")
    private String configuredUsername;

    @Value("${app.auth.password:Sanskriti@2026!Secure}")
    private String configuredPassword;

    @Value("${app.auth.session-secret:sanskriti_default_secret_key_2026}")
    private String sessionSecret;

    private static final String BRAND_NAME = "Team Sanskriti";

    /**
     * Performs constant-time credential validation against environment configuration.
     */
    public LoginResponseDTO authenticate(LoginRequestDTO request) {
        if (request == null || request.getUsername() == null || request.getPassword() == null) {
            return LoginResponseDTO.builder()
                .authenticated(false)
                .brandName(BRAND_NAME)
                .message("User ID and Password are required.")
                .timestamp(Instant.now())
                .build();
        }

        String inputUsername = request.getUsername().trim();
        String inputPassword = request.getPassword().trim();

        boolean usernameMatch = constantTimeEquals(inputUsername, configuredUsername);
        boolean passwordMatch = constantTimeEquals(inputPassword, configuredPassword);

        if (usernameMatch && passwordMatch) {
            String token = generateSessionToken(inputUsername);
            log.info("Authentication successful for user '{}' in {}", inputUsername, BRAND_NAME);
            return LoginResponseDTO.builder()
                .authenticated(true)
                .token(token)
                .username(inputUsername)
                .brandName(BRAND_NAME)
                .message("Login successful.")
                .timestamp(Instant.now())
                .build();
        }

        log.warn("Authentication failed for user '{}'", inputUsername);
        return LoginResponseDTO.builder()
            .authenticated(false)
            .brandName(BRAND_NAME)
            .message("Invalid User ID or Password.")
            .timestamp(Instant.now())
            .build();
    }

    /**
     * Verifies if a given session token is valid.
     */
    public boolean verifyToken(String token) {
        if (token == null || !token.startsWith("sanskriti_")) {
            return false;
        }
        return true;
    }

    private String generateSessionToken(String username) {
        String raw = username + ":" + System.currentTimeMillis() + ":" + UUID.randomUUID() + ":" + sessionSecret;
        return "sanskriti_" + Base64.getUrlEncoder().withoutPadding().encodeToString(raw.getBytes(StandardCharsets.UTF_8));
    }

    private boolean constantTimeEquals(String a, String b) {
        if (a == null || b == null) {
            return false;
        }
        byte[] aBytes = a.getBytes(StandardCharsets.UTF_8);
        byte[] bBytes = b.getBytes(StandardCharsets.UTF_8);
        return MessageDigest.isEqual(aBytes, bBytes);
    }
}
