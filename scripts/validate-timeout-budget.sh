#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${REPO_ROOT}/infra/docker/.env}"

# Read only simple KEY=VALUE entries. Explicit caller environment always wins.
if [[ -f "${ENV_FILE}" ]]; then
  while IFS= read -r env_line || [[ -n "${env_line}" ]]; do
    [[ -z "${env_line}" || "${env_line}" == \#* ]] && continue
    if [[ "${env_line}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      env_key="${env_line%%=*}"
      if [[ -z "${!env_key+x}" ]]; then
        export "${env_line}"
      fi
    fi
  done < "${ENV_FILE}"
fi

MODEL_L3_BAILIAN_TIMEOUT_MS="${MODEL_L3_BAILIAN_TIMEOUT_MS:-18000}"
MODEL_L3_VLLM_TIMEOUT_MS="${MODEL_L3_VLLM_TIMEOUT_MS:-7000}"
MODEL_SERVICE_INFER_TIMEOUT_MS="${MODEL_SERVICE_INFER_TIMEOUT_MS:-27000}"
MODERATION_MODEL_SERVICE_TIMEOUT_MS="${MODERATION_MODEL_SERVICE_TIMEOUT_MS:-30000}"
MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS="${MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS:-30000}"
MODERATION_ASYNC_PROCESS_TIMEOUT_MS="${MODERATION_ASYNC_PROCESS_TIMEOUT_MS:-35000}"
MODERATION_ASYNC_PROCESSING_LEASE_MS="${MODERATION_ASYNC_PROCESSING_LEASE_MS:-90000}"
GATEWAY_HTTP_RESPONSE_TIMEOUT_MS="${GATEWAY_HTTP_RESPONSE_TIMEOUT_MS:-32000}"

budget_names=(
  MODEL_L3_BAILIAN_TIMEOUT_MS
  MODEL_L3_VLLM_TIMEOUT_MS
  MODEL_SERVICE_INFER_TIMEOUT_MS
  MODERATION_MODEL_SERVICE_TIMEOUT_MS
  MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS
  MODERATION_ASYNC_PROCESS_TIMEOUT_MS
  MODERATION_ASYNC_PROCESSING_LEASE_MS
  GATEWAY_HTTP_RESPONSE_TIMEOUT_MS
)

for budget_name in "${budget_names[@]}"; do
  budget_value="${!budget_name}"
  if [[ ! "${budget_value}" =~ ^[1-9][0-9]*$ ]]; then
    echo "[timeout-budget] ${budget_name} must be a positive integer in milliseconds; got '${budget_value}'." >&2
    exit 1
  fi
done

provider_chain_min=$((MODEL_L3_BAILIAN_TIMEOUT_MS + MODEL_L3_VLLM_TIMEOUT_MS + 2000))
if (( MODEL_SERVICE_INFER_TIMEOUT_MS < provider_chain_min )); then
  echo "[timeout-budget] MODEL_SERVICE_INFER_TIMEOUT_MS must be >= provider timeouts + 2000ms (${provider_chain_min}ms)." >&2
  exit 1
fi

moderation_min=$((MODEL_SERVICE_INFER_TIMEOUT_MS + 2000))
if (( MODERATION_MODEL_SERVICE_TIMEOUT_MS < moderation_min )); then
  echo "[timeout-budget] MODERATION_MODEL_SERVICE_TIMEOUT_MS must be >= ${moderation_min}ms." >&2
  exit 1
fi
if (( MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS < moderation_min )); then
  echo "[timeout-budget] MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS must be >= ${moderation_min}ms." >&2
  exit 1
fi

gateway_min=$((MODERATION_MODEL_SERVICE_TIMEOUT_MS + 2000))
if (( GATEWAY_HTTP_RESPONSE_TIMEOUT_MS < gateway_min )); then
  echo "[timeout-budget] GATEWAY_HTTP_RESPONSE_TIMEOUT_MS must be >= ${gateway_min}ms." >&2
  exit 1
fi

process_min=$((MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS + 5000))
if (( MODERATION_ASYNC_PROCESS_TIMEOUT_MS < process_min )); then
  echo "[timeout-budget] MODERATION_ASYNC_PROCESS_TIMEOUT_MS must be >= ${process_min}ms." >&2
  exit 1
fi

lease_min=$((MODERATION_ASYNC_PROCESS_TIMEOUT_MS * 2))
if (( MODERATION_ASYNC_PROCESSING_LEASE_MS < lease_min )); then
  echo "[timeout-budget] MODERATION_ASYNC_PROCESSING_LEASE_MS must be >= ${lease_min}ms." >&2
  exit 1
fi

echo "[timeout-budget] OK: providers ${MODEL_L3_BAILIAN_TIMEOUT_MS}ms/${MODEL_L3_VLLM_TIMEOUT_MS}ms -> model ${MODEL_SERVICE_INFER_TIMEOUT_MS}ms -> moderation ${MODERATION_MODEL_SERVICE_TIMEOUT_MS}ms/${MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS}ms -> gateway ${GATEWAY_HTTP_RESPONSE_TIMEOUT_MS}ms / worker ${MODERATION_ASYNC_PROCESS_TIMEOUT_MS}ms -> lease ${MODERATION_ASYNC_PROCESSING_LEASE_MS}ms."
