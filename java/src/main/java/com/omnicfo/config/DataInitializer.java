package com.omnicfo.config;

import com.omnicfo.model.entity.Organization;
import com.omnicfo.repository.OrganizationRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.util.UUID;

/**
 * Seeds initial demo tenant organizations on application startup for immediate testing with Postman.
 */
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
            Organization org1 = Organization.builder()
                .id(DEMO_TENANT_1)
                .businessName("Acme Retail Enterprises")
                .build();

            Organization org2 = Organization.builder()
                .id(DEMO_TENANT_2)
                .businessName("Nova Logistics & Transport")
                .build();

            organizationRepository.save(org1);
            organizationRepository.save(org2);

            log.info("================================================================================");
            log.info("🚀 DEMO TENANTS INITIALIZED FOR POSTMAN TESTING:");
            log.info("   Tenant 1: 'Acme Retail Enterprises'     | X-Tenant-ID: {}", DEMO_TENANT_1);
            log.info("   Tenant 2: 'Nova Logistics & Transport'  | X-Tenant-ID: {}", DEMO_TENANT_2);
            log.info("================================================================================");
        }
    }
}
