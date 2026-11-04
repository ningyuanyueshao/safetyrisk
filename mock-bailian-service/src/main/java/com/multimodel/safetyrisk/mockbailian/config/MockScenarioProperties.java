package com.multimodel.safetyrisk.mockbailian.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "mock.bailian")
public class MockScenarioProperties {

    private int normalLatencyMs = 100;
    private int extremeLatencyMs = 3800;
    // 默认 7s 只表示慢响应。要验证当前 18s provider 超时与 failover，运行时应改为 >18s（如 19s）。
    private int timeoutLatencyMs = 7000;

    public int getNormalLatencyMs() {
        return normalLatencyMs;
    }

    public void setNormalLatencyMs(int normalLatencyMs) {
        this.normalLatencyMs = normalLatencyMs;
    }

    public int getExtremeLatencyMs() {
        return extremeLatencyMs;
    }

    public void setExtremeLatencyMs(int extremeLatencyMs) {
        this.extremeLatencyMs = extremeLatencyMs;
    }

    public int getTimeoutLatencyMs() {
        return timeoutLatencyMs;
    }

    public void setTimeoutLatencyMs(int timeoutLatencyMs) {
        this.timeoutLatencyMs = timeoutLatencyMs;
    }
}
