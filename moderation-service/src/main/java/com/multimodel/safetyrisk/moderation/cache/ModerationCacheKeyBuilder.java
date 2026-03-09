package com.multimodel.safetyrisk.moderation.cache;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

public final class ModerationCacheKeyBuilder {

    private ModerationCacheKeyBuilder() {
    }

    public static String build(ModerationRequest request) {
        // 仅使用审核相关字段构建键，保证等价请求共享缓存结果。
        String raw = String.join("|",
                safe(request.getContentType() == null ? null : request.getContentType().name()),
                safe(request.getUserId()),
                safe(request.getContent()),
                safe(request.getImageUrl()));
        return sha256Hex(raw);
    }

    private static String safe(String input) {
        return input == null ? "" : input;
    }

    private static String sha256Hex(String raw) {
        try {
            // 先做哈希再作为 Redis 键，避免键过长并降低敏感信息暴露风险。
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(raw.getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder(bytes.length * 2);
            for (byte current : bytes) {
                String hex = Integer.toHexString(current & 0xff);
                if (hex.length() == 1) {
                    builder.append('0');
                }
                builder.append(hex);
            }
            return builder.toString();
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 algorithm is required", ex);
        }
    }
}
