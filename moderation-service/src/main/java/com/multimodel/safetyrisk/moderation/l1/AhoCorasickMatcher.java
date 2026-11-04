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

    // AC 自动机的根节点，所有匹配都从这里开始。
    private final Node root = new Node();

    public AhoCorasickMatcher(List<String> patterns) {
        // 先把词表插入 Trie。
        for (String pattern : patterns) {
            // 统一做大小写归一化，避免大小写导致漏匹配。
            String normalized = normalize(pattern);
            // 跳过空词，避免产生无意义节点。
            if (!normalized.isBlank()) {
                insert(normalized);
            }
        }
        // Trie 建好后，补齐失配指针（fail 指针）。
        buildFailureLinks();
    }

    public List<String> match(String text) {
        // 与词表同样的归一化规则，确保匹配语义一致。
        String normalized = normalize(text);
        // current 表示“当前匹配状态”所在节点。
        Node current = root;
        // 去重收集命中的敏感词，避免同一词重复返回多次。
        Set<String> uniqueMatches = new HashSet<>();

        // 单次线性扫描文本字符。
        for (char c : normalized.toCharArray()) {
            // 沿失配指针回退，直到找到可用转移（或回到根节点）。
            while (current != root && !current.children.containsKey(c)) {
                current = current.fail;
            }
            // 如果有对应子边就向下走，否则停留在 root。
            current = current.children.getOrDefault(c, root);
            // outputs 同时包含当前节点命中和由后缀继承的命中项。
            uniqueMatches.addAll(current.outputs);
        }

        // 转成 List 返回给调用方。
        return new ArrayList<>(uniqueMatches);
    }

    private void insert(String pattern) {
        // 从根节点开始逐字符插入 Trie。
        Node current = root;
        for (char c : pattern.toCharArray()) {
            // 如果不存在该字符分支就创建新节点。
            current = current.children.computeIfAbsent(c, ignored -> new Node());
        }
        // 走到词尾后，把完整模式串挂到 outputs。
        current.outputs.add(pattern);
    }

    private void buildFailureLinks() {
        // BFS 构建 fail 指针：从浅层到深层逐层推进。
        Queue<Node> queue = new ArrayDeque<>();

        // 根节点的第一层子节点 fail 都指向 root。
        for (Node child : root.children.values()) {
            child.fail = root;
            queue.offer(child);
        }

        // 广度优先遍历每个节点，为其子节点计算 fail。
        while (!queue.isEmpty()) {
            Node current = queue.poll();

            for (Map.Entry<Character, Node> entry : current.children.entrySet()) {
                // transition 是当前边的字符，next 是要设置 fail 的子节点。
                char transition = entry.getKey();
                Node next = entry.getValue();

                // 从 current 的 fail 开始尝试寻找可用后缀转移。
                Node failure = current.fail;
                while (failure != null && !failure.children.containsKey(transition)) {
                    failure = failure.fail;
                }

                // 若不存在可用后缀转移，则失配指针回落到根节点。
                next.fail = failure == null ? root : failure.children.get(transition);
                // 继承 fail 节点的输出，支持“一次到位”拿到后缀命中。
                next.outputs.addAll(next.fail.outputs);
                // 继续处理 next 的子节点。
                queue.offer(next);
            }
        }

        // 根节点 fail 指向自己，匹配逻辑里可以少做空判断。
        root.fail = root;
    }

    private String normalize(String input) {
        // null 视为空串，并统一转小写。
        return input == null ? "" : input.toLowerCase(Locale.ROOT);
    }

    private static final class Node {
        // Trie 的字符转移表：当前字符 -> 下一个节点。
        private final Map<Character, Node> children = new HashMap<>();
        // 到达该节点时能命中的词（包含直接命中和后缀继承命中）。
        private final List<String> outputs = new ArrayList<>();
        // 失配指针：当前路径无法继续时跳转到的“最长可用后缀”节点。
        private Node fail;
    }
}
