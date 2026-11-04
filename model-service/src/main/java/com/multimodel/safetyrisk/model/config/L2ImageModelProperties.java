package com.multimodel.safetyrisk.model.config;

import java.util.ArrayList;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "model.l2.image")
public class L2ImageModelProperties {

    private boolean enabled = true;
    private String modelPath = "models/image-risk.onnx";
    private double rejectThreshold = 0.85;
    private double reviewThreshold = 0.60;
    private List<String> fallbackRiskKeywords = new ArrayList<>();

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getModelPath() {
        return modelPath;
    }

    public void setModelPath(String modelPath) {
        this.modelPath = modelPath;
    }

    public double getRejectThreshold() {
        return rejectThreshold;
    }

    public void setRejectThreshold(double rejectThreshold) {
        this.rejectThreshold = rejectThreshold;
    }

    public double getReviewThreshold() {
        return reviewThreshold;
    }

    public void setReviewThreshold(double reviewThreshold) {
        this.reviewThreshold = reviewThreshold;
    }

    public List<String> getFallbackRiskKeywords() {
        return fallbackRiskKeywords;
    }

    public void setFallbackRiskKeywords(List<String> fallbackRiskKeywords) {
        this.fallbackRiskKeywords = fallbackRiskKeywords;
    }
}
