package com.multimodel.safetyrisk.mockbailian.service;

import com.multimodel.safetyrisk.mockbailian.config.MockScenarioProperties;

public enum MockScenario {
    NORMAL,
    EXTREME_LATENCY,
    HTTP_429,
    HTTP_500,
    HTTP_503,
    TIMEOUT;

    public long delayMs(MockScenarioProperties properties) {
        return switch (this) {
            case NORMAL, HTTP_429, HTTP_500, HTTP_503 -> properties.getNormalLatencyMs();
            case EXTREME_LATENCY -> properties.getExtremeLatencyMs();
            case TIMEOUT -> properties.getTimeoutLatencyMs();
        };
    }

    static MockScenario fromPayload(String payload) {
        if (payload == null) {
            return NORMAL;
        }
        if (payload.contains("__MOCK_SCENARIO_TIMEOUT__")) {
            return TIMEOUT;
        }
        if (payload.contains("__MOCK_SCENARIO_503__")) {
            return HTTP_503;
        }
        if (payload.contains("__MOCK_SCENARIO_500__")) {
            return HTTP_500;
        }
        if (payload.contains("__MOCK_SCENARIO_429__")) {
            return HTTP_429;
        }
        if (payload.contains("__MOCK_SCENARIO_EXTREME_LATENCY__")) {
            return EXTREME_LATENCY;
        }
        return NORMAL;
    }
}
