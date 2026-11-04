package com.multimodel.safetyrisk.moderation.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "moderation.async")
public class ModerationAsyncProperties {

    private boolean enabled = true;
    private String topic = "moderation.tasks";
    private String dlqTopic = "moderation.tasks.dlq";
    private String groupId = "moderation-async-workers";
    private int enqueueTimeoutMs = 5000;
    private int processTimeoutMs = 35000;
    private int maxRetries = 2;
    private long retryBackoffMs = 1000;
    // PROCESSING 状态的"处理租约"：消费者在崩溃后（offset 未提交）任务会卡在 PROCESSING，
    // 超过该时长后视为孤儿任务，允许被重新抢占处理。需远大于 processTimeoutMs。
    private long processingLeaseMs = 90000;
    // PENDING 孤儿任务阈值：正常 PENDING 在毫秒级内就会被消费者 claim 为 PROCESSING，
    // 超过该时长仍停留在 PENDING 的基本可断定是"落库成功但从未入队/无人认领"的孤儿，
    // 由定时清扫器兜底重新入队。需远大于入队超时与消费超时。
    private long pendingOrphanThresholdMs = 300000;
    // 兜底清扫的执行间隔。
    private long sweepIntervalMs = 60000;
    // 每轮清扫最多处理多少个 PENDING 孤儿，避免宕机后瞬时大批量重投冲击下游。
    private int pendingSweepBatchSize = 100;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getTopic() {
        return topic;
    }

    public void setTopic(String topic) {
        this.topic = topic;
    }

    public String getGroupId() {
        return groupId;
    }

    public void setGroupId(String groupId) {
        this.groupId = groupId;
    }

    public String getDlqTopic() {
        return dlqTopic;
    }

    public void setDlqTopic(String dlqTopic) {
        this.dlqTopic = dlqTopic;
    }

    public int getProcessTimeoutMs() {
        return processTimeoutMs;
    }

    public int getEnqueueTimeoutMs() {
        return enqueueTimeoutMs;
    }

    public void setEnqueueTimeoutMs(int enqueueTimeoutMs) {
        this.enqueueTimeoutMs = enqueueTimeoutMs;
    }

    public void setProcessTimeoutMs(int processTimeoutMs) {
        this.processTimeoutMs = processTimeoutMs;
    }

    public int getMaxRetries() {
        return maxRetries;
    }

    public void setMaxRetries(int maxRetries) {
        this.maxRetries = maxRetries;
    }

    public long getRetryBackoffMs() {
        return retryBackoffMs;
    }

    public void setRetryBackoffMs(long retryBackoffMs) {
        this.retryBackoffMs = retryBackoffMs;
    }

    public long getProcessingLeaseMs() {
        return processingLeaseMs;
    }

    public void setProcessingLeaseMs(long processingLeaseMs) {
        this.processingLeaseMs = processingLeaseMs;
    }

    public long getPendingOrphanThresholdMs() {
        return pendingOrphanThresholdMs;
    }

    public void setPendingOrphanThresholdMs(long pendingOrphanThresholdMs) {
        this.pendingOrphanThresholdMs = pendingOrphanThresholdMs;
    }

    public long getSweepIntervalMs() {
        return sweepIntervalMs;
    }

    public void setSweepIntervalMs(long sweepIntervalMs) {
        this.sweepIntervalMs = sweepIntervalMs;
    }

    public int getPendingSweepBatchSize() {
        return pendingSweepBatchSize;
    }

    public void setPendingSweepBatchSize(int pendingSweepBatchSize) {
        this.pendingSweepBatchSize = pendingSweepBatchSize;
    }
}
