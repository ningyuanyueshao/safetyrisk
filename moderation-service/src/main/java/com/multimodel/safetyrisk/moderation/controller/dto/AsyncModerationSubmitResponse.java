package com.multimodel.safetyrisk.moderation.controller.dto;

import java.time.LocalDateTime;

public class AsyncModerationSubmitResponse {

    private String requestId;
    private String taskId;
    private String status;
    private String message;
    // 以下字段仅“命中已完成任务直接复用历史结果”时返回；其余场景为 null，保持对旧客户端的兼容。
    private String decision;
    private Boolean violation;
    private Double confidence;
    private String reason;
    private LocalDateTime completedAt;

    public String getRequestId() {
        return requestId;
    }

    public void setRequestId(String requestId) {
        this.requestId = requestId;
    }

    public String getTaskId() {
        return taskId;
    }

    public void setTaskId(String taskId) {
        this.taskId = taskId;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }

    public String getDecision() {
        return decision;
    }

    public void setDecision(String decision) {
        this.decision = decision;
    }

    public Boolean getViolation() {
        return violation;
    }

    public void setViolation(Boolean violation) {
        this.violation = violation;
    }

    public Double getConfidence() {
        return confidence;
    }

    public void setConfidence(Double confidence) {
        this.confidence = confidence;
    }

    public String getReason() {
        return reason;
    }

    public void setReason(String reason) {
        this.reason = reason;
    }

    public LocalDateTime getCompletedAt() {
        return completedAt;
    }

    public void setCompletedAt(LocalDateTime completedAt) {
        this.completedAt = completedAt;
    }
}
