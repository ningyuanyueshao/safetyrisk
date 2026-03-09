package com.multimodel.safetyrisk.moderation.l1;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Queue;
import java.util.Set;

public class AhoCorasickMatcher {

    private final Node root = new Node();

    public AhoCorasickMatcher(List<String> patterns) {
        for (String pattern : patterns) {
            String normalized = normalize(pattern);
            if (!normalized.isBlank()) {
                insert(normalized);
            }
        }
        buildFailureLinks();
    }

    public List<String> match(String text) {
        String normalized = normalize(text);
        Node current = root;
        Set<String> uniqueMatches = new HashSet<>();

        for (char c : normalized.toCharArray()) {
            // 沿失配指针回退，直到找到可用转移（或回到根节点）。
            while (current != root && !current.children.containsKey(c)) {
                current = current.fail;
            }
            current = current.children.getOrDefault(c, root);
            // outputs 同时包含当前节点命中和由后缀继承的命中项。
            uniqueMatches.addAll(current.outputs);
        }

        return new ArrayList<>(uniqueMatches);
    }

    private void insert(String pattern) {
        Node current = root;
        for (char c : pattern.toCharArray()) {
            current = current.children.computeIfAbsent(c, ignored -> new Node());
        }
        current.outputs.add(pattern);
    }

    private void buildFailureLinks() {
        Queue<Node> queue = new ArrayDeque<>();

        for (Node child : root.children.values()) {
            child.fail = root;
            queue.offer(child);
        }

        while (!queue.isEmpty()) {
            Node current = queue.poll();

            for (Map.Entry<Character, Node> entry : current.children.entrySet()) {
                char transition = entry.getKey();
                Node next = entry.getValue();

                Node failure = current.fail;
                while (failure != null && !failure.children.containsKey(transition)) {
                    failure = failure.fail;
                }

                // 若不存在可用后缀转移，则失配指针回落到根节点。
                next.fail = failure == null ? root : failure.children.get(transition);
                next.outputs.addAll(next.fail.outputs);
                queue.offer(next);
            }
        }

        root.fail = root;
    }

    private String normalize(String input) {
        return input == null ? "" : input.toLowerCase(Locale.ROOT);
    }

    private static final class Node {
        private final Map<Character, Node> children = new HashMap<>();
        private final List<String> outputs = new ArrayList<>();
        private Node fail;
    }
}
