package com.omnicfo.config;

import com.omnicfo.model.entity.Organization;
import com.omnicfo.repository.OrganizationRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.util.UUID;

@Slf4j
@Component
@RequiredArgsConstructor
public class DataInitializer implements CommandLineRunner {
    public static final UUID DEMO_TENANT_1 = UUID.fromString("a0000000-0000-0000-0000-000000000001");
    public static final UUID DEMO_TENANT_2 = UUID.fromString("b0000000-0000-0000-0000-000000000002");

    private final OrganizationRepository organizationRepository;

    @Override
    public void run(String... args) {
        if (organizationRepository.count() == 0) {
            organizationRepository.save(Organization.builder()
                .id(DEMO_TENANT_1)
                .businessName("Acme Retail Enterprises")
                .build());
            organizationRepository.save(Organization.builder()
                .id(DEMO_TENANT_2)
                .businessName("Nova Logistics & Transport")
                .build());
            log.info("Demo tenants initialized for local testing");
        }
    }
}
