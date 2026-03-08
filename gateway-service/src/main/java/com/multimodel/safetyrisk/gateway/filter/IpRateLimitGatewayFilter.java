package com.multimodel.safetyrisk.gateway.filter;

import java.net.InetSocketAddress;
import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

@Component
public class IpRateLimitGatewayFilter implements GlobalFilter, Ordered {

    private final int maxPerSecond;
    private final ConcurrentHashMap<String, WindowCounter> counters = new ConcurrentHashMap<>();

    public IpRateLimitGatewayFilter(@Value("${gateway.rate-limit.per-ip-per-second:50}") int maxPerSecond) {
        this.maxPerSecond = maxPerSecond;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String clientIp = resolveClientIp(exchange);
        long currentSecond = Instant.now().getEpochSecond();

        WindowCounter counter = counters.compute(clientIp, (ip, existing) -> {
            if (existing == null || existing.epochSecond != currentSecond) {
                return new WindowCounter(currentSecond, new AtomicInteger(1));
            }
            existing.count.incrementAndGet();
            return existing;
        });

        if (counter.count.get() > maxPerSecond) {
            exchange.getResponse().setStatusCode(HttpStatus.TOO_MANY_REQUESTS);
            return exchange.getResponse().setComplete();
        }

        return chain.filter(exchange);
    }

    @Override
    public int getOrder() {
        return -90;
    }

    private String resolveClientIp(ServerWebExchange exchange) {
        String forwardedFor = exchange.getRequest().getHeaders().getFirst("X-Forwarded-For");
        if (forwardedFor != null && !forwardedFor.isBlank()) {
            return forwardedFor.split(",")[0].trim();
        }

        InetSocketAddress remoteAddress = exchange.getRequest().getRemoteAddress();
        return remoteAddress == null ? "unknown" : remoteAddress.getAddress().getHostAddress();
    }

    private static final class WindowCounter {
        private final long epochSecond;
        private final AtomicInteger count;

        private WindowCounter(long epochSecond, AtomicInteger count) {
            this.epochSecond = epochSecond;
            this.count = count;
        }
    }
}
