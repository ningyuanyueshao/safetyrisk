package com.multimodel.safetyrisk.moderation.l1;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.moderation.config.L1FilterProperties;
import jakarta.annotation.PostConstruct;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Pattern;
import org.springframework.stereotype.Service;

@Service
public class L1RegexFilterService {

    private final L1FilterProperties properties;

    private volatile AhoCorasickMatcher matcher = new AhoCorasickMatcher(List.of());
    private volatile List<Pattern> regexPatterns = List.of();
    private volatile Set<String> blockedUsers = Set.of();

    public L1RegexFilterService(L1FilterProperties properties) {
        this.properties = properties;
    }

    @PostConstruct
    public void init() {
        reload();
    }

    public void reload() {
        // Build automaton once and reuse for O(n) multi-keyword scanning per request.
        this.matcher = new AhoCorasickMatcher(properties.getSensitiveWords());

        List<Pattern> compiled = new ArrayList<>();
        for (String regexRule : properties.getRegexRules()) {
            compiled.add(Pattern.compile(regexRule, Pattern.CASE_INSENSITIVE));
        }
        this.regexPatterns = List.copyOf(compiled);

        Set<String> users = ConcurrentHashMap.newKeySet();
        users.addAll(properties.getBlockedUsers());
        this.blockedUsers = Set.copyOf(users);
    }

    public L1FilterResult filter(ModerationRequest request) {
        // 1) User-level blocklist has highest priority and short-circuits immediately.
        if (request.getUserId() != null && blockedUsers.contains(request.getUserId())) {
            return L1FilterResult.reject("BLOCKED_USER", List.of(request.getUserId()));
        }

        // 2) Sensitive words check via Aho-Corasick for deterministic low-latency matching.
        List<String> sensitiveHits = matcher.match(request.getContent());
        if (!sensitiveHits.isEmpty()) {
            return L1FilterResult.reject("SENSITIVE_WORD", sensitiveHits);
        }

        // 3) Regex rules cover patterns that are hard to express as plain keywords.
        for (Pattern pattern : regexPatterns) {
            if (pattern.matcher(request.getContent()).find()) {
                return L1FilterResult.reject("REGEX_RULE", List.of(pattern.pattern()));
            }
        }

        return L1FilterResult.pass();
    }
}
