package com.multimodel.safetyrisk.mockbailian.controller;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.multimodel.safetyrisk.mockbailian.config.MockScenarioProperties;
import com.multimodel.safetyrisk.mockbailian.service.MockScenario;
import com.multimodel.safetyrisk.mockbailian.service.MockScenarioResolver;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

@RestController
@RequestMapping("/compatible-mode/v1")
public class MockBailianController {

    private final MockScenarioProperties properties;
    private final MockScenarioResolver scenarioResolver;
    private final ObjectMapper objectMapper;

    public MockBailianController(
            MockScenarioProperties properties,
            MockScenarioResolver scenarioResolver,
            ObjectMapper objectMapper) {
        this.properties = properties;
        this.scenarioResolver = scenarioResolver;
        this.objectMapper = objectMapper;
    }

    @PostMapping(value = "/chat/completions", consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<ResponseEntity<?>> chatCompletions(@RequestBody JsonNode payload) {
        MockScenario scenario = scenarioResolver.resolve(payload);
        return Mono.delay(Duration.ofMillis(scenario.delayMs(properties)))
                .map(ignored -> responseForScenario(scenario));
    }

    private ResponseEntity<?> responseForScenario(MockScenario scenario) {
        return switch (scenario) {
            case HTTP_429 -> errorResponse(HttpStatus.TOO_MANY_REQUESTS, "mock-429", "Mock Bailian rate limit.");
            case HTTP_500 -> errorResponse(HttpStatus.INTERNAL_SERVER_ERROR, "mock-500", "Mock Bailian internal error.");
            case HTTP_503 -> errorResponse(HttpStatus.SERVICE_UNAVAILABLE, "mock-503", "Mock Bailian unavailable.");
            case EXTREME_LATENCY -> successResponse("PASS", false, 0.96, "mock-extreme-latency");
            case TIMEOUT -> successResponse("PASS", false, 0.95, "mock-timeout-late-success");
            case NORMAL -> successResponse("PASS", false, 0.99, "mock-normal");
        };
    }

    private ResponseEntity<?> successResponse(String decision, boolean violation, double confidence, String reason) {
        return ResponseEntity.ok(Map.of(
                "id", "mockcmpl-" + UUID.randomUUID(),
                "object", "chat.completion",
                "created", System.currentTimeMillis() / 1000,
                "model", "mock-bailian",
                "choices", List.of(Map.of(
                        "index", 0,
                        "message", Map.of(
                                "role", "assistant",
                                "content", toDecisionContent(decision, violation, confidence, reason))))));
    }

    private ResponseEntity<?> errorResponse(HttpStatus status, String code, String message) {
        return ResponseEntity.status(status)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "error", Map.of(
                                "code", code,
                                "message", message)));
    }

    private String toDecisionContent(String decision, boolean violation, double confidence, String reason) {
        try {
            return objectMapper.writeValueAsString(Map.of(
                    "decision", decision,
                    "violation", violation,
                    "confidence", confidence,
                    "reason", reason));
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("Failed to serialize mock L3 response.", ex);
        }
    }
}
