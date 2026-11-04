package com.multimodel.safetyrisk.model.service;

import static org.assertj.core.api.Assertions.assertThat;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.common.api.model.ModelDecisionResponse;
import com.multimodel.safetyrisk.model.config.ModelProtectionProperties;
import com.multimodel.safetyrisk.model.l2.L2ContentClassificationService;
import com.multimodel.safetyrisk.model.l2.L2Decision;
import com.multimodel.safetyrisk.model.l2.L2ImageClassificationService;
import com.multimodel.safetyrisk.model.l2.L2TextClassificationService;
import com.multimodel.safetyrisk.model.l3.L3Decision;
import com.multimodel.safetyrisk.model.l3.L3MultimodalService;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Mono;

class ModelInferenceServiceTest {

    @Test
    void l3OnlyInferenceBypassesL2AndMarksTheDecisionLayer() {
        AtomicInteger l2Calls = new AtomicInteger();
        AtomicInteger l3Calls = new AtomicInteger();
        L2TextClassificationService text = request -> {
            l2Calls.incrementAndGet();
            return Mono.just(new L2Decision("REJECT", true, 0.99, "must not run"));
        };
        L2ImageClassificationService image = request -> Mono.just(
                new L2Decision("PASS_TO_L3", false, 0.8, "unused"));
        L2ContentClassificationService l2 = new L2ContentClassificationService(text, image);
        L3MultimodalService l3 = request -> {
            l3Calls.incrementAndGet();
            return Mono.just(new L3Decision("PASS", false, 0.95, "l3 test"));
        };
        ModelProtectionProperties protection = new ModelProtectionProperties();
        protection.setInferTimeoutMs(1_000);
        ModelInferenceService service = new ModelInferenceService(l2, l3, protection);
        ModerationRequest request = new ModerationRequest();
        request.setContentType(ModerationRequest.ContentType.TEXT);
        request.setContent("fixture");

        ModelDecisionResponse response = service.inferL3(request).block(Duration.ofSeconds(1));

        assertThat(response).isNotNull();
        assertThat(response.getDecision()).isEqualTo("PASS");
        assertThat(response.getDecisionLayer()).isEqualTo("L3");
        assertThat(l2Calls).hasValue(0);
        assertThat(l3Calls).hasValue(1);
    }
}
