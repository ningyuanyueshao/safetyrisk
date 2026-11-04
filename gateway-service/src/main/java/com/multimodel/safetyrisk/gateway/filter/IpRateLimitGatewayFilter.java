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
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

@Component
public class IpRateLimitGatewayFilter implements GlobalFilter, Ordered {

    private final int maxPerSecond;
    private final int cleanupTtlSeconds;
    private final ConcurrentHashMap<String, WindowCounter> counters = new ConcurrentHashMap<>();

    public IpRateLimitGatewayFilter(
            @Value("${gateway.rate-limit.per-ip-per-second:50}") int maxPerSecond,
            @Value("${gateway.rate-limit.counter-cleanup-ttl-seconds:10}") int cleanupTtlSeconds) {
        this.maxPerSecond = maxPerSecond;
        this.cleanupTtlSeconds = cleanupTtlSeconds;
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

    /**
     * 显式淘汰长时间无请求的 IP 计数条目，避免 counters 无限增长。
     *
     * <p>活跃计数器总是在当前秒内被写入（epochSecond == 当前秒），
     * 因此 epochSecond 同时等价于"最后访问秒"，可直接作为淘汰依据：
     * 超过 cleanupTtlSeconds 没有收到任何请求的 IP，其条目对限流已无意义，
     * 下一次请求到来时 compute 会重建新窗口。</p>
     */
    @Scheduled(fixedRateString = "${gateway.rate-limit.counter-cleanup-interval-ms:5000}")
    public void evictStaleCounters() {
        long cutoff = Instant.now().getEpochSecond() - cleanupTtlSeconds;
        counters.entrySet().removeIf(entry -> entry.getValue().epochSecond < cutoff);
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
