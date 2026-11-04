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
        // 自动机构建一次后复用，使每次请求可进行 O(n) 的多关键词扫描。
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
        // 1) 用户级黑名单优先级最高，命中后立即短路返回。
        if (request.getUserId() != null && blockedUsers.contains(request.getUserId())) {
            return L1FilterResult.reject("BLOCKED_USER", List.of(request.getUserId()));
        }

        // IMAGE 请求不做文本规则过滤，直接放行到模型层。
        if (request.getContentType() == ModerationRequest.ContentType.IMAGE) {
            return L1FilterResult.pass();
        }

        String text = request.getContent() == null ? "" : request.getContent();
        if (text.isBlank()) {
            return L1FilterResult.pass();
        }

        // 2) 使用 Aho-Corasick 进行敏感词检测，保证确定性与低延迟。
        List<String> sensitiveHits = matcher.match(text);
        if (!sensitiveHits.isEmpty()) {
            return L1FilterResult.reject("SENSITIVE_WORD", sensitiveHits);
        }

        // 3) 正则规则用于覆盖难以用关键词表达的模式。
        for (Pattern pattern : regexPatterns) {
            if (pattern.matcher(text).find()) {
                return L1FilterResult.reject("REGEX_RULE", List.of(pattern.pattern()));
            }
        }

        return L1FilterResult.pass();
    }
}
