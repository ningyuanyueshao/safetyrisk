# 阶段二评测脚本

这个目录用于沉淀阶段二的离线评测能力，先把“数据集 -> 接口调用 -> 指标汇总 -> 实验归档”这条链路跑通。冻结的 300 条数据可由 L2 与完整链路共用；本地图片会转换为 `imageData`，所以 L2 与 L3 看到的是同一批图片。

## 脚本

- `run_evaluation.py`（统一入口，兼容实现仍位于 `run_l3_evaluation.py`）
  - `--scope l2`：直接调用 model-service 的 L2-only 接口，不调用 L3
  - `--scope l3`：直接调用配置的 L3 provider，不经过 L2
  - `--scope pipeline`：运行包含 L1/L2/L3 的完整链路
  - 统一选择 L3 路由：`bailian`（纯百炼）/ `local`（纯本地）/ `mixed`（百炼失败后切本地）
  - 统一选择接口：`sync` / `async`
  - 自动做预算校验、所需 provider 预检、服务重启和健康检查
  - 每次运行使用独立请求 namespace，避免命中旧 Redis 缓存或异步 MySQL 去重任务
  - 自动归档结果和不含密钥的 `run_config.json`
- `evaluate_moderation_dataset.py`
  - 读取 `jsonl` 评测集
  - 调用同步/模型接口，或提交异步任务并轮询到终态
  - 统计准确率、各标签 precision/recall/f1、宏平均 F1、延迟和混淆矩阵
  - 按 `contentType`、`scene`、`category` 聚合结果
  - 对带 `expectedViolation` 的样本统计二分类指标、expected `REJECT` 漏判和 PASS 误报
  - 支持可选质量门禁，适合接入 CI
  - 可选输出 `summary.json`、`report.md`、`predictions.jsonl`

## 快速开始

### 一次测完 L2、L3 和端到端链路

`run_full_evaluation.py` 一次运行会依次产生：

1. L2-only：绕过 L3，统计 L2 路由覆盖率和拦截贡献。
2. L3-only：绕过 L2，统计所选 L3 provider 的独立模型质量。
3. Pipeline：按所选同步/异步接口统计 L1 + L2 + L3 的最终系统质量。

例如完整评测混合 L3 的同步链路：

```bash
python3 scripts/eval/run_full_evaluation.py --provider mixed --mode sync
```

首次运行或代码变化后加 `--build`。若要遍历纯百炼、纯本地、混合以及同步、异步全部组合：

```bash
python3 scripts/eval/run_full_evaluation.py --provider all --mode all --build
```

后一条命令会运行 10 个任务（1 个 L2-only、3 个 L3-only、6 个 Pipeline）；其中百炼和混合任务会把数据发送到百炼，并产生相应调用费用。汇总报告写入 `experiments/phase2/full-suite/<run-id>/report.md`，每个子任务同时保留自己的完整报告与逐条预测。

### 单项评测

L2 独立评测命令：

```bash
python3 scripts/eval/run_evaluation.py --scope l2 --mode sync --build
```

L2 的原始 `PASS_TO_L3` 会保留并用于覆盖率、终止准确率和拒绝贡献统计；仅在与共享数据集的三分类标签计算基线 Accuracy/Macro-F1 时投影为 `PASS`。

完整链路的六种组合只需改变 provider 和 mode：

```bash
# 先校验数据和执行计划，不重启服务、不调用模型
python3 scripts/eval/run_evaluation.py --scope pipeline --provider mixed --mode sync --dry-run

# 纯百炼：同步 / 异步
python3 scripts/eval/run_evaluation.py --scope pipeline --provider bailian --mode sync
python3 scripts/eval/run_evaluation.py --scope pipeline --provider bailian --mode async

# 纯本地 Ollama：同步 / 异步
python3 scripts/eval/run_evaluation.py --scope pipeline --provider local --mode sync
python3 scripts/eval/run_evaluation.py --scope pipeline --provider local --mode async

# 混合故障转移（百炼 -> 本地）：同步 / 异步
python3 scripts/eval/run_evaluation.py --scope pipeline --provider mixed --mode sync
python3 scripts/eval/run_evaluation.py --scope pipeline --provider mixed --mode async
```

默认使用冻结集 `datasets/l3/eval/l3_eval_frozen_v1.jsonl` 和图片目录 `datasets/l3/eval/assets`，结果写入 `experiments/phase2/gateway-l3/<时间>-<provider>-<mode>/`。这里的“纯百炼/纯本地/混合”只控制 L3 路由，Gateway 中的 L1/L2 仍按系统配置执行；若要隔离评测 L3 模型本身，继续直接调用 model-service 的同步接口。`bailian` 与 `mixed` 会把数据发送给百炼；`local` 不会。默认只用已有镜像重建三个应用容器，源码或依赖变化后可显式加 `--build`。

