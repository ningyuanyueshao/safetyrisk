package com.multimodel.safetyrisk.model.service;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.common.api.model.ModelDecisionResponse;
import com.multimodel.safetyrisk.model.config.ModelProtectionProperties;
import com.multimodel.safetyrisk.model.l2.L2ContentClassificationService;
import com.multimodel.safetyrisk.model.l2.L2Decision;
import com.multimodel.safetyrisk.model.l3.L3Decision;
import com.multimodel.safetyrisk.model.l3.L3MultimodalService;
import java.time.Duration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

@Service
public class ModelInferenceService {

    private static final Logger log = LoggerFactory.getLogger(ModelInferenceService.class);

    private final L2ContentClassificationService l2ContentClassificationService;
    private final L3MultimodalService l3MultimodalService;
    private final ModelProtectionProperties protectionProperties;

    public ModelInferenceService(
            L2ContentClassificationService l2ContentClassificationService,
            L3MultimodalService l3MultimodalService,
            ModelProtectionProperties protectionProperties) {
        this.l2ContentClassificationService = l2ContentClassificationService;
        this.l3MultimodalService = l3MultimodalService;
        this.protectionProperties = protectionProperties;
    }

    public Mono<ModelDecisionResponse> infer(ModerationRequest request) {
        return l2ContentClassificationService.classify(request)
                .flatMap(l2Decision -> {
                    if (!"PASS_TO_L3".equals(l2Decision.getDecision())) {
                        return Mono.just(fromL2(l2Decision));
                    }
                    return l3MultimodalService.classify(request).map(this::fromL3);
                })
                .timeout(Duration.ofMillis(protectionProperties.getInferTimeoutMs()))
                .onErrorResume(ex -> {
                    log.warn("Model inference timeout or error, fallback to REVIEW: {}", ex.getMessage());
                    return Mono.just(fallbackReview("Model inference timeout/error, fallback to REVIEW."));
                });
    }

    /** Run L2 only. PASS_TO_L3 is preserved so the evaluator can measure L2 coverage. */
    public Mono<ModelDecisionResponse> inferL2(ModerationRequest request) {
        return l2ContentClassificationService.classify(request).map(this::fromL2);
    }

    /** Run the configured L3 provider directly, bypassing L2 for layer-isolated evaluation. */
    public Mono<ModelDecisionResponse> inferL3(ModerationRequest request) {
        return l3MultimodalService.classify(request)
                .map(this::fromL3)
                .timeout(Duration.ofMillis(protectionProperties.getInferTimeoutMs()))
                .onErrorResume(ex -> {
                    log.warn("L3-only inference timeout or error, fallback to REVIEW: {}", ex.getMessage());
                    return Mono.just(fallbackReview("L3-only inference timeout/error, fallback to REVIEW."));
                });
    }

    private ModelDecisionResponse fromL2(L2Decision decision) {
        ModelDecisionResponse response = new ModelDecisionResponse();
        response.setDecision(decision.getDecision());
        response.setViolation(decision.isViolation());
        response.setConfidence(decision.getConfidence());
        response.setReason(decision.getReason());
        response.setDecisionLayer("L2");
        return response;
    }

    private ModelDecisionResponse fromL3(L3Decision decision) {
        ModelDecisionResponse response = new ModelDecisionResponse();
        response.setDecision(decision.getDecision());
        response.setViolation(decision.isViolation());
        response.setConfidence(decision.getConfidence());
        response.setReason(decision.getReason());
        response.setDecisionLayer("L3");
        return response;
    }

    private ModelDecisionResponse fallbackReview(String reason) {
        ModelDecisionResponse response = new ModelDecisionResponse();
        response.setDecision("REVIEW");
        response.setViolation(true);
        response.setConfidence(0.65);
        response.setReason(reason);
        response.setDecisionLayer("FALLBACK");
        return response;
    }
}
