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

        // 网关收到的审核请求会先命中这条路由，再转发到 moderation-service；
        // 对 Zipkin 来说，这也是外部请求进入审核链路后的第一跳 HTTP 转发。
        return builder.routes()
                .route("moderation-service-route", r -> r
                        .path("/api/v1/moderation/**")
                        .uri(moderationUrl))
                .build();
    }
}
