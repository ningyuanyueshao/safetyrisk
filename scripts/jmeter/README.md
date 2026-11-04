# JMeter 压测脚本

本目录提供阶段一 Week4 的 JMeter 压测脚本。

## 文件说明

- `moderation-sync-check.jmx`：同步审核压测（`POST /api/v1/moderation/check`）
- `moderation-async-flow.jmx`：异步链路压测（`POST /check/async` + 轮询 `GET /tasks/{taskId}` 直到终态）
- `data/moderation_sync_payloads.csv`：基础同步压测样本
- `data/moderation_async_payloads.csv`：基础异步压测样本
- `data/moderation_sync_mock_scenarios.csv`：Mock L3 同步场景样本
- `data/moderation_async_mock_scenarios.csv`：Mock L3 异步场景样本

## Mock L3 压测前置准备

### 本地宿主机运行（推荐）

```bash
ENABLE_L3_MOCK=true ./scripts/dev-local.sh start
```

这会：
- 启动 `mock-bailian-service`（8089）
- 让 `model-service` 以 `l3-mock` profile 启动
- 将 L3 下游切到 `http://localhost:8089/compatible-mode/v1`

### Docker Compose 运行

```bash
MODEL_L3_PROVIDER=bailian MODEL_SERVICE_ACTIVE_PROFILE=l3-mock MODEL_L3_BAILIAN_BASE_URL=http://mock-bailian-service:8089/compatible-mode/v1 docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env --profile mock-l3 --profile observability up -d
```

如果要保留业务服务容器方式联调，可在 `.env` 中覆盖：
- `MODEL_SERVICE_ACTIVE_PROFILE=l3-mock`
- `MODEL_L3_PROVIDER=bailian`
- `MODEL_L3_BAILIAN_BASE_URL=http://mock-bailian-service:8089/compatible-mode/v1`
- `DASHSCOPE_API_KEY=mock-key`

## 非 GUI 执行示例

### 1) 同步接口压测（Mock L3）

```bash
jmeter -n \
  -t scripts/jmeter/moderation-sync-check.jmx \
  -Jhost=localhost -Jport=8080 -Jthreads=60 -JrampUp=20 -Jloops=10 \
  -JpayloadCsv=scripts/jmeter/data/moderation_sync_mock_scenarios.csv \
  -l /tmp/moderation-sync-mock.jtl \
  -e -o /tmp/moderation-sync-mock-report
```

### 2) 异步链路压测（Mock L3）

```bash
jmeter -n \
  -t scripts/jmeter/moderation-async-flow.jmx \
  -Jhost=localhost -Jport=8080 -Jthreads=20 -JrampUp=10 -Jloops=6 \
  -JpayloadCsv=scripts/jmeter/data/moderation_async_mock_scenarios.csv \
  -JpollSleepMs=500 -JmaxPolls=20 \
  -l /tmp/moderation-async-mock.jtl \
  -e -o /tmp/moderation-async-mock-report
```

### 3) 仅 NORMAL 场景（结果输出到项目目录）

先准备结果目录：

```bash
mkdir -p scripts/jmeter/results
```

同步：

```bash
jmeter -n \
  -t scripts/jmeter/moderation-sync-check.jmx \
  -Jhost=localhost -Jport=8080 -Jthreads=60 -JrampUp=20 -Jloops=10 \
  -JpayloadCsv=scripts/jmeter/data/moderation_sync_normal_only.csv \
  -l scripts/jmeter/results/moderation-sync-normal.jtl \
  -e -o scripts/jmeter/results/moderation-sync-normal-report
```

异步：

```bash
jmeter -n \
  -t scripts/jmeter/moderation-async-flow.jmx \
  -Jhost=localhost -Jport=8080 -Jthreads=20 -JrampUp=10 -Jloops=6 \
  -JpayloadCsv=scripts/jmeter/data/moderation_async_normal_only.csv \
  -JpollSleepMs=500 -JmaxPolls=20 \
  -l scripts/jmeter/results/moderation-async-normal.jtl \
  -e -o scripts/jmeter/results/moderation-async-normal-report
```

### 4) 一键运行四组压测（同步带异常、同步仅正常、异步带异常、异步仅正常）

```bash
./scripts/jmeter/run_all_four_tests.sh
```

可选传入运行 ID（用于结果目录名）：

```bash
./scripts/jmeter/run_all_four_tests.sh baseline-v1
```

脚本会按顺序执行：
- `sync-mock-all`（同步带异常）
- `sync-normal-only`（同步仅正常）
- `async-mock-all`（异步带异常）
- `async-normal-only`（异步仅正常）

并输出到：
- `scripts/jmeter/results/<运行ID>/*.jtl`
- `scripts/jmeter/results/<运行ID>/*-report/index.html`
- `scripts/jmeter/results/<运行ID>/*-summary-cn.md`

常用环境变量覆盖（可选）：
- `HOST` / `PORT` / `PROTOCOL`
- `SYNC_THREADS` / `SYNC_RAMP_UP` / `SYNC_LOOPS`
- `ASYNC_THREADS` / `ASYNC_RAMP_UP` / `ASYNC_LOOPS`
- `POLL_SLEEP_MS` / `MAX_POLLS`
- `CONNECT_TIMEOUT_MS` / `RESPONSE_TIMEOUT_MS`
- `JMETER_BIN` / `PYTHON_BIN`

