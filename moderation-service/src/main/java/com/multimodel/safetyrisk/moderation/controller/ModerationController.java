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

        // 即使调用方未传 X-Request-Id，也生成请求标识，保证链路可追踪。
        String finalRequestId = requestId == null || requestId.isBlank() ? UUID.randomUUID().toString() : requestId;
        // 缓存键基于稳定业务字段，不包含随机请求 ID，便于命中相同请求。
        String cacheKey = ModerationCacheKeyBuilder.build(request);

        return moderationDecisionCache.get(cacheKey)
                // 先查缓存，避免重复计算同一审核结果。
                .map(cached -> toResponse(finalRequestId, cached, true))
                .switchIfEmpty(Mono.defer(() -> {
                    // L1 为本地快速规则层；L2/L3 模型审核在后续阶段处理。
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
            // 拒绝来自确定性规则，置信度可设为较高值。
            decision.setConfidence(0.99);
            decision.setReason(joinReason(l1Result));
            return decision;
        }

        decision.setViolation(false);
        decision.setDecision("PASS_TO_L2");
        // 此处“非违规”仅表示未被 L1 拦截，不代表最终模型结论。
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
