package com.omnicfo.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * Configuration for HTTP Client communicating with the external Python AI Service.
 * Uses SimpleClientHttpRequestFactory for reliable HTTP/1.1 communication with uvicorn.
 */
@Configuration
public class AiClientConfig {

    @Value("${ai.service.python.base-url}")
    private String baseUrl;

    @Bean
    public RestClient aiPythonRestClient() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(10000);
        factory.setReadTimeout(60000);

        return RestClient.builder()
            .baseUrl(baseUrl)
            .requestFactory(factory)
            .build();
    }
}
