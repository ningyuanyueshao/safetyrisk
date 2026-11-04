package com.multimodel.safetyrisk.moderation.service;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.common.api.model.ModelDecisionResponse;
import com.multimodel.safetyrisk.moderation.cache.CachedModerationDecision;
import com.multimodel.safetyrisk.moderation.cache.ModerationCacheKeyBuilder;
import com.multimodel.safetyrisk.moderation.cache.ModerationDecisionCache;
import com.multimodel.safetyrisk.moderation.config.ModelServiceProperties;
import com.multimodel.safetyrisk.moderation.l1.L1FilterResult;
import com.multimodel.safetyrisk.moderation.l1.L1RegexFilterService;
import com.multimodel.safetyrisk.moderation.model.ModelServiceClient;
import java.util.StringJoiner;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

@Service
public class ModerationPipelineService {

    private static final Logger log = LoggerFactory.getLogger(ModerationPipelineService.class);

    private final L1RegexFilterService l1RegexFilterService;
    private final ModelServiceClient modelServiceClient;
    private final ModerationDecisionCache moderationDecisionCache;
    private final ModelServiceProperties modelServiceProperties;

    public ModerationPipelineService(
            L1RegexFilterService l1RegexFilterService,
            ModelServiceClient modelServiceClient,
            ModerationDecisionCache moderationDecisionCache,
            ModelServiceProperties modelServiceProperties) {
        this.l1RegexFilterService = l1RegexFilterService;
        this.modelServiceClient = modelServiceClient;
        this.moderationDecisionCache = moderationDecisionCache;
        this.modelServiceProperties = modelServiceProperties;
    }

    /**
     * 同步链路：当前默认 30s 调用预算，能容纳 model-service 的完整 provider/failover 链。
     */
    public Mono<ModerationPipelineResult> evaluate(ModerationRequest request, String requestId) {
        return evaluate(request, requestId, modelServiceProperties.getTimeoutMs());
    }

    /**
     * 异步链路：当前同样默认 30s，用与同步链路相同的预算比较终态一致性；配置仍独立保留。
     */
    public Mono<ModerationPipelineResult> evaluateAsync(ModerationRequest request, String requestId) {
        return evaluate(request, requestId, modelServiceProperties.getAsyncTimeoutMs());
    }

    private Mono<ModerationPipelineResult> evaluate(
            ModerationRequest request, String requestId, int modelServiceTimeoutMs) {
        // 审核请求先归一化成稳定键；同一语义请求可复用历史决策结果。
        String cacheKey = ModerationCacheKeyBuilder.build(request);
        return moderationDecisionCache.get(cacheKey)
                // 命中缓存：跳过 L1 正则与模型推理，直接返回。
                .map(cached -> new ModerationPipelineResult(cached, true))
                // 未命中缓存：走完整审核流程，并将决策写回缓存（L1 + Redis）。
                // 这里必须用 Mono.defer，避免在缓存命中时也提前执行下游审核逻辑。
                .switchIfEmpty(Mono.defer(() -> evaluateWithoutCache(request, requestId, modelServiceTimeoutMs)
                        .flatMap(decision -> moderationDecisionCache.put(cacheKey, decision)
                                .thenReturn(new ModerationPipelineResult(decision, false)))));
    }

    private Mono<CachedModerationDecision> evaluateWithoutCache(
            ModerationRequest request, String requestId, int modelServiceTimeoutMs) {
        log.info("L1 start requestId={}", requestId);
        L1FilterResult l1Result = l1RegexFilterService.filter(request);
        log.info("L1 end requestId={} rejected={} reason={}",
                requestId,
                l1Result.isRejected(),
                l1Result.getReason());

        // L1 已明确命中违规时直接拒绝，不再继续调用模型服务。
        if (l1Result.isRejected()) {
            return Mono.just(rejectFromL1(l1Result));
        }

        log.info("Model-service start requestId={} timeoutMs={}", requestId, modelServiceTimeoutMs);
        return modelServiceClient.infer(request, modelServiceTimeoutMs)
                .doOnNext(modelDecision -> log.info("Model-service end requestId={} decision={} confidence={} reason={}",
                        requestId,
                        modelDecision.getDecision(),
                        modelDecision.getConfidence(),
                        modelDecision.getReason()))
                .map(this::toCachedDecision);
    }

    private CachedModerationDecision rejectFromL1(L1FilterResult l1Result) {
        CachedModerationDecision decision = new CachedModerationDecision();
        decision.setViolation(true);
        decision.setDecision("REJECT");
        decision.setConfidence(0.99);
        decision.setReason(joinReason(l1Result));
        return decision;
    }

    private CachedModerationDecision toCachedDecision(ModelDecisionResponse modelDecision) {
        CachedModerationDecision decision = new CachedModerationDecision();
        decision.setViolation(modelDecision.isViolation());
        decision.setDecision(modelDecision.getDecision());
        decision.setConfidence(modelDecision.getConfidence());
        decision.setReason(modelDecision.getReason());
        return decision;
    }

    private String joinReason(L1FilterResult result) {
        StringJoiner joiner = new StringJoiner(",");
        for (String match : result.getMatches()) {
            joiner.add(match);
        }
        return result.getReason() + ":" + joiner;
    }
}
