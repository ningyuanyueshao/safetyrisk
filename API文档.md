# MultiModel SafetyRisk API 文档

## 1. 文档范围

本文档基于当前代码实现整理（2026-09-16），覆盖：
- 对外审核接口（经 `gateway-service` 转发到 `moderation-service`）
- 异步任务接口（提交、查询、回放）
- 内部模型接口（`moderation-service` 调 `model-service`）

## 2. 基础信息

- 网关地址：`http://localhost:8080`
- 审核服务直连地址：`http://localhost:8081`
- 模型服务直连地址：`http://localhost:8082`
- 请求/响应格式：`application/json`

### 2.1 通用请求头

- `X-Request-Id`（可选）：请求唯一标识。
  - 若未传，网关或服务端自动生成 UUID。
  - 会透传到日志，便于排障与链路关联。

### 2.2 内容类型字段

`contentType` 取值：
- `TEXT`
- `IMAGE`
- `MIXED`

请求有效性校验：
- `TEXT`：`content` 必填且非空白
- `IMAGE`：`imageUrl` 与 `imageData` 至少有一个非空白
- `MIXED`：`content`、`imageUrl`、`imageData` 至少有一个非空白

图片字段约定：

- `imageUrl`：可被审核服务/模型 provider 访问的 HTTP(S) 地址。
- `imageData`：纯 Base64 或 `data:image/...;base64,...` data URL。
- 同时传入时，L2、百炼和本地 OpenAI-compatible L3 均优先使用 `imageData`。建议调用方只传一种图片来源。

## 3. 对外审核 API（Gateway）

以下接口推荐走网关 `:8080` 访问。

### 3.1 同步审核

- 方法与路径：`POST /api/v1/moderation/check`
- 描述：同步执行 `L1 -> model-service(L2/L3)` 审核链路；命中缓存时直接返回缓存结果。

请求体示例：

```json
{
  "contentType": "TEXT",
  "content": "这是一段待审核文本",
  "userId": "user-001"
}
```

成功响应（200）：

```json
{
  "requestId": "8a0871ad-f22d-4875-97c0-7444587c18d0",
  "violation": true,
  "decision": "REVIEW",
  "confidence": 0.65,
  "reason": "Model-service unavailable, fallback to REVIEW."
}
```

响应字段说明：
- `requestId`：请求 ID
- `violation`：是否违规（布尔）
- `decision`：`REJECT` / `REVIEW` / `PASS`
- `confidence`：0~1 置信度
- `reason`：决策原因；缓存命中时会追加 ` [CACHE_HIT]`

常见错误：
- `400`：请求参数校验失败
- `429`：网关 IP 限流触发
- `5xx`：服务异常

### 3.2 multipart 图片同步审核

- 方法与路径：`POST /api/v1/moderation/check/upload`
- 请求类型：`multipart/form-data`
- 必填 part：`image`
- 可选 part：`contentType`（`IMAGE` 或 `MIXED`，默认 `IMAGE`）、`content`、`userId`
- 描述：服务将上传文件转成 `imageData` 后复用同一条同步 pipeline，响应结构与 `/check` 相同。

### 3.3 异步审核提交

- 方法与路径：`POST /api/v1/moderation/check/async`
- 描述：提交审核任务到 Kafka，立即返回任务号。
- 幂等策略：按请求哈希去重（`contentType|userId|content|imageUrl|imageData` 的 SHA-256）：
  - 若已存在**进行中**任务（`PENDING/PROCESSING`），复用已有任务号，不重复入队。
  - 若已存在**已完成**任务（`COMPLETED`），直接复用历史审核结果，不重复入队。
  - `FAILED` 任务不参与复用，失败任务通过回放接口重新入队。

请求体示例：

```json
{
  "contentType": "MIXED",
  "content": "请审核文本",
  "imageUrl": "https://example.com/demo.jpg",
  "userId": "user-async-001"
}
```

成功响应（200）：

```json
{
  "requestId": "45c1f0f8-9570-4f65-8562-9d33cfad38df",
  "taskId": "dbf3942b-bbb8-4a8d-b775-b51f4440184f",
  "status": "PENDING",
  "message": "Task accepted and queued to Kafka."
}
```

命中已完成任务时直接复用历史结果（新增 `decision/violation/confidence/reason/completedAt` 字段）：

```json
{
  "requestId": "45c1f0f8-9570-4f65-8562-9d33cfad38df",
  "taskId": "dbf3942b-bbb8-4a8d-b775-b51f4440184f",
  "status": "COMPLETED",
  "message": "Task already completed, reuse existing result.",
  "decision": "PASS",
  "violation": false,
  "confidence": 0.82,
  "reason": "L3 decision parsed.",
  "completedAt": "2026-04-02T21:10:12"
}
```

常见错误：
- `400`：请求参数校验失败
- `500`：异步功能关闭、生产者不可用或入队失败

