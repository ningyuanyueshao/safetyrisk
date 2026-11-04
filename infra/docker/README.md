# Docker Compose 目录

本目录提供本地开发环境的一键编排。

## 文件说明
- `docker-compose.yml`：本地依赖与服务编排（Redis/MySQL/Kafka/Zipkin + 三个业务服务 + Prometheus/Grafana）。
- `docker-compose.mock-l3.yml`：Mock L3 联调示例覆盖文件。
- `.env.example`：环境变量模板。
- `prometheus.yml`：Prometheus 抓取配置（Gateway/Moderation/Model 的 `/actuator/prometheus`）。
- `alerts/`：Prometheus 告警规则（服务可用性、异步重试/DLQ 等）。
- `grafana/`：Grafana 数据源与仪表盘自动加载配置（含 `Moderation Async Overview`）。
- 链路追踪：基于 **Micrometer Tracing + Zipkin**（Spring Boot 3 下的 Sleuth 替代方案）。

## 使用方式
0. 一键本地开发启动（推荐）：
   - 默认故障转移 L3（百炼 -> 本地 Ollama）：`./scripts/dev-local.sh start`
   - 脚本会读取 `infra/docker/.env`；命令行显式设置的同名环境变量优先
   - 启用 Mock L3：`ENABLE_L3_MOCK=true ./scripts/dev-local.sh start`
   - 查看状态：`./scripts/dev-local.sh status`
   - 查看日志：`./scripts/dev-local.sh logs gateway-service`
   - 停止本地服务：`./scripts/dev-local.sh stop`
   - 停止本地服务 + 依赖容器：`./scripts/dev-local.sh stop-all`
1. 在本目录复制环境变量文件：
   - `cp .env.example .env`
   - 默认 L3 是故障转移模式：填写 `DASHSCOPE_API_KEY`（也兼容 `BAILIAN_API_KEY`）；百炼模型用 `MODEL_L3_BAILIAN_MODEL` 切换，默认 `qwen3.8-flash`
   - 本地兜底默认使用 Ollama 的 `qwen3.5:0.8b`；先执行 `ollama pull qwen3.5:0.8b`。宿主机地址由 `MODEL_L3_VLLM_BASE_URL` 控制，容器地址由 `MODEL_L3_VLLM_DOCKER_BASE_URL` 控制
   - `MODEL_L3_VLLM_BASE_URL` / `MODEL_L3_VLLM_MODEL` 是为兼容既有配置保留的变量名，可指向 Ollama、vLLM 等 OpenAI 兼容接口
   - L2 图像模型由 Compose 只读挂载到 `/models/resnet50_finetune_onnx`；当前文本分类头未经风控数据微调，`MODEL_L2_TEXT_ENABLED=false` 时使用关键词 fallback，避免把随机分类头当成有效模型
   - Ollama 默认设 `MODEL_L3_VLLM_REASONING_EFFORT=none`，避免 0.8B 模型把短超时预算耗在思考过程；若目标端点不支持该字段，将它设为空字符串即可省略
   - 只使用百炼 API 时设置 `MODEL_L3_PROVIDER=bailian`
   - 只使用本地 OpenAI 兼容模型时设置 `MODEL_L3_PROVIDER=vllm`
   - Mock 模式可保留 `DASHSCOPE_API_KEY=mock-key`
2. 推荐开发模式：仅启动基础依赖（不启动业务服务容器）：
   - `docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env up -d`
   - 如需 Mock L3，再加：`--profile mock-l3`
3. 本地 Maven 运行业务服务（代码改动后只需本地重启，不用 Docker build）：
   - 终端 1（moderation）：
     - `cd moderation-service && mvn spring-boot:run`
   - 终端 2（model）：
     - 默认故障转移 L3（百炼 -> 本地 Ollama）：`cd model-service && mvn spring-boot:run`
     - 只用百炼 API：`cd model-service && MODEL_L3_PROVIDER=bailian DASHSCOPE_API_KEY=你的Key MODEL_L3_BAILIAN_MODEL=qwen3.8-flash mvn spring-boot:run`
     - 只用本地模型：`cd model-service && MODEL_L3_PROVIDER=vllm MODEL_L3_VLLM_BASE_URL=http://localhost:11434/v1 MODEL_L3_VLLM_MODEL=qwen3.5:0.8b mvn spring-boot:run`
     - Mock L3：`cd model-service && SPRING_PROFILES_ACTIVE=l3-mock MODEL_L3_BAILIAN_BASE_URL=http://localhost:8089/compatible-mode/v1 DASHSCOPE_API_KEY=mock-key mvn spring-boot:run`
   - 终端 3（gateway）：
     - `cd gateway-service && mvn spring-boot:run`
4. 如需完整容器化联调（包含三业务服务）：
   - 默认故障转移 L3：`docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env --profile apps up -d`
   - Mock L3 故障注入：`MODEL_L3_PROVIDER=bailian MODEL_SERVICE_ACTIVE_PROFILE=l3-mock MODEL_L3_BAILIAN_BASE_URL=http://mock-bailian-service:8089/compatible-mode/v1 docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env --profile apps --profile mock-l3 up -d`