快速抽样示例：

```bash
python3 scripts/eval/run_evaluation.py \
  --scope pipeline \
  --provider mixed \
  --mode async \
  --max-samples 10 \
  --run-id smoke-mixed-async
```

如果服务已按目标 provider 启动，可加 `--no-restart`；此时脚本无法替你确认运行中容器的 provider 是否与参数一致。完整参数见：

```bash
python3 scripts/eval/run_evaluation.py --help
```

正式跑 300 条前，先对两路 L3 provider 发低成本探针：

```bash
DASHSCOPE_API_KEY=你的百炼Key \
MODEL_L3_BAILIAN_MODEL=qwen3.8-flash \
MODEL_L3_VLLM_BASE_URL=http://127.0.0.1:11434/v1 \
MODEL_L3_VLLM_MODEL=qwen3.5:0.8b \
MODEL_L3_VLLM_REASONING_EFFORT=none \
python3 scripts/eval/preflight_l3_providers.py --provider both
```

脚本不会输出 API Key，也兼容 `BAILIAN_API_KEY`。`--provider bailian|local|both` 可只检查计划使用的 provider；`both` 任一路未完成有效响应都会非零退出。旧参数 `--require-both` 仍兼容。

先做数据校验：

```bash
python3 scripts/eval/evaluate_moderation_dataset.py \
  --input datasets/eval/moderation_eval.sample.jsonl \
  --dry-run
```

跑当前网关基线：

```bash
python3 scripts/eval/evaluate_moderation_dataset.py \
  --input datasets/eval/moderation_eval.sample.jsonl \
  --url http://localhost:8080/api/v1/moderation/check \
  --output-dir experiments/phase2/baseline-api/20260425-gateway-baseline
```

只评测模型服务：

```bash
python3 scripts/eval/evaluate_moderation_dataset.py \
  --input datasets/eval/moderation_eval.sample.jsonl \
  --url http://localhost:8082/api/v1/model/classify \
  --output-dir experiments/phase2/local-l3/20260425-model-baseline
```

异步提交并轮询最终结果：

```bash
python3 scripts/eval/evaluate_moderation_dataset.py \
  --mode async \
  --input datasets/l3/eval/l3_eval_frozen_v1.jsonl \
  --require-frozen \
  --url http://localhost:8080/api/v1/moderation/check/async \
  --task-url-template 'http://localhost:8080/api/v1/moderation/tasks/{taskId}' \
  --output-dir experiments/phase2/baseline-api/20260425-gateway-async
```

质量门禁示例（阈值应由业务根据正式 Gold Dataset 确定）：

```bash
python3 scripts/eval/evaluate_moderation_dataset.py \
  --input datasets/l3/eval/l3_eval_frozen_v1.jsonl \
  --url http://localhost:8080/api/v1/moderation/check \
  --require-frozen \
  --min-accuracy 0.90 \
  --min-macro-f1 0.85 \
  --min-reject-recall 0.95 \
  --max-risky-pass-rate 0.01 \
  --max-review-rate 0.30 \
  --enforce-quality-gate
```

## 输入格式

最小字段：

- `id`
- `contentType`
- `expectedDecision`
- 按 `contentType` 提供 `content`，或 `imageUrl` / `imagePath` / `imageData` 图片来源

可选字段：

- `userId`
- `imagePath`：显式的本地资源路径；现有冻结集为兼容旧格式，将本地路径保存在 `imageUrl`
- `imageData`：可直接提供的纯 Base64/data URL；逐条预测输出中只保留长度摘要
- `scene`
- `category`
- `expectedViolation`
- `source`
- `notes`

评测脚本只把 `expectedDecision` 作为三分类 Gold Label；`expectedReason` 不做自然语言全文相等比较。若需要自动评价理由，建议在接口中增加稳定的 `reasonCode` 或 `category` 字段。

## 结果归档建议

每次实验输出一个独立目录，建议命名：

```text
experiments/phase2/<track>/YYYYMMDD-<short-name>/
```

目录内保留：

- `summary.json`
- `report.md`
- `predictions.jsonl`
- 本次实验使用的提示词或配置快照

正式评测前应确保图片真实可访问，并关闭或隔离审核缓存，避免缓存命中掩盖模型调用结果。统一入口通过给原本没有 `userId` 的样本加入每次运行独立的评测 namespace，隔离缓存和异步去重；不会向 Gold 样本正文追加 cache-buster，因此不改变送给模型的文本/图片。数据集本身带 `userId` 的样本会保留原值，脚本会提示这部分可能复用历史异步任务。
