package com.multimodel.safetyrisk.gateway.filter;

import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

@Component
public class RequestIdGatewayFilter implements GlobalFilter, Ordered {

    private static final Logger log = LoggerFactory.getLogger(RequestIdGatewayFilter.class);
    // 业务侧统一透传的请求标识，主要用于人工排障与跨服务日志关联；它独立于 Zipkin 的 traceId/spanId。
    private static final String REQUEST_ID_HEADER = "X-Request-Id";

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        ServerHttpRequest request = exchange.getRequest();
        String requestId = request.getHeaders().getFirst(REQUEST_ID_HEADER);
        long startNanos = System.nanoTime();

        // 仅在上游没有携带 requestId 时补齐，避免覆盖调用方已存在的链路标识。
        if (requestId == null || requestId.isBlank()) {
            requestId = UUID.randomUUID().toString();
        }
        final String finalRequestId = requestId;

        // WebFlux 请求对象是不可变的，这里通过 mutate() 把 requestId 写回请求头，确保下游服务也能直接透传使用。
        ServerHttpRequest mutatedRequest = request.mutate()
                .header(REQUEST_ID_HEADER, finalRequestId)
                .build();

        ServerWebExchange mutatedExchange = exchange.mutate().request(mutatedRequest).build();
        String method = mutatedRequest.getMethod() == null ? "UNKNOWN" : mutatedRequest.getMethod().name();
        String path = mutatedRequest.getURI().getPath();

        log.info("Gateway request start requestId={} method={} path={}", finalRequestId, method, path);

        return chain.filter(mutatedExchange)
                .doOnSuccess(ignored -> {
                    int status = mutatedExchange.getResponse().getStatusCode() == null
                            ? 0
                            : mutatedExchange.getResponse().getStatusCode().value();
                    long elapsedMs = (System.nanoTime() - startNanos) / 1_000_000;
                    log.info(
                            "Gateway request end requestId={} method={} path={} status={} elapsedMs={}",
                            finalRequestId,
                            method,
                            path,
                            status,
                            elapsedMs);
                })
                .doOnError(ex -> {
                    long elapsedMs = (System.nanoTime() - startNanos) / 1_000_000;
                    log.error(
                            "Gateway request error requestId={} method={} path={} elapsedMs={}",
                            finalRequestId,
                            method,
                            path,
                            elapsedMs,
                            ex);
                });
    }

    @Override
    public int getOrder() {
        // 尽量靠前执行，让后续过滤器、日志以及下游服务都能复用同一个 requestId。
        return -100;
    }
}
