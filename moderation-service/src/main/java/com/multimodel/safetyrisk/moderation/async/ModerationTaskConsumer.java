package com.multimodel.safetyrisk.moderation.async;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.multimodel.safetyrisk.moderation.config.ModerationAsyncProperties;
import com.multimodel.safetyrisk.moderation.persistence.ModerationTaskService;
import com.multimodel.safetyrisk.moderation.service.ModerationPipelineResult;
import com.multimodel.safetyrisk.moderation.service.ModerationPipelineService;
import java.time.Duration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;

@Component
@ConditionalOnProperty(prefix = "moderation.async", name = "enabled", havingValue = "true", matchIfMissing = true)
public class ModerationTaskConsumer {

    private static final Logger log = LoggerFactory.getLogger(ModerationTaskConsumer.class);

    private final ObjectMapper objectMapper;
    private final ModerationPipelineService pipelineService;
    private final ModerationTaskService taskService;
    private final ModerationAsyncProperties asyncProperties;

    public ModerationTaskConsumer(
            ObjectMapper objectMapper,
            ModerationPipelineService pipelineService,
            ModerationTaskService taskService,
            ModerationAsyncProperties asyncProperties) {
        this.objectMapper = objectMapper;
        this.pipelineService = pipelineService;
        this.taskService = taskService;
        this.asyncProperties = asyncProperties;
    }

    @KafkaListener(
            topics = "${moderation.async.topic}",
            groupId = "${moderation.async.group-id}",
            containerFactory = "moderationKafkaListenerContainerFactory")
    public void consume(String payload) {
        ModerationTaskMessage message;
        try {
            message = objectMapper.readValue(payload, ModerationTaskMessage.class);
        } catch (Exception ex) {
            // 非法消息直接标记为不可重试异常，交给 ErrorHandler 走 DLQ。
            throw new IllegalArgumentException("Failed to parse moderation task payload", ex);
        }

        try {
            // CAS 抢占状态：只有 PENDING/FAILED 能被推进为 PROCESSING。
            // 已被并发消费抢占（PROCESSING）或已完成（COMPLETED）的任务返回 false，直接跳过，
            // 不再重复跑 pipeline——这就是“消费侧幂等”的落点。
            // 卡死在 PROCESSING 的孤儿任务会由仓库按 processingLease 超时回收。
            boolean claimed = taskService.markProcessing(message.getTaskId())
                    .block(Duration.ofMillis(asyncProperties.getProcessTimeoutMs()));
            if (!claimed) {
                log.info("Skip duplicated moderation task taskId={} requestId={}",
                        message.getTaskId(),
                        message.getRequestId());
                return;
            }

            // listener 线程中阻塞等待本次任务完成，确保“处理成功后再提交 offset”。
            // 这样 Kafka 重试 / DLQ 的边界与数据库任务状态更新保持一致。
            // 消费侧走 evaluateAsync：用较长的调用预算，让 model-service 的故障转移能完整跑完。
            // 这里必须留出比 async-timeout-ms 更长的 block 预算，否则 block 先超时会把
            // 本该“降级 REVIEW 完成”的任务误判为 FAILED，白白触发重试和 DLQ。
            ModerationPipelineResult result = pipelineService.evaluateAsync(message.getRequest(), message.getRequestId())
                    .block(Duration.ofMillis(asyncProperties.getProcessTimeoutMs()));
            taskService.markCompleted(message.getTaskId(), result.getDecision())
                    .block(Duration.ofMillis(asyncProperties.getProcessTimeoutMs()));
        } catch (Exception ex) {
            log.error("Async moderation task failed taskId={} requestId={}",
                    message.getTaskId(),
                    message.getRequestId(),
                    ex);
            taskService.markFailed(message.getTaskId(), ex.getMessage())
                    .onErrorResume(ignored -> Mono.empty())
                    .block();
            // 继续抛异常，让 Kafka ErrorHandler 接管“重试 -> DLQ”。
            throw new RuntimeException("Async moderation task failed", ex);
        }
    }
}
