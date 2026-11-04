package com.multimodel.safetyrisk.moderation.async;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.multimodel.safetyrisk.moderation.config.ModerationAsyncProperties;
import java.time.Duration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;

@Component
@ConditionalOnProperty(prefix = "moderation.async", name = "enabled", havingValue = "true", matchIfMissing = true)
public class ModerationTaskProducer {

    private final KafkaTemplate<String, String> kafkaTemplate;
    private final ObjectMapper objectMapper;
    private final ModerationAsyncProperties asyncProperties;

    public ModerationTaskProducer(
            KafkaTemplate<String, String> kafkaTemplate,
            ObjectMapper objectMapper,
            ModerationAsyncProperties asyncProperties) {
        this.kafkaTemplate = kafkaTemplate;
        this.objectMapper = objectMapper;
        this.asyncProperties = asyncProperties;
    }

    public Mono<Void> send(ModerationTaskMessage message) {
        return Mono.fromCallable(() -> objectMapper.writeValueAsString(message))
                // taskId 作为 Kafka key，可让同一 task 的重试消息稳定落到同一分区，保持顺序一致性。
                // requestId 则放在消息体里继续传递，方便把 HTTP 入队与异步消费阶段的日志关联起来。
                .flatMap(payload -> Mono.fromFuture(kafkaTemplate.send(asyncProperties.getTopic(), message.getTaskId(), payload))
                        .timeout(Duration.ofMillis(asyncProperties.getEnqueueTimeoutMs()))
                        .then(Mono.<Void>empty()))
                // 将 checked/包装异常统一映射为 RuntimeException，便于上游 Reactive 链路处理。
                .onErrorMap(this::unwrap);
    }

    private RuntimeException unwrap(Throwable throwable) {
        if (throwable instanceof RuntimeException runtimeException) {
            return runtimeException;
        }
        return new RuntimeException(throwable.getMessage(), throwable);
    }
}
