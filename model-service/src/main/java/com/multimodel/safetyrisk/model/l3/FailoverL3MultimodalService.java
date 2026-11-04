package com.multimodel.safetyrisk.model.l3;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import reactor.core.publisher.Mono;

/**
 * Routes L3 requests to Bailian first and falls back to a local OpenAI-compatible model
 * when the primary provider is unavailable or its circuit is open.
 */
public class FailoverL3MultimodalService implements L3MultimodalService {

    private static final Logger log = LoggerFactory.getLogger(FailoverL3MultimodalService.class);

    private final L3MultimodalService primary;
    private final L3MultimodalService fallback;

    public FailoverL3MultimodalService(
            L3MultimodalService primary,
            L3MultimodalService fallback) {
        this.primary = primary;
        this.fallback = fallback;
    }

    @Override
    public Mono<L3Decision> classify(ModerationRequest request) {
        return primary.classify(request)
                .onErrorResume(primaryError -> {
                    log.warn("Primary L3 provider unavailable, switching to local provider: {}",
                            primaryError.getMessage());
                    return fallback.classify(request)
                            .onErrorResume(fallbackError -> {
                                log.warn("Local L3 fallback unavailable, returning REVIEW: {}",
                                        fallbackError.getMessage());
                                return Mono.just(new L3Decision(
                                        "REVIEW",
                                        true,
                                        0.70,
                                        "L3 API and local vLLM failed, fallback to REVIEW."));
                            });
                });
    }
}
