package com.multimodel.safetyrisk.moderation.cache;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.multimodel.safetyrisk.moderation.config.ModerationCacheProperties;
import java.time.Duration;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

@Service
public class RedisModerationDecisionCache implements ModerationDecisionCache {

    private final ReactiveStringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final ModerationCacheProperties properties;

    public RedisModerationDecisionCache(
            ReactiveStringRedisTemplate redisTemplate,
            ObjectMapper objectMapper,
            ModerationCacheProperties properties) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.properties = properties;
    }

    @Override
    public Mono<CachedModerationDecision> get(String key) {
        if (!properties.isEnabled()) {
            return Mono.empty();
        }

        return redisTemplate.opsForValue()
                .get(fullKey(key))
                .flatMap(this::fromJson)
                .onErrorResume(ignored -> Mono.empty());
    }

    @Override
    public Mono<Void> put(String key, CachedModerationDecision decision) {
        if (!properties.isEnabled()) {
            return Mono.empty();
        }

        return toJson(decision)
                .flatMap(json -> redisTemplate.opsForValue()
                        .set(fullKey(key), json, Duration.ofSeconds(properties.getTtlSeconds())))
                .then()
                .onErrorResume(ignored -> Mono.empty());
    }

    private String fullKey(String key) {
        return properties.getKeyPrefix() + key;
    }

    private Mono<String> toJson(CachedModerationDecision value) {
        try {
            return Mono.just(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException ex) {
            return Mono.error(ex);
        }
    }

    private Mono<CachedModerationDecision> fromJson(String json) {
        try {
            return Mono.just(objectMapper.readValue(json, CachedModerationDecision.class));
        } catch (JsonProcessingException ex) {
            return Mono.error(ex);
        }
    }
}
