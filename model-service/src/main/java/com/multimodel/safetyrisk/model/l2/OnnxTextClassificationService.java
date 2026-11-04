package com.multimodel.safetyrisk.model.l2;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtException;
import ai.onnxruntime.OrtSession;
import ai.onnxruntime.OrtSession.Result;
import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.model.config.L2TextModelProperties;
import jakarta.annotation.PostConstruct;
import java.nio.FloatBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

@Service
public class OnnxTextClassificationService implements L2TextClassificationService {

    private static final Logger log = LoggerFactory.getLogger(OnnxTextClassificationService.class);
    private static final int FEATURE_SIZE = 128;

    private final L2TextModelProperties properties;
    private volatile OrtEnvironment environment;
    private volatile OrtSession session;
    private volatile String inputName;

    public OnnxTextClassificationService(L2TextModelProperties properties) {
        this.properties = properties;
    }

    @PostConstruct
    public void init() {
        if (!properties.isEnabled()) {
            log.info("Model-service L2 text disabled");
            return;
        }
        try {
            Optional<Path> resolved = OnnxModelPathResolver.resolve(properties.getModelPath());
            if (resolved.isEmpty()) {
                log.warn("L2 text model missing, fallback enabled. configuredPath={}", properties.getModelPath());
                return;
            }
            Path modelPath = resolved.get();
            environment = OrtEnvironment.getEnvironment();
            session = environment.createSession(Files.readAllBytes(modelPath), new OrtSession.SessionOptions());
            inputName = session.getInputNames().stream().findFirst().orElse("input");
            log.info("L2 text model loaded from {}", modelPath.toAbsolutePath());
        } catch (Exception ex) {
            log.error("L2 text model init failed, fallback enabled", ex);
            session = null;
            inputName = null;
        }
    }

    @Override
    public Mono<L2Decision> classify(ModerationRequest request) {
        if (request.getContentType() == ModerationRequest.ContentType.IMAGE) {
            return Mono.just(new L2Decision("PASS_TO_L3", false, 0.70, "L2 text skipped for image content."));
        }

        return Mono.fromCallable(() -> {
                    if (session != null && inputName != null) {
                        Optional<L2Decision> onnx = tryOnnxInference(request.getContent());
                        if (onnx.isPresent()) {
                            return onnx.get();
                        }
                    }
                    return fallbackDecision(request.getContent());
                })
                .subscribeOn(Schedulers.boundedElastic());
    }

    private Optional<L2Decision> tryOnnxInference(String text) {
        try {
            float[] vector = buildFeatureVector(text);
            try (OnnxTensor tensor = OnnxTensor.createTensor(environment, FloatBuffer.wrap(vector), new long[] {1, FEATURE_SIZE});
                    Result result = session.run(Map.of(inputName, tensor))) {
                return Optional.of(scoreToDecision(parseRiskScore(result), "L2 text ONNX inference"));
            }
        } catch (Exception ex) {
            log.warn("L2 text inference failed, fallback enabled: {}", ex.getMessage());
            return Optional.empty();
        }
    }

    private double parseRiskScore(Result result) throws OrtException {
        Object value = result.get(0).getValue();
        if (value instanceof float[][] matrix && matrix.length > 0 && matrix[0].length > 0) {
            return clamp(matrix[0][Math.min(1, matrix[0].length - 1)]);
        }
        if (value instanceof float[] vector && vector.length > 0) {
            return clamp(vector[Math.min(1, vector.length - 1)]);
        }
        if (value instanceof double[][] matrix && matrix.length > 0 && matrix[0].length > 0) {
            return clamp(matrix[0][Math.min(1, matrix[0].length - 1)]);
        }
        if (value instanceof double[] vector && vector.length > 0) {
            return clamp(vector[Math.min(1, vector.length - 1)]);
        }
        return 0.0;
    }

    private float[] buildFeatureVector(String text) {
        String normalized = text == null ? "" : text.toLowerCase(Locale.ROOT);
        float[] vector = new float[FEATURE_SIZE];
        int length = normalized.length();
        if (length == 0) {
            return vector;
        }

        for (int i = 0; i < length; i++) {
            int bucket = Math.abs(normalized.charAt(i)) % FEATURE_SIZE;
            vector[bucket] += 1.0f;
        }
        for (int i = 0; i < FEATURE_SIZE; i++) {
            vector[i] = vector[i] / length;
        }
        return vector;
    }

    private L2Decision fallbackDecision(String text) {
        String normalized = text == null ? "" : text.toLowerCase(Locale.ROOT);
        List<String> hits = properties.getFallbackRiskKeywords().stream()
                .filter(keyword -> !keyword.isBlank())
                .filter(keyword -> normalized.contains(keyword.toLowerCase(Locale.ROOT)))
                .collect(Collectors.toList());

        double score = Math.min(1.0, hits.size() * 0.25 + (normalized.length() > 300 ? 0.1 : 0.0));
        if (hits.isEmpty()) {
            score = Math.max(score, 0.15);
        }

        String reason = hits.isEmpty()
                ? "L2 text fallback: no risk keyword matched"
                : "L2 text fallback hits=" + String.join(",", hits);
        return scoreToDecision(score, reason);
    }

    private L2Decision scoreToDecision(double score, String reasonPrefix) {
        if (score >= properties.getRejectThreshold()) {
            return new L2Decision("REJECT", true, score, reasonPrefix + ", decision=REJECT");
        }
        if (score >= properties.getReviewThreshold()) {
            return new L2Decision("REVIEW", true, score, reasonPrefix + ", decision=REVIEW");
        }
        return new L2Decision("PASS_TO_L3", false, 1.0 - score, reasonPrefix + ", decision=PASS_TO_L3");
    }

    private double clamp(double value) {
        if (value < 0.0) {
            return 0.0;
        }
        if (value > 1.0) {
            return 1.0;
        }
        return value;
    }
}