`imageData` 会持久化到 `moderation_task.image_data`，消费、重启恢复和失败回放均可重建原始图片请求。

### 3.4 查询异步任务

- 方法与路径：`GET /api/v1/moderation/tasks/{taskId}`
- 描述：查询任务状态及最终审核结果。

成功响应（200）：

```json
{
  "taskId": "dbf3942b-bbb8-4a8d-b775-b51f4440184f",
  "requestId": "45c1f0f8-9570-4f65-8562-9d33cfad38df",
  "status": "COMPLETED",
  "decision": "PASS",
  "violation": false,
  "confidence": 0.82,
  "reason": "L3 decision parsed.",
  "errorMessage": null,
  "createdAt": "2026-04-02T21:10:11",
  "updatedAt": "2026-04-02T21:10:12",
  "completedAt": "2026-04-02T21:10:12"
}
```

`status` 取值：
- `PENDING`
- `PROCESSING`
- `COMPLETED`
- `FAILED`

常见错误：
- `404`：任务不存在

### 3.5 单任务回放

- 方法与路径：`POST /api/v1/moderation/tasks/{taskId}/replay`
- 描述：仅允许回放 `FAILED` 任务，重新入队。

成功响应（200）：

```json
{
  "requestId": "f8a9a3e9-c559-4229-aa0e-12a0ce2ef167",
  "taskId": "89889887-7c45-4c3d-9dac-f46c4f173891",
  "status": "PENDING",
  "message": "Replay task accepted and queued."
}
```

常见错误：
- `404`：任务不存在
- `500`：任务不是 `FAILED`、异步未开启、生产者不可用

### 3.6 批量回放失败任务

- 方法与路径：`POST /api/v1/moderation/tasks/replay/batch?limit=20`
- 描述：按最近失败任务批量回放，`limit` 自动钳制到 `[1, 100]`。

成功响应（200）：

```json
{
  "requestId": "b16d5f6b-2d7f-4fbc-927a-c6fef9f52f49",
  "requestedLimit": 20,
  "replayedCount": 2,
  "items": [
    {
      "sourceTaskId": "src-task-1",
      "replayTaskId": "replay-task-1",
      "message": "Batch replay task accepted and queued."
    },
    {
      "sourceTaskId": "src-task-2",
      "replayTaskId": "replay-task-2",
      "message": "Batch replay task accepted and queued."
    }
  ]
}
```

## 4. 内部模型 API（Model Service）

该接口主要供 `moderation-service` 内部调用，生产环境不建议直接暴露公网。

### 4.1 模型推理

- 方法与路径：`POST /api/v1/model/classify`
- 描述：执行模型链路 `L2 -> (必要时) L3`，返回统一决策。

请求体：同 `ModerationRequest`。

成功响应（200）：

```json
{
  "decision": "PASS",
  "violation": false,
  "confidence": 0.86,
  "reason": "L3 decision parsed.",
  "decisionLayer": "L3"
}
```

响应 `decision` 取值：
- `REJECT`
- `REVIEW`
- `PASS`

`decisionLayer` 取值：`L2`、`L3`、`FALLBACK`，用于区分该次模型服务在哪一层终止。

服务内降级策略（对调用方透明）：
- L3 关闭 / 缺少密钥 / 熔断开启 -> `REVIEW`
- L3 调用异常 -> `REVIEW`
- 整体推理超时或异常 -> `REVIEW`

### 4.2 分层独立评测接口

- `POST /api/v1/model/classify/l2`：只执行 L2，不调用 L3。该接口会保留 L2 中间态 `PASS_TO_L3`，便于统计路由率、终止覆盖率和拒绝贡献。
- `POST /api/v1/model/classify/l3`：绕过 L2，直接调用当前配置的 L3 provider，用于测量纯 L3 质量。
- 两个接口的请求体均为 `ModerationRequest`，响应均为含 `decisionLayer` 的模型决策。

## 5. 决策语义约定

- `REJECT`：明确违规，建议直接拦截
- `REVIEW`：风险不确定，建议人工复审
- `PASS`：审核通过

> 说明：`PASS_TO_L3` 是 L2 内部中间状态，不会作为 Gateway 对外最终返回值；L2-only 评测接口会刻意保留它。

## 6. 限流与可用性说明

- 网关限流：`gateway-service` 按 IP 固定窗口限流，默认 `50 req/s/IP`
- 模型服务限流：可配置开关，默认关闭；开启后默认 `200 req/s/IP`
- 异步重试：Kafka 消费失败按固定退避重试，超过阈值进入 DLQ
- 缓存：`moderation-service` 使用 Caffeine + Redis 两级缓存，降低重复请求开销

## 7. 版本与变更

- 当前版本：`v1`
- 变更时间：`2026-09-16`
- 建议后续新增 `v2` 路由时保持向后兼容，避免直接修改现有字段语义。
