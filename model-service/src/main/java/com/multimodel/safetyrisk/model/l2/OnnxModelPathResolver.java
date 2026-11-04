package com.multimodel.safetyrisk.model.l2;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

final class OnnxModelPathResolver {

    private static final Logger log = LoggerFactory.getLogger(OnnxModelPathResolver.class);
    private static final String[] CANDIDATE_FILES = {"model.onnx", "model_quantized.onnx"};

    private OnnxModelPathResolver() {}

    static Optional<Path> resolve(String configuredPath) {
        if (configuredPath == null || configuredPath.isBlank()) {
            return Optional.empty();
        }

        List<Path> candidates = new ArrayList<>();
        Path original = Path.of(configuredPath);
        candidates.add(original);
        if (!original.isAbsolute()) {
            candidates.add(Path.of("").resolve(original));
            candidates.add(Path.of("..").resolve(original));
            candidates.add(Path.of("../..").resolve(original));
        }

        for (Path candidate : candidates) {
            Optional<Path> resolved = resolveCandidate(candidate);
            if (resolved.isPresent()) {
                return resolved;
            }
        }

        log.warn("Cannot resolve ONNX model path from config='{}'", configuredPath);
        return Optional.empty();
    }

    private static Optional<Path> resolveCandidate(Path candidate) {
        try {
            if (Files.isDirectory(candidate)) {
                for (String filename : CANDIDATE_FILES) {
                    Path file = candidate.resolve(filename);
                    if (Files.exists(file)) {
                        return Optional.of(file.toAbsolutePath().normalize());
                    }
                }
            }
            if (Files.exists(candidate)) {
                return Optional.of(candidate.toAbsolutePath().normalize());
            }
        } catch (Exception ex) {
            log.warn("Failed resolving candidate path={}", candidate, ex);
        }
        return Optional.empty();
    }
}
