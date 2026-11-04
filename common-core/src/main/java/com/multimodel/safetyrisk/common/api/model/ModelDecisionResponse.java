package com.multimodel.safetyrisk.common.api.model;

public class ModelDecisionResponse {

    private String decision;
    private boolean violation;
    private double confidence;
    private String reason;
    private String decisionLayer;

    public String getDecision() {
        return decision;
    }

    public void setDecision(String decision) {
        this.decision = decision;
    }

    public boolean isViolation() {
        return violation;
    }

    public void setViolation(boolean violation) {
        this.violation = violation;
    }

    public double getConfidence() {
        return confidence;
    }

    public void setConfidence(double confidence) {
        this.confidence = confidence;
    }

    public String getReason() {
        return reason;
    }

    public void setReason(String reason) {
        this.reason = reason;
    }

    public String getDecisionLayer() {
        return decisionLayer;
    }

    public void setDecisionLayer(String decisionLayer) {
        this.decisionLayer = decisionLayer;
    }
}
