package com.multimodel.safetyrisk.moderation.l1;

import java.util.Collections;
import java.util.List;

public class L1FilterResult {

    private final boolean rejected;
    private final String reason;
    private final List<String> matches;

    private L1FilterResult(boolean rejected, String reason, List<String> matches) {
        this.rejected = rejected;
        this.reason = reason;
        this.matches = matches;
    }

    public static L1FilterResult pass() {
        // PASS means this layer found no hard violation; later layers may still reject.
        return new L1FilterResult(false, "PASS", Collections.emptyList());
    }

    public static L1FilterResult reject(String reason, List<String> matches) {
        // Preserve concrete matches to improve traceability and auditability.
        return new L1FilterResult(true, reason, matches);
    }

    public boolean isRejected() {
        return rejected;
    }

    public String getReason() {
        return reason;
    }

    public List<String> getMatches() {
        return matches;
    }
}
