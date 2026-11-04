package com.multimodel.safetyrisk.model.filter;

import com.multimodel.safetyrisk.model.config.ModelProtectionProperties;
import java.net.InetSocketAddress;
import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

@Component
public class ModelServiceRateLimitFilter implements WebFilter, Ordered {

    private final ModelProtectionProperties properties;
    private final ConcurrentHashMap<String, WindowCounter> counters = new ConcurrentHashMap<>();

    public ModelServiceRateLimitFilter(ModelProtectionProperties properties) {
        this.properties = properties;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        if (!properties.isRateLimitEnabled()) {
            return chain.filter(exchange);
        }
        if (!exchange.getRequest().getPath().value().startsWith("/api/v1/model/")) {
            return chain.filter(exchange);
        }

        String clientIp = resolveClientIp(exchange);
        long currentSecond = Instant.now().getEpochSecond();

        WindowCounter counter = counters.compute(clientIp, (ip, existing) -> {
            if (existing == null || existing.epochSecond != currentSecond) {
                return new WindowCounter(currentSecond, new AtomicInteger(1));
            }
            existing.count.incrementAndGet();
            return existing;
        });

        if (counter.count.get() > properties.getPerIpPerSecond()) {
            exchange.getResponse().setStatusCode(HttpStatus.TOO_MANY_REQUESTS);
            return exchange.getResponse().setComplete();
        }
        return chain.filter(exchange);
    }

    @Override
    public int getOrder() {
        return -120;
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
