package com.multimodel.safetyrisk.moderation.cache;

import reactor.core.publisher.Mono;

public interface ModerationDecisionCache {

    Mono<CachedModerationDecision> get(String key);

    Mono<Void> put(String key, CachedModerationDecision decision);
}
