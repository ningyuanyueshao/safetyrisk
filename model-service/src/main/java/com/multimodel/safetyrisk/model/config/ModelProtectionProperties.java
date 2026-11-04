package com.multimodel.safetyrisk.model.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "model.protection")
public class ModelProtectionProperties {

    private boolean rateLimitEnabled = false;
    private int perIpPerSecond = 200;
    private int inferTimeoutMs = 27000;
    private int l3CircuitFailureThreshold = 5;
    private int l3CircuitOpenMs = 15000;

    public boolean isRateLimitEnabled() {
        return rateLimitEnabled;
    }

    public void setRateLimitEnabled(boolean rateLimitEnabled) {
        this.rateLimitEnabled = rateLimitEnabled;
    }

    public int getPerIpPerSecond() {
        return perIpPerSecond;
    }

    public void setPerIpPerSecond(int perIpPerSecond) {
        this.perIpPerSecond = perIpPerSecond;
    }

    public int getInferTimeoutMs() {
        return inferTimeoutMs;
    }

    public void setInferTimeoutMs(int inferTimeoutMs) {
        this.inferTimeoutMs = inferTimeoutMs;
    }

    public int getL3CircuitFailureThreshold() {
        return l3CircuitFailureThreshold;
    }

    public void setL3CircuitFailureThreshold(int l3CircuitFailureThreshold) {
        this.l3CircuitFailureThreshold = l3CircuitFailureThreshold;
    }

    public int getL3CircuitOpenMs() {
        return l3CircuitOpenMs;
    }

    public void setL3CircuitOpenMs(int l3CircuitOpenMs) {
        this.l3CircuitOpenMs = l3CircuitOpenMs;
    }
}
