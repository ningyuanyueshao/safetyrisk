package com.multimodel.safetyrisk.moderation.model;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.common.api.model.ModelDecisionResponse;
import com.multimodel.safetyrisk.moderation.config.ModelServiceProperties;
import java.time.Duration;
import java.util.concurrent.TimeoutException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.Exceptions;
import reactor.core.publisher.Mono;

@Component
public class ModelServiceClient {

    private static final Logger log = LoggerFactory.getLogger(ModelServiceClient.class);

    private final WebClient webClient;

    public ModelServiceClient(WebClient.Builder webClientBuilder, ModelServiceProperties properties) {
        this.webClient = webClientBuilder.baseUrl(properties.getBaseUrl()).build();
    }

    /**
     * 按调用方给出的预算发起推理。同步/异步保留独立配置，便于未来按 SLA 调整；
     * 当前严格一致性模式下两者默认均为 30s，都能容纳完整 provider/failover 链。
     */
    public Mono<ModelDecisionResponse> infer(ModerationRequest request, int timeoutMs) {
        // 这里是 moderation-service 调 model-service 的关键 HTTP 出口。
        // 复用 Spring 注入的 WebClient.Builder，才能带上 tracing filter，让客户端 span 正确串进 Zipkin 链路。
        return webClient.post()
                .uri("/api/v1/model/classify")
                .bodyValue(request)
                .retrieve()
                .bodyToMono(ModelDecisionResponse.class)
                .timeout(Duration.ofMillis(timeoutMs))
                .onErrorResume(ex -> {
                    // 模型服务异常时保守降级到 REVIEW，避免因下游不可用而把高风险内容直接放行。
                    // 区分"超时"和"不可用"：前者是我们这条预算掐断的，后者是下游真的挂了。
                    // 预算仍由同步/异步入口分别传入，所以 reason 里带上具体毫秒数，排障时能直接看出是哪一层先到点。
                    boolean timedOut = Exceptions.unwrap(ex) instanceof TimeoutException;
                    String reason = timedOut
                            ? "Model-service call timed out after " + timeoutMs + "ms, fallback to REVIEW."
                            : "Model-service unavailable, fallback to REVIEW.";
                    log.warn("Model-service call failed, fallback to REVIEW. timeoutMs={} timedOut={} cause={}",
                            timeoutMs, timedOut, ex.getMessage());
                    ModelDecisionResponse fallback = new ModelDecisionResponse();
                    fallback.setDecision("REVIEW");
                    fallback.setViolation(true);
                    fallback.setConfidence(0.65);
                    fallback.setReason(reason);
                    fallback.setDecisionLayer("FALLBACK");
                    return Mono.just(fallback);
                });
    }
}
