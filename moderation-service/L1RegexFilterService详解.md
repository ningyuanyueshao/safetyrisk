# L1RegexFilterService 详细流程说明

这份文档专门解释 `L1RegexFilterService` 的执行过程。你可以把它理解为：
“在大模型审核前，先用一层**快、稳、可解释**的规则筛查器做初判”。

---

## 1. 这个类解决什么问题

代码位置：
- `moderation-service/src/main/java/com/multimodel/safetyrisk/moderation/l1/L1RegexFilterService.java`

它做三件事（按优先级）：
1. 黑名单用户拦截
2. 敏感词拦截（Aho-Corasick）
3. 正则规则拦截

如果都没命中，就返回 `PASS`，交给后续 L2/L3 模型继续审核。

---

## 2. 输入与输出

### 输入：`ModerationRequest`
位置：
- `common-core/src/main/java/com/multimodel/safetyrisk/common/api/ModerationRequest.java`

关键字段：
- `contentType`：内容类型（TEXT / IMAGE / MIXED）
- `content`：文本内容（TEXT 时必填，由 `@AssertTrue` 做条件校验）
- `userId`：用户 ID（可为空）
- `imageUrl`：图片地址（可为空）
- `imageData`：纯 Base64 或 data URL（可为空，与 `imageUrl` 二选一即可构成 IMAGE 输入）

注意：L1RegexFilterService 当前主要用的是 `userId` 和 `content`。

### 输出：`L1FilterResult`
位置：
- `moderation-service/src/main/java/com/multimodel/safetyrisk/moderation/l1/L1FilterResult.java`

结构：
- `rejected`：是否拒绝
- `reason`：拒绝原因（如 `BLOCKED_USER` / `SENSITIVE_WORD` / `REGEX_RULE` / `PASS`）
- `matches`：命中的具体内容（用于排查和审计）

---

## 3. 配置从哪里来

配置类：
- `moderation-service/src/main/java/com/multimodel/safetyrisk/moderation/config/L1FilterProperties.java`

配置文件示例：
- `moderation-service/src/main/resources/application.yml`

对应关系：
- `moderation.l1.sensitive-words` -> 敏感词列表
- `moderation.l1.regex-rules` -> 正则规则列表
- `moderation.l1.blocked-users` -> 黑名单用户列表

示例（当前项目）：
- 敏感词：`赌博`、`毒品`、`色情`
- 正则：`buy/sell fake id`、`fraud`
- 黑名单：`blocked-user-001`

---

## 4. 生命周期：服务启动时发生了什么

### 4.1 Bean 创建
Spring 创建 `L1RegexFilterService`，构造函数注入 `L1FilterProperties`。

### 4.2 `@PostConstruct` 调用 `init()`
`init()` 会调用 `reload()`，把配置编译成运行时可高效查询的数据结构。

### 4.3 `reload()` 内部做了三次“预处理”
1. `matcher = new AhoCorasickMatcher(sensitiveWords)`
2. 把每条 regex 用 `Pattern.compile(..., CASE_INSENSITIVE)` 预编译
3. 把黑名单用户构建成集合 `blockedUsers`

这样做的目的：
- 把“重活”放在启动/重载阶段
- 把请求阶段变成快速判断

---

## 5. `filter()` 主流程（最重要）

下面是等价伪代码（和源码逻辑一致）：

```text
if userId 在 blockedUsers 中:
    return reject("BLOCKED_USER", [userId])

sensitiveHits = matcher.match(content)
if sensitiveHits 非空:
    return reject("SENSITIVE_WORD", sensitiveHits)

for 每个 regexPattern:
    if regexPattern 在 content 中 find 到:
        return reject("REGEX_RULE", [该 pattern 文本])

return pass()
```

### 关键点：这是“短路返回”
- 一旦命中某一层，后面不再执行
- 所以优先级是固定的：
  1. 黑名单用户
  2. 敏感词
  3. 正则
  4. 通过

---

## 6. 为什么敏感词用 Aho-Corasick

类位置：
- `moderation-service/src/main/java/com/multimodel/safetyrisk/moderation/l1/AhoCorasickMatcher.java`

你可以把它当成“多关键词匹配自动机”：
- 把多个关键词构成 Trie 树
- 通过 fail 指针处理失配回退
- 一次扫描文本，找出所有关键词命中

好处：
- 不用对每个关键词都单独 `contains` 一遍
- 在关键词多时性能更稳

实现细节（当前代码）：
- 文本和词表都会 `toLowerCase`（忽略大小写）
- 用 `Set` 去重命中结果

---

## 7. 一个完整示例

假设请求：
- `userId = "blocked-user-001"`
- `content = "I want to buy fake id"`

执行过程：
1. 先查黑名单，命中
2. 直接返回 `BLOCKED_USER`
3. 不会再执行敏感词和正则规则

再看另一个请求：
- `userId = "normal-user-01"`
- `content = "I want to buy fake id"`

执行过程：
1. 黑名单不命中
2. 敏感词（中文词）可能不命中
3. 正则 `buy/sell fake id` 命中
4. 返回 `REGEX_RULE`

---

## 8. 常见疑问与排查

### Q1: 为什么我加了配置但不生效？
先检查：
1. 配置前缀是否是 `moderation.l1`
2. 是否真的触发了 `reload()`（服务重启会触发）
3. 正则是否写对（Java 字符串和 YAML 转义）

### Q2: 会不会空指针？
`content` 在请求对象上是 `@NotBlank`，正常经控制器校验后不会为空。
如果你绕过了校验直接调用服务，`content` 为空时也会被 Aho-Corasick 的 `normalize` 转为空串，通常不会炸，但语义可能不符合预期。

### Q3: 为什么返回 PASS 还可能被拒绝？
`PASS` 只代表 “L1 规则层未命中”，并不是最终安全结论。后续 L2/L3 模型层仍可能拒绝。

---

## 9. 你可以怎么继续读代码（推荐顺序）

1. 先看 `L1RegexFilterService.filter()`（主流程）
2. 再看 `L1FilterResult`（返回结构）
3. 再看 `AhoCorasickMatcher.match()`（敏感词算法）
4. 最后看 `application.yml`（实际规则数据）

按这个顺序，你会更容易建立“从请求到结论”的完整心智模型。
