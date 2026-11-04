#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

JMETER_BIN="${JMETER_BIN:-jmeter}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST="${HOST:-localhost}"
PORT="${PORT:-8080}"
PROTOCOL="${PROTOCOL:-http}"
POLL_SLEEP_MS="${POLL_SLEEP_MS:-500}"
MAX_POLLS="${MAX_POLLS:-20}"
CONNECT_TIMEOUT_MS="${CONNECT_TIMEOUT_MS:-5000}"
RESPONSE_TIMEOUT_MS="${RESPONSE_TIMEOUT_MS:-40000}"

SYNC_THREADS="${SYNC_THREADS:-60}"
SYNC_RAMP_UP="${SYNC_RAMP_UP:-20}"
SYNC_LOOPS="${SYNC_LOOPS:-10}"

ASYNC_THREADS="${ASYNC_THREADS:-20}"
ASYNC_RAMP_UP="${ASYNC_RAMP_UP:-10}"
ASYNC_LOOPS="${ASYNC_LOOPS:-6}"

RUN_ID="${1:-$(date +"%Y%m%d-%H%M%S")}"
RESULT_DIR="${PROJECT_ROOT}/scripts/jmeter/results/${RUN_ID}"

if ! command -v "${JMETER_BIN}" >/dev/null 2>&1; then
  echo "未找到 jmeter 命令，请先安装 JMeter，或用 JMETER_BIN 指定路径。"
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "未找到 python3 命令，请先安装 Python 3，或用 PYTHON_BIN 指定路径。"
  exit 1
fi

mkdir -p "${RESULT_DIR}"

run_sync_case() {
  local case_name="$1"
  local payload_csv="$2"
  local jtl_path="${RESULT_DIR}/${case_name}.jtl"
  local report_dir="${RESULT_DIR}/${case_name}-report"
  local summary_md="${RESULT_DIR}/${case_name}-summary-cn.md"

  echo ""
  echo "==== 运行 ${case_name} ===="
  "${JMETER_BIN}" -n \
    -t "${PROJECT_ROOT}/scripts/jmeter/moderation-sync-check.jmx" \
    -Jhost="${HOST}" -Jport="${PORT}" -Jprotocol="${PROTOCOL}" \
    -Jthreads="${SYNC_THREADS}" -JrampUp="${SYNC_RAMP_UP}" -Jloops="${SYNC_LOOPS}" \
    -JconnectTimeoutMs="${CONNECT_TIMEOUT_MS}" -JresponseTimeoutMs="${RESPONSE_TIMEOUT_MS}" \
    -JpayloadCsv="${PROJECT_ROOT}/${payload_csv}" \
    -l "${jtl_path}" \
    -e -o "${report_dir}"

  "${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/jmeter/summarize_jtl_cn.py" \
    "${jtl_path}" \
    -o "${summary_md}"
}

run_async_case() {
  local case_name="$1"
  local payload_csv="$2"
  local jtl_path="${RESULT_DIR}/${case_name}.jtl"
  local report_dir="${RESULT_DIR}/${case_name}-report"
  local summary_md="${RESULT_DIR}/${case_name}-summary-cn.md"

  echo ""
  echo "==== 运行 ${case_name} ===="
  "${JMETER_BIN}" -n \
    -t "${PROJECT_ROOT}/scripts/jmeter/moderation-async-flow.jmx" \
    -Jhost="${HOST}" -Jport="${PORT}" -Jprotocol="${PROTOCOL}" \
    -Jthreads="${ASYNC_THREADS}" -JrampUp="${ASYNC_RAMP_UP}" -Jloops="${ASYNC_LOOPS}" \
    -JconnectTimeoutMs="${CONNECT_TIMEOUT_MS}" -JresponseTimeoutMs="${RESPONSE_TIMEOUT_MS}" \
    -JpayloadCsv="${PROJECT_ROOT}/${payload_csv}" \
    -JpollSleepMs="${POLL_SLEEP_MS}" -JmaxPolls="${MAX_POLLS}" \
    -l "${jtl_path}" \
    -e -o "${report_dir}"

  "${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/jmeter/summarize_jtl_cn.py" \
    "${jtl_path}" \
    -o "${summary_md}"
}

echo "输出目录：${RESULT_DIR}"

run_sync_case "sync-mock-all" "scripts/jmeter/data/moderation_sync_mock_scenarios.csv"
run_sync_case "sync-normal-only" "scripts/jmeter/data/moderation_sync_normal_only.csv"
run_async_case "async-mock-all" "scripts/jmeter/data/moderation_async_mock_scenarios.csv"
run_async_case "async-normal-only" "scripts/jmeter/data/moderation_async_normal_only.csv"

echo ""
echo "四组压测全部完成。结果如下："
echo "- JTL: ${RESULT_DIR}/*.jtl"
echo "- HTML 报告: ${RESULT_DIR}/*-report/index.html"
echo "- 中文摘要: ${RESULT_DIR}/*-summary-cn.md"
