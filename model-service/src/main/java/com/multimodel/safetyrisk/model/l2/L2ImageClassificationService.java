package com.multimodel.safetyrisk.model.l2;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import reactor.core.publisher.Mono;

public interface L2ImageClassificationService {

    Mono<L2Decision> classify(ModerationRequest request);
}
