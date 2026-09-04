package com.omnicfo.controller;

import com.omnicfo.model.dto.LoginRequestDTO;
import com.omnicfo.model.dto.LoginResponseDTO;
import com.omnicfo.service.AuthService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.Instant;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/api/v1/auth")
@RequiredArgsConstructor
@CrossOrigin(origins = {"http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"})
public class AuthController {

    private final AuthService authService;

    @PostMapping("/login")
    public ResponseEntity<LoginResponseDTO> login(@RequestBody LoginRequestDTO request) {
        log.info("Received login request for user: {}", request != null ? request.getUsername() : "null");
        LoginResponseDTO response = authService.authenticate(request);
        if (response.isAuthenticated()) {
            return ResponseEntity.ok(response);
        }
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(response);
    }

    @GetMapping("/verify")
    public ResponseEntity<?> verifySession(@RequestHeader(value = "Authorization", required = false) String authHeader) {
        if (authHeader == null || !authHeader.startsWith("Bearer ")) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(Map.of("authenticated", false, "message", "Missing or invalid Authorization header", "timestamp", Instant.now()));
        }
        String token = authHeader.substring(7).trim();
        boolean valid = authService.verifyToken(token);
        if (valid) {
            return ResponseEntity.ok(Map.of("authenticated", true, "brandName", "Team Sanskriti", "timestamp", Instant.now()));
        }
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
            .body(Map.of("authenticated", false, "message", "Session expired or invalid", "timestamp", Instant.now()));
    }
}
