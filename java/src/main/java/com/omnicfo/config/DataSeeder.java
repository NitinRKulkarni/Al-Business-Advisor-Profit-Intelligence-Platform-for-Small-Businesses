package com.omnicfo.config;

import com.omnicfo.model.entity.Organization;
import com.omnicfo.repository.OrganizationRepository;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.UUID;

/**
 * Seeds the two demo tenants documented in the README so uploads work
 * immediately after a fresh start.
 */
@Configuration
public class DataSeeder {

    @Bean
    CommandLineRunner seedTenants(OrganizationRepository repo) {
        return args -> {
            seed(repo, "a0000000-0000-0000-0000-000000000001", "Acme Retail Enterprises");
            seed(repo, "b0000000-0000-0000-0000-000000000002", "Nova Logistics & Transport");
        };
    }

    private void seed(OrganizationRepository repo, String id, String name) {
        UUID uuid = UUID.fromString(id);
        if (!repo.existsById(uuid)) {
            repo.save(Organization.builder().id(uuid).businessName(name).build());
        }
    }
}
