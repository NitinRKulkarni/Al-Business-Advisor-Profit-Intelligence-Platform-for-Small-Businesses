package com.omnicfo.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * Root endpoint controller to provide helpful API information when accessed in browser.
 */
@RestController
@RequestMapping("/")
public class RootController {

    @GetMapping
    public Map<String, Object> getRootInfo() {
        return Map.of(
            "service", "Omni-CFO Multi-Tenant Cloud Platform API",
            "status", "UP",
            "frontendUrl", "http://localhost:5173",
            "endpoints", Map.of(
                "organizations", "/api/v1/organizations",
                "documents", "/api/v1/files",
                "h2Console", "/h2-console"
            )
        );
    }
}