### 5) 分层缓存性能基准（冷启动 vs Redis 命中 vs 本地命中）

如果你想专门验证缓存带来的性能提升，可使用：

```bash
./scripts/jmeter/run_cache_layers_benchmark.sh
```

脚本会按顺序执行三段：
- `cold_miss`：首次请求（预期缓存未命中）
- `redis_hit_expected`：等待本地缓存过期后再请求（预期 Redis 命中）
- `local_hit_expected`：紧接着再请求（预期本地缓存命中）

输出文件：
- `scripts/jmeter/results/cache-benchmark-<运行ID>/raw.csv`
- `scripts/jmeter/results/cache-benchmark-<运行ID>/summary.md`

可选参数（环境变量）：
- `BASE_URL`（默认 `http://localhost:8080/api/v1/moderation/check`）
- `SAMPLES`（每阶段样本数，默认 `80`）
- `LOCAL_EXPIRE_WAIT_SECONDS`（等待本地缓存过期秒数，默认 `32`）
- `CONNECT_TIMEOUT_SECONDS` / `MAX_TIME_SECONDS`
- `PYTHON_BIN`

示例：

```bash
SAMPLES=120 LOCAL_EXPIRE_WAIT_SECONDS=35 ./scripts/jmeter/run_cache_layers_benchmark.sh
```

说明：
- 该脚本使用固定 key 集合进行分阶段重复请求，第一阶段写入缓存，后两阶段复用同 key。
- 阶段统计会包含 `CACHE_HIT` 比例和 `Avg/P95/P99`，便于直接观察分层缓存收益。

异步排障（若 `/tasks/{taskId}` 出现大量 404）：

```bash
python3 - <<'PY'
import csv, sys
from collections import Counter
path = "scripts/jmeter/results/<运行ID>/async-mock-all.jtl"
counter = Counter()
with open(path, encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        label = r.get("label","")
        if "POST /api/v1/moderation/check/async" in label:
            counter[r.get("responseCode","")] += 1
print("POST /check/async 返回码分布:", dict(counter))
PY
```

若这里不是主要为 `200`，说明提交阶段已失败（常见为 Kafka/异步生产者不可用），轮询 404 只是后续表现。

## Mock 场景说明

同步/异步 Mock CSV 默认覆盖以下场景：
- `NORMAL`：固定成功响应，低延迟
- `EXTREME_LATENCY`：高延迟但仍在总超时以内
- `HTTP_429`：下游返回 429，观察 fallback 为 `REVIEW`
- `HTTP_500`：下游返回 500，观察 fallback 为 `REVIEW`
- `HTTP_503`：下游返回 503，观察 fallback 为 `REVIEW`
- `TIMEOUT`：下游延迟超过 `infer-timeout-ms`，观察总超时 fallback

## 关键实现点

- JMeter 会自动生成唯一 `X-Request-Id`
- JMeter 会在 `content` 里拼接 `__CACHE_BUSTER_<uuid>__`，避免 moderation 缓存和 async 去重干扰压测
- 同步脚本会断言：
  - HTTP 200
  - `decision` 符合预期
  - `reason` 包含预期关键字
- 异步脚本会：
  - 提交任务
  - 轮询到 `COMPLETED/FAILED` 或达到 `maxPolls`
  - 断言最终 `status` / `decision` / `reason`

## 常用参数

- `host/port`：目标网关地址
- `threads`：并发线程数
- `rampUp`：爬坡秒数
- `loops`：每线程循环次数
- `payloadCsv`：CSV 样本路径
- `pollSleepMs`：异步轮询间隔（毫秒）
- `maxPolls`：异步最大轮询次数

## 指标建议

关注 JMeter 报告里的：
- `Throughput`
- `Average / P95 / P99 latency`
- `Error %`

并结合 Grafana 的 `Moderation Ops Overview` 观察：
- `Sync Latency P95/P99`
- `Sync Decision Distribution`
- `Async enqueue/retry/dlq`
- `Async dedup hit`

注意：在当前实现里，429/500/503/timeout 很多会在 `model-service` 被吞成 `200 + REVIEW`，所以不要只盯 HTTP 5xx，要重点看 `REVIEW` 占比与尾延迟。

## 中文摘要脚本

如果你不想直接看英文 HTML 报告，可以用脚本把 `.jtl` 转成中文摘要（总览、P95/P99、吞吐、最慢接口、错误率、达标判断）。

建议先确保压测结果都输出在项目目录：

```bash
mkdir -p scripts/jmeter/results
```

同步结果生成中文摘要：

```bash
python3 scripts/jmeter/summarize_jtl_cn.py scripts/jmeter/results/moderation-sync-normal.jtl
```

异步结果生成中文摘要：

```bash
python3 scripts/jmeter/summarize_jtl_cn.py scripts/jmeter/results/moderation-async-normal.jtl
```

保存为文件：

```bash
python3 scripts/jmeter/summarize_jtl_cn.py \
  scripts/jmeter/results/moderation-sync-normal.jtl \
  -o scripts/jmeter/results/moderation-sync-normal-summary-cn.md
```

带达标阈值判断（示例）：

```bash
python3 scripts/jmeter/summarize_jtl_cn.py \
  scripts/jmeter/results/moderation-sync-normal.jtl \
  --target-p95-ms 800 \
  --target-p99-ms 1500 \
  --target-error-rate 1
```
