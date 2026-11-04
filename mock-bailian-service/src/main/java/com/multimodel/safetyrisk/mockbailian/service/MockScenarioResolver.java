package com.multimodel.safetyrisk.mockbailian.service;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.stereotype.Component;

@Component
public class MockScenarioResolver {

    public MockScenario resolve(JsonNode payload) {
        return MockScenario.fromPayload(extractText(payload));
    }

    private String extractText(JsonNode node) {
        if (node == null || node.isNull() || node.isMissingNode()) {
            return "";
        }
        if (node.isTextual()) {
            return node.asText("");
        }
        if (node.isArray()) {
            StringBuilder builder = new StringBuilder();
            for (JsonNode child : node) {
                builder.append(extractText(child)).append('\n');
            }
            return builder.toString();
        }
        if (node.isObject()) {
            StringBuilder builder = new StringBuilder();
            node.fields().forEachRemaining(entry -> builder
                    .append(entry.getKey())
                    .append('=')
                    .append(extractText(entry.getValue()))
                    .append('\n'));
            return builder.toString();
        }
        return node.asText("");
    }
}
