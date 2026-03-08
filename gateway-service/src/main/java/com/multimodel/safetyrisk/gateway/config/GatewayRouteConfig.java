package com.multimodel.safetyrisk.gateway.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.route.RouteLocator;
import org.springframework.cloud.gateway.route.builder.RouteLocatorBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class GatewayRouteConfig {

    @Bean
    public RouteLocator customRouteLocator(
            RouteLocatorBuilder builder,
            @Value("${gateway.backend.moderation-url}") String moderationUrl) {

        return builder.routes()
                .route("moderation-service-route", r -> r
                        .path("/api/v1/moderation/**")
                        .uri(moderationUrl))
                .build();
    }
}
