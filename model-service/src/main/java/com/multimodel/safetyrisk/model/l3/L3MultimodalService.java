package com.multimodel.safetyrisk.model.l3;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import reactor.core.publisher.Mono;

public interface L3MultimodalService {

    Mono<L3Decision> classify(ModerationRequest request);
}
