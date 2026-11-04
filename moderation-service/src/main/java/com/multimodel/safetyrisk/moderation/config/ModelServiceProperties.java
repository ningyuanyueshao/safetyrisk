package com.multimodel.safetyrisk.moderation.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "moderation.model-service")
public class ModelServiceProperties {

    private String baseUrl = "http://localhost:8082";
    // 严格一致性模式：同步和异步使用相同预算，均覆盖 model-service 的完整故障转移空间。
    private int timeoutMs = 30000;
    // 必须大于 model-service 的 model.protection.infer-timeout-ms，否则外层先超时，内部那一次带原因的降级 REVIEW 传不回来。
    private int asyncTimeoutMs = 30000;

    public String getBaseUrl() {
        return baseUrl;
    }

    public void setBaseUrl(String baseUrl) {
        this.baseUrl = baseUrl;
    }

    public int getTimeoutMs() {
        return timeoutMs;
    }

    public void setTimeoutMs(int timeoutMs) {
        this.timeoutMs = timeoutMs;
    }

    public int getAsyncTimeoutMs() {
        return asyncTimeoutMs;
    }

    public void setAsyncTimeoutMs(int asyncTimeoutMs) {
        this.asyncTimeoutMs = asyncTimeoutMs;
    }
}
