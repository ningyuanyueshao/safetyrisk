package com.multimodel.safetyrisk.moderation.cache;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

public final class ModerationCacheKeyBuilder {

    private ModerationCacheKeyBuilder() {
    }

    public static String build(ModerationRequest request) {
        // Build key from moderation-relevant fields only so equivalent requests share cache.
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
            // Hash long or sensitive raw content before storing it as a Redis key.
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
