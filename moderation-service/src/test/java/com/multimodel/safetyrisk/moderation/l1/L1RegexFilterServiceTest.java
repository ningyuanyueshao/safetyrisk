package com.multimodel.safetyrisk.moderation.l1;

import static org.assertj.core.api.Assertions.assertThat;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.moderation.config.L1FilterProperties;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class L1RegexFilterServiceTest {

    private L1RegexFilterService service;

    @BeforeEach
    void setUp() {
        L1FilterProperties properties = new L1FilterProperties();
        properties.setSensitiveWords(List.of("赌博", "毒品", "fraud"));
        properties.setRegexRules(List.of("\\b(?:buy|sell)\\s+fake\\s+id\\b"));
        properties.setBlockedUsers(List.of("blocked-user"));
        service = new L1RegexFilterService(properties);
        service.init();
    }

    @Test
    void blockedUserHasHighestPriorityEvenForImageRequests() {
        ModerationRequest request = request(ModerationRequest.ContentType.IMAGE, null);
        request.setImageUrl("https://images.example.test/safe.jpg");
        request.setUserId("blocked-user");

        L1FilterResult result = service.filter(request);

        assertThat(result.isRejected()).isTrue();
        assertThat(result.getReason()).isEqualTo("BLOCKED_USER");
        assertThat(result.getMatches()).containsExactly("blocked-user");
    }

    @Test
    void sensitiveWordsAreMatchedCaseInsensitively() {
        L1FilterResult result = service.filter(request(
                ModerationRequest.ContentType.TEXT,
                "This looks like FRAUD."));

        assertThat(result.isRejected()).isTrue();
        assertThat(result.getReason()).isEqualTo("SENSITIVE_WORD");
        assertThat(result.getMatches()).containsExactly("fraud");
    }

    @Test
    void regexUsesWordBoundaries() {
        L1FilterResult rejected = service.filter(request(
                ModerationRequest.ContentType.TEXT,
                "I want to buy fake id today"));
        L1FilterResult passed = service.filter(request(
                ModerationRequest.ContentType.TEXT,
                "I buy fake ideas for a workshop"));

        assertThat(rejected.isRejected()).isTrue();
        assertThat(rejected.getReason()).isEqualTo("REGEX_RULE");
        assertThat(passed.isRejected()).isFalse();
    }

    @Test
    void imageRequestsDoNotApplyTextRules() {
        ModerationRequest request = request(ModerationRequest.ContentType.IMAGE, "赌博");
        request.setImageUrl("https://images.example.test/sample.jpg");

        assertThat(service.filter(request).isRejected()).isFalse();
    }

    @Test
    void blankTextPassesToTheNextLayer() {
        assertThat(service.filter(request(ModerationRequest.ContentType.TEXT, "  ")).isRejected()).isFalse();
    }

    private ModerationRequest request(ModerationRequest.ContentType type, String content) {
        ModerationRequest request = new ModerationRequest();
        request.setContentType(type);
        request.setContent(content);
        return request;
    }
}