5. 启动监控组件（Prometheus + Grafana）：
   - `docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env --profile observability up -d`
   - 联合启动业务服务和监控：
     - `docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env --profile apps --profile observability up -d`
   - Mock L3 故障注入联合启动：`MODEL_L3_PROVIDER=bailian MODEL_SERVICE_ACTIVE_PROFILE=l3-mock MODEL_L3_BAILIAN_BASE_URL=http://mock-bailian-service:8089/compatible-mode/v1 docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env --profile apps --profile mock-l3 --profile observability up -d`
6. 只重建单个业务服务镜像（改哪儿重建哪儿）：
   - `COMPOSE_DOCKER_CLI_BUILD=0 DOCKER_BUILDKIT=0 docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env --profile apps build gateway-service`
   - `docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env --profile apps up -d --no-build gateway-service`
   - 本次 `imageData` 链路改动涉及 `model-service` 和 `moderation-service`；若使用容器化业务服务，需重建这两个镜像（gateway 未改动可不重建）。已有 MySQL volume 不需要重建，但旧库必须执行 `infra/docker/migrations/20260914_add_moderation_task_image_data.sql`。
7. 查看状态：
   - `docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env ps -a`
8. 停止并清理：
   - `docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env down`
9. 热加载 Prometheus 配置/规则（修改 `prometheus.yml` 或 `alerts/*.yml` 后）：
   - `curl -X POST http://localhost:9090/-/reload`

## 访问入口
- Gateway: `http://localhost:8080`
- Moderation: `http://localhost:8081`
- Model: `http://localhost:8082`
- Mock Bailian: `http://localhost:8089`
- Zipkin: `http://localhost:9411`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`（默认账号密码：`admin/admin`，可在 `.env` 中覆盖）

## 超时预算阶梯
默认采用“严格一致性”模式：同步与异步请求都允许 model-service 走完同一条 provider/failover 链，避免同步请求被外层 6s 提前截断、异步请求却继续得到最终结果。30s 是失败场景的上限，正常请求仍会在模型返回后立即完成。

调 timeout 相关配置时必须保证下面这条链自洽（任一层改动都要核对其上下的层）：

| 层级 | 配置 | 默认值 |
| --- | --- | --- |
| 百炼 provider | `MODEL_L3_BAILIAN_TIMEOUT_MS` | `18000` |
| 本地 provider | `MODEL_L3_VLLM_TIMEOUT_MS` | `7000` |
| model-service 全链兜底 | `MODEL_SERVICE_INFER_TIMEOUT_MS` | `27000` |
| moderation 同步调用 | `MODERATION_MODEL_SERVICE_TIMEOUT_MS` | `30000` |
| moderation 异步调用 | `MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS` | `30000` |
| Gateway 响应 | `GATEWAY_HTTP_RESPONSE_TIMEOUT_MS` | `32000` |
| 异步消费侧 block | `MODERATION_ASYNC_PROCESS_TIMEOUT_MS` | `35000` |
| PROCESSING 租约 | `MODERATION_ASYNC_PROCESSING_LEASE_MS` | `90000` |

- 百炼的 18s 来自当前 300 条实测的 P99 `16.37s`，预留约 1.6s；本地模型的 7s 覆盖实测 P99 `5.65s`。
- 故障转移最坏预算为 `18s(百炼) + 7s(本地) + 2s(调度余量) = 27s`。
- `MODEL_SERVICE_INFER_TIMEOUT_MS` 必须**小于**调用方预算，才能保证超时返回的是 model-service 自己那条带原因的 `REVIEW`，而不是被外层掐断。
- Gateway 需要再给同步调用至少 2s 的转发余量；消费侧 block 需要比异步调用多至少 5s；租约至少是 block 预算的 2 倍。
- `scripts/dev-local.sh start` 会先运行 `scripts/validate-timeout-budget.sh`；也可以单独执行该脚本检查 `.env`，脚本只读取预算值，不输出密钥。

部署差异值放在被 Git 忽略的 `infra/docker/.env`，可提交的默认值和说明放在 `application.yml`、`docker-compose.yml` 与 `.env.example`。这样切换模型或环境只改环境变量，代码中仍有安全默认值。

如果线上产品明确要求同步接口 6–10s 内返回，应把同步结果定义为 `PENDING/REVIEW` 的临时结果，再由异步接口提供最终判定；这种模式不能再要求同步/异步逐条决策完全一致。

## 告警验证
- 在 Prometheus 页面打开 `Alerts`，可查看规则状态与 firing 告警。
- 在 Grafana 的 `Moderation Async Overview` 中查看 `Firing Alerts` 面板。

## 链路追踪验证
- 在 Zipkin 页面按 `gateway-service` / `moderation-service` / `model-service` 检索 trace。
- 默认采样率由 `.env` 中 `TRACING_SAMPLING_PROBABILITY` 控制（开发环境建议 `1.0`）。
