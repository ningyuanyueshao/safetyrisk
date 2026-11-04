package com.multimodel.safetyrisk.moderation.async;

import com.multimodel.safetyrisk.common.api.ModerationRequest;

public class ModerationTaskMessage {

    private String taskId;
    private String requestId;
    private ModerationRequest request;

    public String getTaskId() {
        return taskId;
    }

    public void setTaskId(String taskId) {
        this.taskId = taskId;
    }

    public String getRequestId() {
        return requestId;
    }

    public void setRequestId(String requestId) {
        this.requestId = requestId;
    }

    public ModerationRequest getRequest() {
        return request;
    }

    public void setRequest(ModerationRequest request) {
        this.request = request;
    }
}
