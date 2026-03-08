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
            while (current != root && !current.children.containsKey(c)) {
                current = current.fail;
            }
            current = current.children.getOrDefault(c, root);
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
