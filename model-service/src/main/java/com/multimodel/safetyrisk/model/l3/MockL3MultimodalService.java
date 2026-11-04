package com.multimodel.safetyrisk.model.l3;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import reactor.core.publisher.Mono;

public class MockL3MultimodalService implements L3MultimodalService {

    private static final Logger log = LoggerFactory.getLogger(MockL3MultimodalService.class);

    @Override
    public Mono<L3Decision> classify(ModerationRequest request) {
        log.info("Mock L3 service called for userId: {}", request.getUserId());

        // Mock 逻辑：简单的关键词匹配
        String content = request.getContent() == null ? "" : request.getContent().toLowerCase();

        if (content.contains("诈骗") || content.contains("赌博") || content.contains("毒品")
                || content.contains("裸聊") || content.contains("色情")) {
            return Mono.just(new L3Decision("REJECT", true, 0.95, "Mock L3: detected high-risk keywords"));
        }

        if (content.contains("可疑") || content.contains("风险") || content.contains("敏感")) {
            return Mono.just(new L3Decision("REVIEW", true, 0.75, "Mock L3: detected medium-risk keywords"));
        }

        return Mono.just(new L3Decision("PASS", false, 0.90, "Mock L3: no risk detected"));
    }
}
