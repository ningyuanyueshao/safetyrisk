package com.multimodel.safetyrisk.moderation.service;

import com.multimodel.safetyrisk.moderation.cache.CachedModerationDecision;

public class ModerationPipelineResult {

    private final CachedModerationDecision decision;
    private final boolean cacheHit;

    public ModerationPipelineResult(CachedModerationDecision decision, boolean cacheHit) {
        this.decision = decision;
        this.cacheHit = cacheHit;
    }

    public CachedModerationDecision getDecision() {
        return decision;
    }

    public boolean isCacheHit() {
        return cacheHit;
    }
}
