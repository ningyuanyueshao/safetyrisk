package com.multimodel.safetyrisk.moderation.async;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.moderation.config.ModerationAsyncProperties;
import com.multimodel.safetyrisk.moderation.metrics.ModerationAsyncMetrics;
import com.multimodel.safetyrisk.moderation.persistence.ModerationTaskRecord;
import com.multimodel.safetyrisk.moderation.persistence.ModerationTaskService;
import java.time.Duration;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;

/**
 * 兜底清扫器：专门回收"落库成功但从未入队/无人认领"的 PENDING 孤儿任务。
 *
 * <p>正常 PENDING 在毫秒级内就会被消费者 claim 为 PROCESSING，因此超过
 * {@code pending-orphan-threshold-ms} 仍停留在此状态的，基本可断定是孤儿：
 * <ul>
 *   <li>落库成功后进程宕机，Kafka 消息从未发出（onErrorResume 来不及执行）；</li>
 *   <li>消息虽发出但消费者反复崩溃未能认领，最终进入 DLQ 而任务状态未流转。</li>
 * </ul>
 *
 * <p>处理方式：用原 taskId 重新投递同一消息。消费侧 CAS 抢占 + 请求去重保证幂等，
 * 重复投递不会造成重复审核。重投成功刷新 updated_at 做节流；重投也失败则仅当记录仍为
 * PENDING 时标记 FAILED，交给回放接口，避免与在途消费者竞态误杀。
 */
@Component
@ConditionalOnProperty(prefix = "moderation.async", name = "enabled", havingValue = "true", matchIfMissing = true)
public class ModerationTaskSweeper {

    private static final Logger log = LoggerFactory.getLogger(ModerationTaskSweeper.class);

    private final ModerationTaskService taskService;
    private final ModerationTaskProducer taskProducer;
    private final ModerationAsyncProperties asyncProperties;
    private final ModerationAsyncMetrics asyncMetrics;

    public ModerationTaskSweeper(
            ModerationTaskService taskService,
            ModerationTaskProducer taskProducer,
            ModerationAsyncProperties asyncProperties,
            ModerationAsyncMetrics asyncMetrics) {
        this.taskService = taskService;
        this.taskProducer = taskProducer;
        this.asyncProperties = asyncProperties;
        this.asyncMetrics = asyncMetrics;
    }

    @Scheduled(fixedDelayString = "${moderation.async.sweep-interval-ms:60000}")
    public void sweepPendingOrphans() {
        int batchSize = asyncProperties.getPendingSweepBatchSize();
        long orphanThresholdMs = asyncProperties.getPendingOrphanThresholdMs();
        List<ModerationTaskRecord> orphans = taskService.findOrphanPendingTasks(batchSize, orphanThresholdMs)
                .collectList()
                .block(Duration.ofMillis(asyncProperties.getProcessTimeoutMs()));
        if (orphans == null || orphans.isEmpty()) {
            return;
        }
        log.info("Pending orphan sweep found {} orphan task(s), older than {}ms",
                orphans.size(), orphanThresholdMs);

        for (ModerationTaskRecord record : orphans) {
            try {
                ModerationTaskMessage message = new ModerationTaskMessage();
                message.setTaskId(record.getTaskId());
                message.setRequestId(record.getRequestId());
                message.setRequest(toModerationRequest(record));
                taskProducer.send(message)
                        .block(Duration.ofMillis(asyncProperties.getEnqueueTimeoutMs()));
                // 重投成功后刷新 updated_at：避免下一轮立即重复清扫，天然形成"每 threshold 一次"的节流。
                taskService.touchPendingTask(record.getTaskId())
                        .block(Duration.ofMillis(asyncProperties.getProcessTimeoutMs()));
                asyncMetrics.incrementSweepReenqueue();
                log.info("Re-enqueued pending orphan taskId={} requestId={}",
                        record.getTaskId(), record.getRequestId());
            } catch (Exception ex) {
                // 重投也失败（如 Kafka 持续不可用）→ 标记 FAILED 纳入可回放范围，避免无限重试。
                taskService.markPendingFailed(
                                record.getTaskId(),
                                "Pending orphan re-enqueue failed: " + ex.getMessage())
                        .onErrorResume(ignored -> Mono.empty())
                        .block();
                asyncMetrics.incrementSweepFail();
                log.error("Failed to re-enqueue pending orphan taskId={} requestId={}",
                        record.getTaskId(), record.getRequestId(), ex);
            }
        }
    }

    private ModerationRequest toModerationRequest(ModerationTaskRecord record) {
        ModerationRequest request = new ModerationRequest();
        request.setContentType(ModerationRequest.ContentType.valueOf(record.getContentType()));
        request.setUserId(record.getUserId());
        request.setContent(record.getContent());
        request.setImageUrl(record.getImageUrl());
        return request;
    }
}
