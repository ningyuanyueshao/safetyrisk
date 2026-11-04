package com.multimodel.safetyrisk.model.l3;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.model.config.L3BailianProperties;
import com.multimodel.safetyrisk.model.config.L3VllmProperties;
import com.multimodel.safetyrisk.model.config.ModelProtectionProperties;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class L3ProviderContractTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final AtomicInteger hits = new AtomicInteger();
    private final AtomicReference<String> requestBody = new AtomicReference<>();
    private final AtomicReference<String> authorization = new AtomicReference<>();
    private final AtomicInteger status = new AtomicInteger(200);
    private final AtomicReference<String> responseBody = new AtomicReference<>();
    private final AtomicInteger delayMs = new AtomicInteger();
    private HttpServer server;
    private ExecutorService executor;
    private String baseUrl;

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0);
        executor = Executors.newCachedThreadPool();
        server.setExecutor(executor);
        server.createContext("/chat/completions", this::handle);
        server.start();
        baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
        responseBody.set(completion("{\"decision\":\"PASS\",\"violation\":false,\"confidence\":0.91,\"reason\":\"safe\"}"));
    }

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.stop(0);
        }
        if (executor != null) {
            executor.shutdownNow();
        }
    }

    @Test
    void bailianParsesStructuredOutputAndSendsBase64Image() {
        BailianL3MultimodalService service = new BailianL3MultimodalService(
                bailianProperties(1_000), protection(5), objectMapper);

        L3Decision result = service.classify(imageRequest()).block(Duration.ofSeconds(2));

        assertThat(result.getDecision()).isEqualTo("PASS");
        assertThat(result.isViolation()).isFalse();
        assertThat(result.getConfidence()).isEqualTo(0.91);
        assertThat(authorization.get()).isEqualTo("Bearer test-key");
        assertThat(requestBody.get()).contains("data:image/jpeg;base64,AQID", "qwen3.8-flash");
    }

    @Test
    void vllmParsesArrayMessageContent() throws Exception {
        String modelJson = "{\"decision\":\"REJECT\",\"violation\":true,\"confidence\":1.4,\"reason\":\"risk\"}";
        responseBody.set(objectMapper.writeValueAsString(Map.of(
                "choices", List.of(Map.of("message", Map.of(
                        "content", List.of(Map.of("type", "text", "text", modelJson))))))));
        L3VllmProperties properties = new L3VllmProperties();
        properties.setBaseUrl(baseUrl);
        properties.setModel("local-test-model");
        properties.setTimeoutMs(1_000);
        VllmL3MultimodalService service = new VllmL3MultimodalService(
                properties, protection(5), objectMapper);

        L3Decision result = service.classify(imageRequest()).block(Duration.ofSeconds(2));

        assertThat(result.getDecision()).isEqualTo("REJECT");
        assertThat(result.isViolation()).isTrue();
        assertThat(result.getConfidence()).isEqualTo(1.0);
        assertThat(requestBody.get()).contains(
                "data:image/jpeg;base64,AQID",
                "local-test-model",
                "\"reasoning_effort\":\"none\"");
    }

    @Test
    void malformedModelOutputIsReportedAsProviderUnavailable() {
        responseBody.set(completion("not-json"));
        BailianL3MultimodalService service = new BailianL3MultimodalService(
                bailianProperties(1_000), protection(5), objectMapper);

        assertThatThrownBy(() -> service.classify(textRequest()).block(Duration.ofSeconds(2)))
                .isInstanceOf(L3ModelUnavailableException.class)
                .hasMessageContaining("response parse failed");
    }

    @Test
    void timeoutIsReportedAsProviderFailure() {
        delayMs.set(300);
        BailianL3MultimodalService service = new BailianL3MultimodalService(
                bailianProperties(50), protection(5), objectMapper);

        assertThatThrownBy(() -> service.classify(textRequest()).block(Duration.ofSeconds(2)))
                .isInstanceOf(RuntimeException.class)
                .hasMessageContaining("within 50ms");
    }

    @Test
    void repeated429And5xxResponsesOpenTheCircuit() {
        ModelProtectionProperties protection = protection(2);
        BailianL3MultimodalService service = new BailianL3MultimodalService(
                bailianProperties(1_000), protection, objectMapper);

        status.set(429);
        assertThatThrownBy(() -> service.classify(textRequest()).block(Duration.ofSeconds(2)))
                .isInstanceOf(RuntimeException.class);
        status.set(503);
        assertThatThrownBy(() -> service.classify(textRequest()).block(Duration.ofSeconds(2)))
                .isInstanceOf(RuntimeException.class);
        int hitsBeforeOpenCircuitCall = hits.get();

        assertThatThrownBy(() -> service.classify(textRequest()).block(Duration.ofSeconds(2)))
                .isInstanceOf(L3ModelUnavailableException.class)
                .hasMessageContaining("circuit is open");
        assertThat(hits).hasValue(hitsBeforeOpenCircuitCall);
    }

    private L3BailianProperties bailianProperties(int timeoutMs) {
        L3BailianProperties properties = new L3BailianProperties();
        properties.setBaseUrl(baseUrl);
        properties.setApiKey("test-key");
        properties.setModel("qwen3.8-flash");
        properties.setTimeoutMs(timeoutMs);
        return properties;
    }

    private ModelProtectionProperties protection(int failureThreshold) {
        ModelProtectionProperties properties = new ModelProtectionProperties();
        properties.setL3CircuitFailureThreshold(failureThreshold);
        properties.setL3CircuitOpenMs(60_000);
        return properties;
    }

    private ModerationRequest textRequest() {
        ModerationRequest request = new ModerationRequest();
        request.setContentType(ModerationRequest.ContentType.TEXT);
        request.setContent("ordinary test text");
        return request;
    }

    private ModerationRequest imageRequest() {
        ModerationRequest request = new ModerationRequest();
        request.setContentType(ModerationRequest.ContentType.IMAGE);
        request.setImageData("AQID");
        return request;
    }

    private String completion(String modelContent) {
        try {
            return objectMapper.writeValueAsString(Map.of(
                    "choices", List.of(Map.of("message", Map.of("content", modelContent)))));
        } catch (IOException exception) {
            throw new IllegalStateException(exception);
        }
    }

    private void handle(HttpExchange exchange) throws IOException {
        hits.incrementAndGet();
        requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
        authorization.set(exchange.getRequestHeaders().getFirst("Authorization"));
        if (delayMs.get() > 0) {
            try {
                Thread.sleep(delayMs.get());
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
            }
        }
        byte[] bytes = responseBody.get().getBytes(StandardCharsets.UTF_8);
        try {
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(status.get(), bytes.length);
            exchange.getResponseBody().write(bytes);
        } finally {
            exchange.close();
        }
    }
}
