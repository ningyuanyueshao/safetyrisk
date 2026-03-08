package com.multimodel.safetyrisk.moderation.controller;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.common.api.ModerationResponse;
import com.multimodel.safetyrisk.moderation.cache.CachedModerationDecision;
import com.multimodel.safetyrisk.moderation.cache.ModerationCacheKeyBuilder;
import com.multimodel.safetyrisk.moderation.cache.ModerationDecisionCache;
import com.multimodel.safetyrisk.moderation.l1.L1FilterResult;
import com.multimodel.safetyrisk.moderation.l1.L1RegexFilterService;
import jakarta.validation.Valid;
import java.util.StringJoiner;
import java.util.UUID;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

@RestController
@RequestMapping("/api/v1/moderation")
public class ModerationController {

    private final L1RegexFilterService l1RegexFilterService;
    private final ModerationDecisionCache moderationDecisionCache;

    public ModerationController(
            L1RegexFilterService l1RegexFilterService,
            ModerationDecisionCache moderationDecisionCache) {
        this.l1RegexFilterService = l1RegexFilterService;
        this.moderationDecisionCache = moderationDecisionCache;
    }

    @PostMapping(value = "/check", consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<ModerationResponse> check(
            @Valid @RequestBody ModerationRequest request,
            @RequestHeader(value = "X-Request-Id", required = false) String requestId) {

        // Keep request tracing consistent even when caller does not pass X-Request-Id.
        String finalRequestId = requestId == null || requestId.isBlank() ? UUID.randomUUID().toString() : requestId;
        // Cache key is based on stable business fields, not random request id.
        String cacheKey = ModerationCacheKeyBuilder.build(request);

        return moderationDecisionCache.get(cacheKey)
                // Hit cache first to avoid recomputing the same moderation result.
                .map(cached -> toResponse(finalRequestId, cached, true))
                .switchIfEmpty(Mono.defer(() -> {
                    // L1 is a fast local filter layer; L2/L3 happens in later stages.
                    CachedModerationDecision decision = evaluateByL1(request);
                    return moderationDecisionCache.put(cacheKey, decision)
                            .thenReturn(toResponse(finalRequestId, decision, false));
                }));
    }

    private CachedModerationDecision evaluateByL1(ModerationRequest request) {
        L1FilterResult l1Result = l1RegexFilterService.filter(request);

        CachedModerationDecision decision = new CachedModerationDecision();
        if (l1Result.isRejected()) {
            decision.setViolation(true);
            decision.setDecision("REJECT");
            // High confidence because rejection comes from deterministic rules.
            decision.setConfidence(0.99);
            decision.setReason(joinReason(l1Result));
            return decision;
        }

        decision.setViolation(false);
        decision.setDecision("PASS_TO_L2");
        // Non-violation here means "not blocked by L1", not final model judgment.
        decision.setConfidence(0.85);
        decision.setReason("L1 passed, route to L2/L3 model pipeline next.");
        return decision;
    }

    private ModerationResponse toResponse(String requestId, CachedModerationDecision decision, boolean cacheHit) {
        ModerationResponse response = new ModerationResponse();
        response.setRequestId(requestId);
        response.setViolation(decision.isViolation());
        response.setDecision(decision.getDecision());
        response.setConfidence(decision.getConfidence());
        response.setReason(cacheHit ? decision.getReason() + " [CACHE_HIT]" : decision.getReason());
        return response;
    }

    private String joinReason(L1FilterResult result) {
        StringJoiner joiner = new StringJoiner(",");
        for (String match : result.getMatches()) {
            joiner.add(match);
        }
        return result.getReason() + ":" + joiner;
    }
}
