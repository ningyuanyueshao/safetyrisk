package com.multimodel.safetyrisk.moderation.config;

import java.util.ArrayList;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "moderation.l1")
public class L1FilterProperties {

    private List<String> sensitiveWords = new ArrayList<>();
    private List<String> regexRules = new ArrayList<>();
    private List<String> blockedUsers = new ArrayList<>();

    public List<String> getSensitiveWords() {
        return sensitiveWords;
    }

    public void setSensitiveWords(List<String> sensitiveWords) {
        this.sensitiveWords = sensitiveWords;
    }

    public List<String> getRegexRules() {
        return regexRules;
    }

    public void setRegexRules(List<String> regexRules) {
        this.regexRules = regexRules;
    }

    public List<String> getBlockedUsers() {
        return blockedUsers;
    }

    public void setBlockedUsers(List<String> blockedUsers) {
        this.blockedUsers = blockedUsers;
    }
}
