package com.omnicfo.controller;

import com.omnicfo.dto.OrganizationDTO;
import com.omnicfo.model.entity.Organization;
import com.omnicfo.repository.OrganizationRepository;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/v1/organizations")
public class OrganizationController {

    private final OrganizationRepository organizationRepository;

    public OrganizationController(OrganizationRepository organizationRepository) {
        this.organizationRepository = organizationRepository;
    }

    @GetMapping
    public List<OrganizationDTO.Response> list() {
        return organizationRepository.findAll().stream()
                .map(o -> new OrganizationDTO.Response(
                        o.getId(), o.getBusinessName(), o.getCreatedAt()))
                .toList();
    }

    @PostMapping
    public ResponseEntity<OrganizationDTO.Response> create(
            @Valid @RequestBody OrganizationDTO.CreateRequest req) {
        Organization saved = organizationRepository.save(
                Organization.builder().businessName(req.businessName()).build());
        return ResponseEntity.status(HttpStatus.CREATED).body(
                new OrganizationDTO.Response(saved.getId(), saved.getBusinessName(), saved.getCreatedAt()));
    }
}
