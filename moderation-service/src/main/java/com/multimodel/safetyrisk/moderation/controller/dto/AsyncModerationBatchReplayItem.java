package com.multimodel.safetyrisk.moderation.controller.dto;

public class AsyncModerationBatchReplayItem {

    private String sourceTaskId;
    private String replayTaskId;
    private String message;

    public String getSourceTaskId() {
        return sourceTaskId;
    }

    public void setSourceTaskId(String sourceTaskId) {
        this.sourceTaskId = sourceTaskId;
    }

    public String getReplayTaskId() {
        return replayTaskId;
    }

    public void setReplayTaskId(String replayTaskId) {
        this.replayTaskId = replayTaskId;
    }

    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }
}
