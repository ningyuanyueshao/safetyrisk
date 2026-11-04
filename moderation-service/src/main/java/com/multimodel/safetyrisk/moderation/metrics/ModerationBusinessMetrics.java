package com.multimodel.safetyrisk.moderation.metrics;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import org.springframework.stereotype.Component;

@Component
public class ModerationBusinessMetrics {

    // 业务指标聚合入口：
    // 1) 同步审核质量（decision 分布、错误数）
    // 2) 同步审核性能（latency 分位）
    // 3) 异步运维操作量（查询、单个回放、批量回放任务数）
    // 同步接口异常次数，用于计算错误率和触发稳定性告警。
    private final Counter syncErrorCounter;
    // 异步任务查询次数，反映运营/排障侧查询压力。
    private final Counter taskQueryCounter;
    // 单任务回放次数，常用于人工重试失败任务。
    private final Counter replaySingleCounter;
    // 批量回放按“任务条数”累计，反映一次批处理对系统的实际冲击量。
    private final Counter replayBatchCounter;
    // 按 decision 预注册的计数/延迟指标：decision 是低基数字段（固定几个取值），
    // 在构造器里一次性注册，请求路径只做 increment/record，从不动态建指标（避免基数爆炸）。
    private final Map<String, Counter> syncDecisionCounters;
    private final Map<String, Timer> syncLatencyTimers;

    // 系统实际会产出的 decision 取值：L1/L2/L3 可能给出 PASS/REJECT/REVIEW/PASS_TO_L3，
    // recordSyncSuccess 里空值或未知值统一落到 UNKNOWN 兜底。
    private static final List<String> KNOWN_DECISIONS = List.of("PASS", "REJECT", "REVIEW", "PASS_TO_L3", "UNKNOWN");

    public ModerationBusinessMetrics(MeterRegistry meterRegistry) {
        // 这里使用预注册 Counter，避免每次调用都做指标构建。
        this.syncErrorCounter = Counter.builder("moderation.sync.error.total")
                .description("Total number of sync moderation errors")
                .register(meterRegistry);
        this.taskQueryCounter = Counter.builder("moderation.async.task.query.total")
                .description("Total number of async task query requests")
                .register(meterRegistry);
        this.replaySingleCounter = Counter.builder("moderation.async.replay.single.total")
                .description("Total number of async single-task replay requests")
                .register(meterRegistry);
        this.replayBatchCounter = Counter.builder("moderation.async.replay.batch.total")
                .description("Total number of async batch replayed tasks")
                .register(meterRegistry);
        // 预注册同步 decision 分布计数：只按低基数字段 decision 分组，Grafana 可直接 sum by(decision)。
        this.syncDecisionCounters = KNOWN_DECISIONS.stream().collect(Collectors.toMap(
                d -> d,
                d -> Counter.builder("moderation.sync.decision.total")
                        .description("Total number of sync moderation decisions, tagged by decision")
                        .tag("decision", d)
                        .register(meterRegistry)));
        // 预注册同步延迟 Timer，并显式开启直方图发布：
        // 只有 publishPercentileHistogram() 才会让 Prometheus 注册表输出 _bucket 序列，
        // 之后 PromQL 才能用 histogram_quantile 算 P95/P99（默认 Timer 只出 _count/_sum/_max）。
        this.syncLatencyTimers = KNOWN_DECISIONS.stream().collect(Collectors.toMap(
                d -> d,
                d -> Timer.builder("moderation.sync.latency")
                        .publishPercentileHistogram()
                        .description("Sync moderation latency")
                        .tag("decision", d)
                        .register(meterRegistry)));
    }

    public void recordSyncSuccess(long elapsedMs, String decision) {
        // decision 为空或不在已知集合时统一落到 UNKNOWN，防止标签值缺失导致维度混乱。
        String safeDecision = (decision == null || decision.isBlank()) ? "UNKNOWN" : decision;
        // 全部指标都已在构造器预注册，这里只做 increment/record，不在请求路径上动态建指标。
        syncDecisionCounters.getOrDefault(safeDecision, syncDecisionCounters.get("UNKNOWN")).increment();
        // 兜底保护：负耗时按 0 处理，避免脏数据污染直方图分位统计。
        syncLatencyTimers.getOrDefault(safeDecision, syncLatencyTimers.get("UNKNOWN"))
                .record(Duration.ofMillis(Math.max(0, elapsedMs)));
    }

    public void incrementSyncError() {
        // 注意：只统计异常路径；成功路径由 recordSyncSuccess 统计。
        syncErrorCounter.increment();
    }

    public void incrementTaskQuery() {
        taskQueryCounter.increment();
    }

    public void incrementReplaySingle() {
        replaySingleCounter.increment();
    }

    public void incrementReplayBatch(int count) {
        if (count <= 0) {
            return;
        }
        // 批量回放按“任务数”增量，而不是按“请求次数”增量。
        replayBatchCounter.increment(count);
    }
}
