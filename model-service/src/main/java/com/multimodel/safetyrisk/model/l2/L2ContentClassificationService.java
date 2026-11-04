package com.multimodel.safetyrisk.model.l2;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

@Service
public class L2ContentClassificationService {

    private final L2TextClassificationService textService;
    private final L2ImageClassificationService imageService;

    public L2ContentClassificationService(L2TextClassificationService textService, L2ImageClassificationService imageService) {
        this.textService = textService;
        this.imageService = imageService;
    }

    public Mono<L2Decision> classify(ModerationRequest request) {
        ModerationRequest.ContentType type = request.getContentType();
        if (type == ModerationRequest.ContentType.TEXT) {
            return textService.classify(request);
        }
        if (type == ModerationRequest.ContentType.IMAGE) {
            return imageService.classify(request);
        }

        return Mono.zip(textService.classify(request), imageService.classify(request))
                .map(tuple -> merge(tuple.getT1(), tuple.getT2()));
    }

    private L2Decision merge(L2Decision textDecision, L2Decision imageDecision) {
        if ("REJECT".equals(textDecision.getDecision()) || "REJECT".equals(imageDecision.getDecision())) {
            return new L2Decision(
                    "REJECT",
                    true,
                    Math.max(textDecision.getConfidence(), imageDecision.getConfidence()),
                    "L2 mixed decision from text+image, text=" + textDecision.getDecision() + ", image=" + imageDecision.getDecision());
        }
        if ("REVIEW".equals(textDecision.getDecision()) || "REVIEW".equals(imageDecision.getDecision())) {
            return new L2Decision(
                    "REVIEW",
                    true,
                    Math.max(textDecision.getConfidence(), imageDecision.getConfidence()),
                    "L2 mixed decision from text+image, text=" + textDecision.getDecision() + ", image=" + imageDecision.getDecision());
        }
        return new L2Decision(
                "PASS_TO_L3",
                false,
                Math.min(textDecision.getConfidence(), imageDecision.getConfidence()),
                "L2 mixed decision from text+image, text=PASS_TO_L3, image=PASS_TO_L3");
    }
}
