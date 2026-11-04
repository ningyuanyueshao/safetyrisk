package com.multimodel.safetyrisk.moderation.controller.dto;

import java.util.List;

public class AsyncModerationBatchReplayResponse {

    private String requestId;
    private int requestedLimit;
    private int replayedCount;
    private List<AsyncModerationBatchReplayItem> items;

    public String getRequestId() {
        return requestId;
    }

    public void setRequestId(String requestId) {
        this.requestId = requestId;
    }

    public int getRequestedLimit() {
        return requestedLimit;
    }

    public void setRequestedLimit(int requestedLimit) {
        this.requestedLimit = requestedLimit;
    }

    public int getReplayedCount() {
        return replayedCount;
    }

    public void setReplayedCount(int replayedCount) {
        this.replayedCount = replayedCount;
    }

    public List<AsyncModerationBatchReplayItem> getItems() {
        return items;
    }

    public void setItems(List<AsyncModerationBatchReplayItem> items) {
        this.items = items;
    }
}
