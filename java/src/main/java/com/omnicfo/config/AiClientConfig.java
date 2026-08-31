package com.omnicfo.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

/**
 * Configuration for HTTP Client communicating with the external Python AI Service.
 */
@Configuration
public class AiClientConfig {

    @Value("${ai.service.python.base-url}")
    private String baseUrl;

    @Bean
    public RestClient aiPythonRestClient() {
        return RestClient.builder()
            .baseUrl(baseUrl)
            .build();
    }
}
