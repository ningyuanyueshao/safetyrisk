#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

BASE_URL="${BASE_URL:-http://localhost:8080/api/v1/moderation/check}"
SAMPLES="${SAMPLES:-80}"
LOCAL_EXPIRE_WAIT_SECONDS="${LOCAL_EXPIRE_WAIT_SECONDS:-32}"
CONNECT_TIMEOUT_SECONDS="${CONNECT_TIMEOUT_SECONDS:-5}"
MAX_TIME_SECONDS="${MAX_TIME_SECONDS:-20}"
USER_ID_PREFIX="${USER_ID_PREFIX:-cache-bench-user}"
SCENARIO_MARKER="${SCENARIO_MARKER:-__MOCK_SCENARIO_NORMAL__}"

RUN_ID="${1:-$(date +"%Y%m%d-%H%M%S")}"
RESULT_DIR="${PROJECT_ROOT}/scripts/jmeter/results/cache-benchmark-${RUN_ID}"
RAW_CSV="${RESULT_DIR}/raw.csv"
SUMMARY_MD="${RESULT_DIR}/summary.md"

if ! command -v curl >/dev/null 2>&1; then
  echo "未找到 curl 命令，请先安装。"
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "未找到 ${PYTHON_BIN} 命令，请先安装 Python 3，或用 PYTHON_BIN 指定路径。"
  exit 1
fi

if ! [[ "${SAMPLES}" =~ ^[0-9]+$ ]] || [ "${SAMPLES}" -le 0 ]; then
  echo "SAMPLES 必须是正整数，当前值: ${SAMPLES}"
  exit 1
fi

mkdir -p "${RESULT_DIR}"
echo "phase,sample,latency_ms,http_code,cache_hit" > "${RAW_CSV}"

request_once() {
  local phase="$1"
  local idx="$2"
  local key="$3"

  local request_id
  request_id="cache-bench-${RUN_ID}-${phase}-${idx}-$(date +%s%N)"

  local content
  content="缓存基准 ${SCENARIO_MARKER} KEY=${key}"

  local payload
  payload=$(printf '{"contentType":"TEXT","content":"%s","imageUrl":"","userId":"%s-%04d"}' \
    "${content}" "${USER_ID_PREFIX}" "${idx}")

  local curl_output
  curl_output=$(curl -sS \
    --connect-timeout "${CONNECT_TIMEOUT_SECONDS}" \
    --max-time "${MAX_TIME_SECONDS}" \
    -X POST "${BASE_URL}" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json' \
    -H "X-Request-Id: ${request_id}" \
    -d "${payload}" \
    -w $'\n__HTTP_CODE__:%{http_code}\n__TIME_TOTAL__:%{time_total}\n')

  local http_code
  http_code=$(printf '%s\n' "${curl_output}" | sed -n 's/^__HTTP_CODE__://p' | tail -n 1)

  local time_total
  time_total=$(printf '%s\n' "${curl_output}" | sed -n 's/^__TIME_TOTAL__://p' | tail -n 1)

  local body
  body=$(printf '%s\n' "${curl_output}" | sed '/^__HTTP_CODE__:/,$d')

  local cache_hit=0
  if printf '%s' "${body}" | grep -q '\[CACHE_HIT\]'; then
    cache_hit=1
  fi

  local latency_ms
  latency_ms=$(awk -v t="${time_total:-0}" 'BEGIN { printf "%.3f", t * 1000.0 }')

  echo "${phase},${idx},${latency_ms},${http_code:-0},${cache_hit}" >> "${RAW_CSV}"
}

run_phase() {
  local phase="$1"
  shift
  local keys=("$@")

  echo ""
  echo "==== 运行 ${phase}，样本数=${#keys[@]} ===="

  local i=1
  for key in "${keys[@]}"; do
    request_once "${phase}" "${i}" "${key}"
    i=$((i + 1))
  done
}

echo "输出目录：${RESULT_DIR}"

declare -a KEYS=()
for i in $(seq 1 "${SAMPLES}"); do
  KEYS+=("cache-key-${RUN_ID}-$(printf '%04d' "${i}")")
done

run_phase "cold_miss" "${KEYS[@]}"

echo ""
echo "==== 等待本地缓存过期 ${LOCAL_EXPIRE_WAIT_SECONDS}s（Redis 仍应有效） ===="
sleep "${LOCAL_EXPIRE_WAIT_SECONDS}"

run_phase "redis_hit_expected" "${KEYS[@]}"
run_phase "local_hit_expected" "${KEYS[@]}"

"${PYTHON_BIN}" - "${RAW_CSV}" "${SUMMARY_MD}" <<'PY'
import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

raw_csv = Path(sys.argv[1])
summary_md = Path(sys.argv[2])

rows = []
with raw_csv.open(encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

phase_data = defaultdict(list)
for r in rows:
    phase_data[r["phase"]].append(r)

order = ["cold_miss", "redis_hit_expected", "local_hit_expected"]

def percentile(values, p):
    if not values:
        return 0.0
    arr = sorted(values)
    k = math.ceil((p / 100.0) * len(arr)) - 1
    k = max(0, min(k, len(arr) - 1))
    return arr[k]

lines = []
lines.append("# 缓存分层基准摘要")
lines.append("")
lines.append("## 结果")
for phase in order:
    items = phase_data.get(phase, [])
    if not items:
        lines.append(f"- {phase}: 无数据")
        continue

    latencies = [float(x["latency_ms"]) for x in items]
    code_200 = sum(1 for x in items if str(x["http_code"]) == "200")
    cache_hits = sum(1 for x in items if str(x["cache_hit"]) == "1")

    avg = statistics.fmean(latencies)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    hit_ratio = (cache_hits / len(items)) * 100.0

    lines.append(
        f"- {phase}: 样本={len(items)}, HTTP200={code_200}, "
        f"Avg={avg:.2f}ms, P95={p95:.2f}ms, P99={p99:.2f}ms, CACHE_HIT={hit_ratio:.2f}%"
    )

lines.append("")
lines.append("## 判读建议")
lines.append("- cold_miss：应接近 0% CACHE_HIT，用于基线。")
lines.append("- redis_hit_expected：本地缓存过期后，理论上应高 CACHE_HIT，且时延显著低于 cold_miss。")
lines.append("- local_hit_expected：紧接上一阶段，理论上仍高 CACHE_HIT，且时延不高于 redis_hit_expected。")

summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
PY

echo ""
echo "完成。"
echo "- 原始明细: ${RAW_CSV}"
echo "- 摘要报告: ${SUMMARY_MD}"
