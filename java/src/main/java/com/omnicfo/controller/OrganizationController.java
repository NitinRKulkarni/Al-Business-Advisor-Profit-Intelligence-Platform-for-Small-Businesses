package com.omnicfo.controller;

import com.omnicfo.model.entity.Organization;
import com.omnicfo.repository.OrganizationRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/organizations")
@RequiredArgsConstructor
public class OrganizationController {

    private final OrganizationRepository organizationRepository;

    @GetMapping
    public ResponseEntity<List<Organization>> listOrganizations() {
        return ResponseEntity.ok(organizationRepository.findAll());
    }

    @PostMapping
    public ResponseEntity<Organization> createOrganization(@RequestBody Map<String, String> payload) {
        String businessName = payload.get("businessName");
        if (businessName == null || businessName.trim().isEmpty()) {
            throw new IllegalArgumentException("Field 'businessName' is required");
        }
        Organization org = Organization.builder()
            .businessName(businessName.trim())
            .build();
        Organization saved = organizationRepository.save(org);
        return ResponseEntity.status(HttpStatus.CREATED).body(saved);
    }
}
