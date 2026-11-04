package com.multimodel.safetyrisk.model.controller;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.common.api.model.ModelDecisionResponse;
import com.multimodel.safetyrisk.model.service.ModelInferenceService;
import jakarta.validation.Valid;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

@RestController
@RequestMapping("/api/v1/model")
public class ModelInferenceController {

    private final ModelInferenceService modelInferenceService;

    public ModelInferenceController(ModelInferenceService modelInferenceService) {
        this.modelInferenceService = modelInferenceService;
    }

    @PostMapping(value = "/classify", consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<ModelDecisionResponse> classify(@Valid @RequestBody ModerationRequest request) {
        return modelInferenceService.infer(request);
    }

    @PostMapping(value = "/classify/l2", consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<ModelDecisionResponse> classifyL2(@Valid @RequestBody ModerationRequest request) {
        return modelInferenceService.inferL2(request);
    }

    @PostMapping(value = "/classify/l3", consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<ModelDecisionResponse> classifyL3(@Valid @RequestBody ModerationRequest request) {
        return modelInferenceService.inferL3(request);
    }
}
