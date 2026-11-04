package com.multimodel.safetyrisk.model.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.multimodel.safetyrisk.model.l3.BailianL3MultimodalService;
import com.multimodel.safetyrisk.model.l3.FailoverL3MultimodalService;
import com.multimodel.safetyrisk.model.l3.L3MultimodalService;
import com.multimodel.safetyrisk.model.l3.MockL3MultimodalService;
import com.multimodel.safetyrisk.model.l3.VllmL3MultimodalService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties({L3BailianProperties.class, L3VllmProperties.class})
public class L3ServiceConfig {

    private static final Logger log = LoggerFactory.getLogger(L3ServiceConfig.class);

    @Bean
    @ConditionalOnProperty(name = "model.l3.provider", havingValue = "bailian")
    public L3MultimodalService bailianL3MultimodalService(
            L3BailianProperties properties,
            ModelProtectionProperties protectionProperties,
            ObjectMapper objectMapper) {
        log.info("Initializing Bailian L3 service with base URL: {}", properties.getBaseUrl());
        return new BailianL3MultimodalService(properties, protectionProperties, objectMapper);
    }

    @Bean
    @ConditionalOnProperty(name = "model.l3.provider", havingValue = "failover", matchIfMissing = true)
    public L3MultimodalService failoverL3MultimodalService(
            L3BailianProperties bailianProperties,
            L3VllmProperties vllmProperties,
            ModelProtectionProperties protectionProperties,
            ObjectMapper objectMapper) {
        log.info("Initializing L3 failover service. primary=bailian, fallback=openai-compatible-local");
        L3MultimodalService primary = new BailianL3MultimodalService(
                bailianProperties, protectionProperties, objectMapper);
        L3MultimodalService fallback = new VllmL3MultimodalService(
                vllmProperties, protectionProperties, objectMapper);
        return new FailoverL3MultimodalService(primary, fallback);
    }

    @Bean
    @ConditionalOnProperty(name = "model.l3.provider", havingValue = "vllm")
    public L3MultimodalService vllmL3MultimodalService(
            L3VllmProperties properties,
            ModelProtectionProperties protectionProperties,
            ObjectMapper objectMapper) {
        log.info("Initializing OpenAI-compatible local L3 service with base URL: {}, model: {}",
                properties.getBaseUrl(), properties.getModel());
        return new VllmL3MultimodalService(properties, protectionProperties, objectMapper);
    }

    @Bean
    @ConditionalOnProperty(name = "model.l3.provider", havingValue = "mock")
    public L3MultimodalService mockL3MultimodalService() {
        log.info("Initializing Mock L3 service");
        return new MockL3MultimodalService();
    }
}
