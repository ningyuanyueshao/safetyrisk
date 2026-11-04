package com.multimodel.safetyrisk.model.l2;

import static org.assertj.core.api.Assertions.assertThat;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Mono;

class L2ContentClassificationServiceTest {

    @Test
    void textRequestsOnlyInvokeTheTextClassifier() {
        AtomicInteger textCalls = new AtomicInteger();
        AtomicInteger imageCalls = new AtomicInteger();
        L2ContentClassificationService service = service(
                decision("PASS_TO_L3", false, 0.80),
                decision("REJECT", true, 0.95),
                textCalls,
                imageCalls);

        L2Decision result = block(service.classify(request(ModerationRequest.ContentType.TEXT)));

        assertThat(result.getDecision()).isEqualTo("PASS_TO_L3");
        assertThat(textCalls).hasValue(1);
        assertThat(imageCalls).hasValue(0);
    }

    @Test
    void imageRequestsOnlyInvokeTheImageClassifier() {
        AtomicInteger textCalls = new AtomicInteger();
        AtomicInteger imageCalls = new AtomicInteger();
        L2ContentClassificationService service = service(
                decision("REJECT", true, 0.95),
                decision("REVIEW", true, 0.70),
                textCalls,
                imageCalls);

        L2Decision result = block(service.classify(request(ModerationRequest.ContentType.IMAGE)));

        assertThat(result.getDecision()).isEqualTo("REVIEW");
        assertThat(textCalls).hasValue(0);
        assertThat(imageCalls).hasValue(1);
    }

    @Test
    void imageDataIsForwardedToTheImageClassifier() {
        AtomicInteger imageDataCalls = new AtomicInteger();
        L2TextClassificationService textService = ignored -> Mono.just(decision("PASS_TO_L3", false, 0.80));
        L2ImageClassificationService imageService = request -> {
            if ("aGVsbG8=".equals(request.getImageData())) {
                imageDataCalls.incrementAndGet();
            }
            return Mono.just(decision("PASS_TO_L3", false, 0.80));
        };
        L2ContentClassificationService service = new L2ContentClassificationService(textService, imageService);
        ModerationRequest request = request(ModerationRequest.ContentType.IMAGE);
        request.setImageUrl(null);
        request.setImageData("aGVsbG8=");

        block(service.classify(request));

        assertThat(imageDataCalls).hasValue(1);
    }

    @Test
    void mixedRejectTakesPriorityAndUsesTheHighestConfidence() {
        L2ContentClassificationService service = service(
                decision("REVIEW", true, 0.70),
                decision("REJECT", true, 0.93),
                new AtomicInteger(),
                new AtomicInteger());

        L2Decision result = block(service.classify(request(ModerationRequest.ContentType.MIXED)));

        assertThat(result.getDecision()).isEqualTo("REJECT");
        assertThat(result.isViolation()).isTrue();
        assertThat(result.getConfidence()).isEqualTo(0.93);
    }

    @Test
    void mixedReviewTakesPriorityOverPassToL3() {
        L2ContentClassificationService service = service(
                decision("PASS_TO_L3", false, 0.88),
                decision("REVIEW", true, 0.66),
                new AtomicInteger(),
                new AtomicInteger());

        L2Decision result = block(service.classify(request(ModerationRequest.ContentType.MIXED)));

        assertThat(result.getDecision()).isEqualTo("REVIEW");
        assertThat(result.getConfidence()).isEqualTo(0.88);
    }

    @Test
    void mixedPassToL3UsesTheLowerConfidence() {
        L2ContentClassificationService service = service(
                decision("PASS_TO_L3", false, 0.91),
                decision("PASS_TO_L3", false, 0.82),
                new AtomicInteger(),
                new AtomicInteger());

        L2Decision result = block(service.classify(request(ModerationRequest.ContentType.MIXED)));

        assertThat(result.getDecision()).isEqualTo("PASS_TO_L3");
        assertThat(result.isViolation()).isFalse();
        assertThat(result.getConfidence()).isEqualTo(0.82);
    }

    private L2ContentClassificationService service(
            L2Decision textDecision,
            L2Decision imageDecision,
            AtomicInteger textCalls,
            AtomicInteger imageCalls) {
        L2TextClassificationService textService = request -> {
            textCalls.incrementAndGet();
            return Mono.just(textDecision);
        };
        L2ImageClassificationService imageService = request -> {
            imageCalls.incrementAndGet();
            return Mono.just(imageDecision);
        };
        return new L2ContentClassificationService(textService, imageService);
    }

    private L2Decision decision(String decision, boolean violation, double confidence) {
        return new L2Decision(decision, violation, confidence, "test");
    }

    private ModerationRequest request(ModerationRequest.ContentType type) {
        ModerationRequest request = new ModerationRequest();
        request.setContentType(type);
        request.setContent("sample text");
        request.setImageUrl("https://images.example.test/sample.jpg");
        return request;
    }

    private L2Decision block(Mono<L2Decision> result) {
        return result.block(Duration.ofSeconds(1));
    }
}
