package com.multimodel.safetyrisk.moderation.cache;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.multimodel.safetyrisk.moderation.config.ModerationCacheProperties;
import java.util.concurrent.TimeUnit;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

@Service
@Primary
public class MultiLevelModerationDecisionCache implements ModerationDecisionCache {

    private final ModerationCacheProperties properties;
    private final RedisModerationDecisionCache redisCache;
    // F1: 进程内本地缓存（Caffeine），用于降低单实例内重复请求的 Redis 往返开销。
    private final Cache<String, CachedModerationDecision> localCache;

    public MultiLevelModerationDecisionCache(
            ModerationCacheProperties properties,
            RedisModerationDecisionCache redisCache) {
        this.properties = properties;
        this.redisCache = redisCache;
        this.localCache = Caffeine.newBuilder()
                .maximumSize(properties.getLocal().getMaxSize())
                .expireAfterWrite(properties.getLocal().getTtlSeconds(), TimeUnit.SECONDS)
                .build();
    }

    @Override
    public Mono<CachedModerationDecision> get(String key) {
        // 全局开关关闭时，直接视为缓存未命中。
        if (!properties.isEnabled()) {
            return Mono.empty();
        }

        if (properties.getLocal().isEnabled()) {
            CachedModerationDecision local = localCache.getIfPresent(key);
            if (local != null) {
                // 先查本地 F1，命中即返回，避免访问 Redis。
                return Mono.just(local);
            }
        }

        // 本地未命中后回退到 Redis（F2）；若命中则回填本地缓存，加速后续请求。
        return redisCache.get(key)
                .doOnNext(value -> {
                    if (properties.getLocal().isEnabled()) {
                        localCache.put(key, value);
                    }
                });
    }

    @Override
    public Mono<Void> put(String key, CachedModerationDecision decision) {
        // 全局开关关闭时，不写任何缓存。
        if (!properties.isEnabled()) {
            return Mono.empty();
        }

        if (properties.getLocal().isEnabled()) {
            // 先写本地缓存，保证当前实例后续读取可立即命中。
            localCache.put(key, decision);
        }

        // 再写 Redis，保证跨实例可见（Redis 层内部已做异常降级处理）。
        return redisCache.put(key, decision);
    }
}
