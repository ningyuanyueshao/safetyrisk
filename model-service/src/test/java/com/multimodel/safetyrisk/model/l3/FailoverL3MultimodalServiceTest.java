package com.multimodel.safetyrisk.model.l3;

import static org.assertj.core.api.Assertions.assertThat;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Mono;

class FailoverL3MultimodalServiceTest {

    @Test
    void primarySuccessDoesNotCallFallback() {
        AtomicInteger fallbackCalls = new AtomicInteger();
        L3Decision primaryDecision = decision("PASS", false, 0.93, "primary");
        FailoverL3MultimodalService service = new FailoverL3MultimodalService(
                request -> Mono.just(primaryDecision),
                request -> {
                    fallbackCalls.incrementAndGet();
                    return Mono.just(decision("REJECT", true, 0.99, "fallback"));
                });

        L3Decision result = service.classify(request()).block(Duration.ofSeconds(1));

        assertThat(result).isSameAs(primaryDecision);
        assertThat(fallbackCalls).hasValue(0);
    }

    @Test
    void primaryFailurePassesTheSameRequestToFallback() {
        ModerationRequest request = request();
        AtomicReference<ModerationRequest> fallbackRequest = new AtomicReference<>();
        L3Decision fallbackDecision = decision("REJECT", true, 0.91, "fallback");
        FailoverL3MultimodalService service = new FailoverL3MultimodalService(
                ignored -> Mono.error(new L3ModelUnavailableException("primary unavailable")),
                received -> {
                    fallbackRequest.set(received);
                    return Mono.just(fallbackDecision);
                });

        L3Decision result = service.classify(request).block(Duration.ofSeconds(1));

        assertThat(result).isSameAs(fallbackDecision);
        assertThat(fallbackRequest.get()).isSameAs(request);
    }

    @Test
    void bothProvidersFailClosedToReview() {
        FailoverL3MultimodalService service = new FailoverL3MultimodalService(
                request -> Mono.error(new L3ModelUnavailableException("primary unavailable")),
                request -> Mono.error(new L3ModelUnavailableException("fallback unavailable")));

        L3Decision result = service.classify(request()).block(Duration.ofSeconds(1));

        assertThat(result.getDecision()).isEqualTo("REVIEW");
        assertThat(result.isViolation()).isTrue();
        assertThat(result.getConfidence()).isEqualTo(0.70);
        assertThat(result.getReason()).contains("failed");
    }

    private ModerationRequest request() {
        ModerationRequest request = new ModerationRequest();
        request.setContentType(ModerationRequest.ContentType.MIXED);
        request.setContent("sample");
        request.setImageData("AQID");
        return request;
    }

    private L3Decision decision(String value, boolean violation, double confidence, String reason) {
        return new L3Decision(value, violation, confidence, reason);
    }
}
