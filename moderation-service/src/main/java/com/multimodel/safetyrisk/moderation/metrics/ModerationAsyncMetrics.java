package com.multimodel.safetyrisk.moderation.metrics;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;

@Component
public class ModerationAsyncMetrics {

    // 这些 Counter 最终会在 /actuator/prometheus 暴露为
    // moderation_async_*_total，供 Prometheus 抓取与告警/看板计算速率和比例。
    private final Counter asyncEnqueueCounter;
    private final Counter asyncDedupHitCounter;
    private final Counter asyncRetryCounter;
    private final Counter asyncDlqCounter;
    private final Counter asyncSweepReenqueueCounter;
    private final Counter asyncSweepFailCounter;

    public ModerationAsyncMetrics(MeterRegistry meterRegistry) {
        this.asyncEnqueueCounter = Counter.builder("moderation.async.enqueue.total")
                .description("Total number of async moderation tasks enqueued")
                .register(meterRegistry);
        this.asyncDedupHitCounter = Counter.builder("moderation.async.dedup.hit.total")
                .description("Total number of async moderation dedup hits")
                .register(meterRegistry);
        this.asyncRetryCounter = Counter.builder("moderation.async.retry.total")
                .description("Total number of async moderation retry attempts")
                .register(meterRegistry);
        this.asyncDlqCounter = Counter.builder("moderation.async.dlq.total")
                .description("Total number of async moderation tasks sent to DLQ")
                .register(meterRegistry);
        this.asyncSweepReenqueueCounter = Counter.builder("moderation.async.sweep.reenqueue.total")
                .description("Total number of pending orphan tasks re-enqueued by the sweeper")
                .register(meterRegistry);
        this.asyncSweepFailCounter = Counter.builder("moderation.async.sweep.fail.total")
                .description("Total number of pending orphans the sweeper failed to re-enqueue")
                .register(meterRegistry);
    }

    public void incrementEnqueue() {
        // 新任务入队（非去重命中）时累加。
        asyncEnqueueCounter.increment();
    }

    public void incrementDedupHit() {
        // 命中幂等去重时累加，用于观察重复提交占比。
        asyncDedupHitCounter.increment();
    }

    public void incrementRetry() {
        // Kafka 消费失败进入重试流程时累加。
        asyncRetryCounter.increment();
    }

    public void incrementDlq() {
        // 超过最大重试后进入 DLQ 时累加。
        asyncDlqCounter.increment();
    }

    public void incrementSweepReenqueue() {
        // 清扫器成功重投 PENDING 孤儿任务时累加，用于观察兜底机制是否在工作。
        asyncSweepReenqueueCounter.increment();
    }

    public void incrementSweepFail() {
        // 清扫器重投也失败（任务转入 FAILED）时累加，偏高说明 Kafka 侧持续异常。
        asyncSweepFailCounter.increment();
    }
}
