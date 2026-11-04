package com.multimodel.safetyrisk.model.l3;

public class L3Decision {

    private final String decision;
    private final boolean violation;
    private final double confidence;
    private final String reason;

    public L3Decision(String decision, boolean violation, double confidence, String reason) {
        this.decision = decision;
        this.violation = violation;
        this.confidence = confidence;
        this.reason = reason;
    }

    public String getDecision() {
        return decision;
    }

    public boolean isViolation() {
        return violation;
    }

    public double getConfidence() {
        return confidence;
    }

    public String getReason() {
        return reason;
    }
}
