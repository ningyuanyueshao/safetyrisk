#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/infra/docker/docker-compose.yml"
ENV_FILE="${REPO_ROOT}/infra/docker/.env"
LOG_DIR="${REPO_ROOT}/.dev/logs"
PID_DIR="${REPO_ROOT}/.dev/pids"

# Load simple KEY=VALUE entries from the project env file without overriding
# values explicitly supplied by the caller.
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

ENABLE_L3_MOCK="${ENABLE_L3_MOCK:-false}"
MODEL_L3_PROVIDER="${MODEL_L3_PROVIDER:-}"
DASHSCOPE_API_KEY="${DASHSCOPE_API_KEY:-${BAILIAN_API_KEY:-}}"
MODEL_SERVICE_ACTIVE_PROFILE="${MODEL_SERVICE_ACTIVE_PROFILE:-}"
MODEL_L3_BAILIAN_BASE_URL="${MODEL_L3_BAILIAN_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}"
MODEL_L3_BAILIAN_MODEL="${MODEL_L3_BAILIAN_MODEL:-qwen3.8-flash}"
MODEL_L3_BAILIAN_TIMEOUT_MS="${MODEL_L3_BAILIAN_TIMEOUT_MS:-18000}"
MODEL_L3_VLLM_BASE_URL="${MODEL_L3_VLLM_BASE_URL:-http://localhost:11434/v1}"
MODEL_L3_VLLM_MODEL="${MODEL_L3_VLLM_MODEL:-qwen3.5:0.8b}"
MODEL_L3_VLLM_REASONING_EFFORT="${MODEL_L3_VLLM_REASONING_EFFORT:-none}"
MODEL_L3_VLLM_TIMEOUT_MS="${MODEL_L3_VLLM_TIMEOUT_MS:-7000}"
MODEL_SERVICE_INFER_TIMEOUT_MS="${MODEL_SERVICE_INFER_TIMEOUT_MS:-27000}"
MODEL_SERVICE_L3_CIRCUIT_FAILURE_THRESHOLD="${MODEL_SERVICE_L3_CIRCUIT_FAILURE_THRESHOLD:-5}"
MODEL_SERVICE_L3_CIRCUIT_OPEN_MS="${MODEL_SERVICE_L3_CIRCUIT_OPEN_MS:-15000}"
MOCK_BAILIAN_NORMAL_LATENCY_MS="${MOCK_BAILIAN_NORMAL_LATENCY_MS:-100}"
MOCK_BAILIAN_EXTREME_LATENCY_MS="${MOCK_BAILIAN_EXTREME_LATENCY_MS:-3800}"
MOCK_BAILIAN_TIMEOUT_LATENCY_MS="${MOCK_BAILIAN_TIMEOUT_LATENCY_MS:-7000}"
# 严格一致性预算（需保持阶梯关系，见 infra/docker/README.md）：
MODERATION_MODEL_SERVICE_TIMEOUT_MS="${MODERATION_MODEL_SERVICE_TIMEOUT_MS:-30000}"
MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS="${MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS:-30000}"
MODERATION_ASYNC_ENQUEUE_TIMEOUT_MS="${MODERATION_ASYNC_ENQUEUE_TIMEOUT_MS:-5000}"
MODERATION_ASYNC_PROCESS_TIMEOUT_MS="${MODERATION_ASYNC_PROCESS_TIMEOUT_MS:-35000}"
MODERATION_ASYNC_MAX_RETRIES="${MODERATION_ASYNC_MAX_RETRIES:-2}"
MODERATION_ASYNC_RETRY_BACKOFF_MS="${MODERATION_ASYNC_RETRY_BACKOFF_MS:-1000}"
MODERATION_ASYNC_PROCESSING_LEASE_MS="${MODERATION_ASYNC_PROCESSING_LEASE_MS:-90000}"
GATEWAY_HTTP_CONNECT_TIMEOUT_MS="${GATEWAY_HTTP_CONNECT_TIMEOUT_MS:-3000}"
GATEWAY_HTTP_RESPONSE_TIMEOUT_MS="${GATEWAY_HTTP_RESPONSE_TIMEOUT_MS:-32000}"

# 本地 Java 进程运行在宿主机上，依赖容器通过端口映射暴露到 localhost。
LOCAL_ZIPKIN_ENDPOINT="http://localhost:9411/api/v2/spans"
LOCAL_TRACING_SAMPLING_PROBABILITY="${TRACING_SAMPLING_PROBABILITY:-1.0}"
LOCAL_REDIS_HOST="localhost"
LOCAL_REDIS_PORT="6379"
LOCAL_MYSQL_URL="jdbc:mysql://localhost:3306/${MYSQL_DATABASE:-moderation}"
LOCAL_MYSQL_USERNAME="${MYSQL_USER:-moderation}"
LOCAL_MYSQL_PASSWORD="${MYSQL_PASSWORD:-moderation}"
LOCAL_KAFKA_BOOTSTRAP_SERVERS="localhost:29092"

ALL_LOCAL_SERVICES=("moderation-service" "model-service" "gateway-service" "mock-bailian-service")

mkdir -p "${LOG_DIR}" "${PID_DIR}"

service_pid_file() {
  echo "${PID_DIR}/$1.pid"
}

is_mock_enabled() {
  [[ "${ENABLE_L3_MOCK}" == "true" ]]
}

is_running() {
  local service="$1"
  local pid_file
  pid_file="$(service_pid_file "${service}")"

  if [[ -f "${pid_file}" ]]; then
    local pid
    pid="$(cat "${pid_file}")"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      return 0
    fi
    rm -f "${pid_file}"
  fi
  return 1
}

start_deps() {
  echo "[dev-local] Starting dependency containers (including observability)..."
  local -a compose_args=(docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}")
  compose_args+=(--profile observability up -d)
  (cd "${REPO_ROOT}" && "${compose_args[@]}")

  echo "[dev-local] Waiting for dependencies to be healthy..."
  local max_wait=60
  local elapsed=0
  while [[ ${elapsed} -lt ${max_wait} ]]; do
    local mysql_healthy=$(docker inspect --format='{{.State.Health.Status}}' msr-mysql 2>/dev/null || echo "starting")
    local redis_healthy=$(docker inspect --format='{{.State.Health.Status}}' msr-redis 2>/dev/null || echo "starting")
    local zipkin_healthy=$(docker inspect --format='{{.State.Health.Status}}' msr-zipkin 2>/dev/null || echo "starting")

    if [[ "${mysql_healthy}" == "healthy" ]] && [[ "${redis_healthy}" == "healthy" ]] && [[ "${zipkin_healthy}" == "healthy" ]]; then
      echo "[dev-local] All dependencies are healthy"
      return 0
    fi

    echo "[dev-local] Waiting... (MySQL: ${mysql_healthy}, Redis: ${redis_healthy}, Zipkin: ${zipkin_healthy})"
    sleep 2
    elapsed=$((elapsed + 2))
  done

  echo "[dev-local] Warning: Dependencies may not be fully ready after ${max_wait}s"
}

start_service() {
  local service="$1"
  local log_file="${LOG_DIR}/${service}.log"
  local pid_file
  pid_file="$(service_pid_file "${service}")"

  if is_running "${service}"; then
    echo "[dev-local] ${service} already running (pid=$(cat "${pid_file}"))"
    return 0
  fi

  echo "[dev-local] Starting ${service} ..."
  (
    cd "${REPO_ROOT}/${service}"

    local -a env_args=(
      "MANAGEMENT_ZIPKIN_TRACING_ENDPOINT=${LOCAL_ZIPKIN_ENDPOINT}"
      "MANAGEMENT_TRACING_SAMPLING_PROBABILITY=${LOCAL_TRACING_SAMPLING_PROBABILITY}"
    )

    case "${service}" in
      moderation-service)
        env_args+=(
          "SPRING_DATA_REDIS_HOST=${LOCAL_REDIS_HOST}"
          "SPRING_DATA_REDIS_PORT=${LOCAL_REDIS_PORT}"
          "SPRING_DATASOURCE_URL=${LOCAL_MYSQL_URL}"
          "SPRING_DATASOURCE_USERNAME=${LOCAL_MYSQL_USERNAME}"
          "SPRING_DATASOURCE_PASSWORD=${LOCAL_MYSQL_PASSWORD}"
          "SPRING_KAFKA_BOOTSTRAP_SERVERS=${LOCAL_KAFKA_BOOTSTRAP_SERVERS}"
          "MODEL_SERVICE_BASE_URL=http://localhost:8082"
          "MODERATION_MODEL_SERVICE_TIMEOUT_MS=${MODERATION_MODEL_SERVICE_TIMEOUT_MS}"
          "MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS=${MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS}"
          "MODERATION_ASYNC_ENQUEUE_TIMEOUT_MS=${MODERATION_ASYNC_ENQUEUE_TIMEOUT_MS}"
          "MODERATION_ASYNC_PROCESS_TIMEOUT_MS=${MODERATION_ASYNC_PROCESS_TIMEOUT_MS}"
          "MODERATION_ASYNC_MAX_RETRIES=${MODERATION_ASYNC_MAX_RETRIES}"
          "MODERATION_ASYNC_RETRY_BACKOFF_MS=${MODERATION_ASYNC_RETRY_BACKOFF_MS}"
          "MODERATION_ASYNC_PROCESSING_LEASE_MS=${MODERATION_ASYNC_PROCESSING_LEASE_MS}"
        )
        ;;
      model-service)
        if [[ -n "${MODEL_L3_PROVIDER}" ]]; then
          env_args+=("MODEL_L3_PROVIDER=${MODEL_L3_PROVIDER}")
        elif is_mock_enabled; then
          env_args+=("MODEL_L3_PROVIDER=bailian")
        fi

        if is_mock_enabled; then
          env_args+=(
            "SPRING_PROFILES_ACTIVE=${MODEL_SERVICE_ACTIVE_PROFILE:-l3-mock}"
            "DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY:-mock-key}"
            "MODEL_L3_BAILIAN_BASE_URL=${MODEL_L3_BAILIAN_BASE_URL:-http://localhost:8089/compatible-mode/v1}"
            "MODEL_L3_BAILIAN_MODEL=${MODEL_L3_BAILIAN_MODEL}"
            "MODEL_L3_BAILIAN_TIMEOUT_MS=${MODEL_L3_BAILIAN_TIMEOUT_MS}"
            "MODEL_SERVICE_INFER_TIMEOUT_MS=${MODEL_SERVICE_INFER_TIMEOUT_MS}"
            "MODEL_SERVICE_L3_CIRCUIT_FAILURE_THRESHOLD=${MODEL_SERVICE_L3_CIRCUIT_FAILURE_THRESHOLD}"
            "MODEL_SERVICE_L3_CIRCUIT_OPEN_MS=${MODEL_SERVICE_L3_CIRCUIT_OPEN_MS}"
          )
        else
          env_args+=(
            "DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY}"
            "MODEL_L3_BAILIAN_BASE_URL=${MODEL_L3_BAILIAN_BASE_URL}"
            "MODEL_L3_BAILIAN_MODEL=${MODEL_L3_BAILIAN_MODEL}"
            "MODEL_L3_BAILIAN_TIMEOUT_MS=${MODEL_L3_BAILIAN_TIMEOUT_MS}"
            "MODEL_SERVICE_INFER_TIMEOUT_MS=${MODEL_SERVICE_INFER_TIMEOUT_MS}"
            "MODEL_SERVICE_L3_CIRCUIT_FAILURE_THRESHOLD=${MODEL_SERVICE_L3_CIRCUIT_FAILURE_THRESHOLD}"
            "MODEL_SERVICE_L3_CIRCUIT_OPEN_MS=${MODEL_SERVICE_L3_CIRCUIT_OPEN_MS}"
          )
        fi

        if [[ "${MODEL_L3_PROVIDER}" != "mock" ]]; then
          env_args+=(
            "MODEL_L3_VLLM_BASE_URL=${MODEL_L3_VLLM_BASE_URL}"
            "MODEL_L3_VLLM_MODEL=${MODEL_L3_VLLM_MODEL}"
            "MODEL_L3_VLLM_REASONING_EFFORT=${MODEL_L3_VLLM_REASONING_EFFORT}"
            "MODEL_L3_VLLM_TIMEOUT_MS=${MODEL_L3_VLLM_TIMEOUT_MS}"
          )
        fi
        ;;
      mock-bailian-service)
        env_args+=(
          "MOCK_BAILIAN_NORMAL_LATENCY_MS=${MOCK_BAILIAN_NORMAL_LATENCY_MS}"
          "MOCK_BAILIAN_EXTREME_LATENCY_MS=${MOCK_BAILIAN_EXTREME_LATENCY_MS}"
          "MOCK_BAILIAN_TIMEOUT_LATENCY_MS=${MOCK_BAILIAN_TIMEOUT_LATENCY_MS}"
        )
        ;;
      gateway-service)
        env_args+=(
          "GATEWAY_BACKEND_MODERATION_URL=http://localhost:8081"
          "GATEWAY_HTTP_CONNECT_TIMEOUT_MS=${GATEWAY_HTTP_CONNECT_TIMEOUT_MS}"
          "GATEWAY_HTTP_RESPONSE_TIMEOUT_MS=${GATEWAY_HTTP_RESPONSE_TIMEOUT_MS}"
        )
        ;;
    esac

    nohup env "${env_args[@]}" mvn spring-boot:run >"${log_file}" 2>&1 &
    echo $! >"${pid_file}"
  )
  sleep 1

  if is_running "${service}"; then
    echo "[dev-local] ${service} started (pid=$(cat "${pid_file}"), log=${log_file})"
  else
    echo "[dev-local] Failed to start ${service}. Check log: ${log_file}"
    return 1
  fi
}

build_shared_module() {
  echo "[dev-local] Building shared module common-core ..."
  (cd "${REPO_ROOT}" && mvn -pl common-core -am -DskipTests install)
}

stop_service() {
  local service="$1"
  local pid_file
  pid_file="$(service_pid_file "${service}")"

  if ! is_running "${service}"; then
    echo "[dev-local] ${service} not running"
    return 0
  fi

  local pid
  pid="$(cat "${pid_file}")"
  echo "[dev-local] Stopping ${service} (pid=${pid}) ..."
  kill "${pid}" 2>/dev/null || true

  for _ in {1..20}; do
    if kill -0 "${pid}" 2>/dev/null; then
      sleep 0.5
    else
      break
    fi
  done

  if kill -0 "${pid}" 2>/dev/null; then
    echo "[dev-local] Force killing ${service} (pid=${pid})"
    kill -9 "${pid}" 2>/dev/null || true
  fi

  rm -f "${pid_file}"
  echo "[dev-local] ${service} stopped"
}

status() {
  echo "[dev-local] Local service status:"
  for service in "${ALL_LOCAL_SERVICES[@]}"; do
    if is_running "${service}"; then
      echo "  - ${service}: RUNNING (pid=$(cat "$(service_pid_file "${service}")"))"
    else
      echo "  - ${service}: STOPPED"
    fi
  done
  echo
  echo "[dev-local] Docker dependency status:"
  (cd "${REPO_ROOT}" && docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps)

  # Detect actual L3 provider from model-service logs
  if is_running "model-service"; then
    local log_file="${LOG_DIR}/model-service.log"
    if [[ -f "${log_file}" ]]; then
      if grep -q "Initializing vLLM L3 service" "${log_file}" 2>/dev/null; then
        echo "[dev-local] L3 provider: vllm (detected from running service)"
      elif grep -q "Initializing Mock L3 service" "${log_file}" 2>/dev/null; then
        echo "[dev-local] L3 provider: mock (detected from running service)"
      elif grep -q "Initializing Bailian L3 service" "${log_file}" 2>/dev/null; then
        echo "[dev-local] L3 provider: bailian (detected from running service)"
      elif grep -q "Initializing L3 failover service" "${log_file}" 2>/dev/null; then
        echo "[dev-local] L3 provider: failover (bailian -> vllm, detected from running service)"
      else
        echo "[dev-local] L3 provider: unknown (could not detect from logs)"
      fi
    else
      echo "[dev-local] L3 provider: unknown (log file not found)"
    fi
  else
    # Fallback to environment variable when service is not running
    if [[ -n "${MODEL_L3_PROVIDER}" ]]; then
      echo "[dev-local] L3 provider: ${MODEL_L3_PROVIDER} (from environment)"
    elif is_mock_enabled; then
      echo "[dev-local] L3 provider: mock (from ENABLE_L3_MOCK)"
    else
      echo "[dev-local] L3 provider: failover (bailian -> vllm, default)"
    fi
  fi
}

stop_all() {
  for service in "${ALL_LOCAL_SERVICES[@]}"; do
    stop_service "${service}"
  done
}

stop_deps() {
  echo "[dev-local] Stopping dependency containers..."
  (cd "${REPO_ROOT}" && docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" down)
  echo "[dev-local] Cleaning Redis cache..."
  docker volume rm multimodel-safetyrisk_redis-data 2>/dev/null || true
  echo "[dev-local] Cleaning up logs and pids..."
  rm -rf "${LOG_DIR}" "${PID_DIR}"
  mkdir -p "${LOG_DIR}" "${PID_DIR}"
}

start_all() {
  "${SCRIPT_DIR}/validate-timeout-budget.sh" "${ENV_FILE}"
  start_deps
  build_shared_module
  start_service "moderation-service"
  if is_mock_enabled; then
    start_service "mock-bailian-service"
  fi
  start_service "model-service"
  start_service "gateway-service"
  echo
  echo "[dev-local] All services started."
  echo "[dev-local] Gateway:    http://localhost:8080"
  echo "[dev-local] Moderation: http://localhost:8081"
  echo "[dev-local] Model:      http://localhost:8082"
  if is_mock_enabled; then
    echo "[dev-local] Mock L3:    http://localhost:8089"
  fi
  echo "[dev-local] Zipkin:     http://localhost:9411"
  echo "[dev-local] Prometheus: http://localhost:9090"
  echo "[dev-local] Grafana:    http://localhost:3000"
  echo "[dev-local] Logs under: ${LOG_DIR}"
}

usage() {
  cat <<USAGE
Usage: scripts/dev-local.sh <command>

Environment:
  MODEL_L3_PROVIDER=<provider>   Choose L3 provider: failover (default) | bailian | vllm | mock
  ENABLE_L3_MOCK=true            Legacy: start mock-bailian and use the l3-mock profile
  DASHSCOPE_API_KEY=<key>         Bailian API key (BAILIAN_API_KEY is also accepted)
  MODEL_L3_BAILIAN_MODEL=<model> Bailian model (default: qwen3.8-flash)
  MODEL_L3_VLLM_BASE_URL=<url>   OpenAI-compatible local URL (default: http://localhost:11434/v1)
  MODEL_L3_VLLM_MODEL=<model>    Local model name (default: qwen3.5:0.8b)
  MODEL_L3_VLLM_REASONING_EFFORT=<effort>  none by default; set empty if unsupported
  Timeout budgets are configured in infra/docker/.env; see infra/docker/README.md.

Examples:
  ./scripts/dev-local.sh start                          # Bailian -> local Ollama failover
  MODEL_L3_PROVIDER=bailian ./scripts/dev-local.sh start # Use Bailian only
  MODEL_L3_PROVIDER=vllm ./scripts/dev-local.sh start   # Use local OpenAI-compatible endpoint only
  MODEL_L3_PROVIDER=mock ./scripts/dev-local.sh start   # Use mock service
  ENABLE_L3_MOCK=true ./scripts/dev-local.sh start      # Use mock service (legacy)

Commands:
  start        Start Docker dependencies + local services
  stop         Stop local services (includes mock if running)
  stop-all     Stop local services + dependency containers
  restart      Restart local services (dependencies stay running)
  status       Show local service and dependency status
  logs <name>  Tail logs for one service (name: moderation-service|model-service|gateway-service|mock-bailian-service)
USAGE
}

logs() {
  local service="${1:-}"
  if [[ -z "${service}" ]]; then
    echo "[dev-local] Missing service name"
    usage
    exit 1
  fi
  local log_file="${LOG_DIR}/${service}.log"
  if [[ ! -f "${log_file}" ]]; then
    echo "[dev-local] Log file not found: ${log_file}"
    exit 1
  fi
  tail -f "${log_file}"
}

main() {
  local cmd="${1:-start}"
  case "${cmd}" in
    start)
      start_all
      ;;
    stop)
      stop_all
      ;;
    stop-all)
      stop_all
      stop_deps
      ;;
    restart)
      stop_all
      start_all
      ;;
    status)
      status
      ;;
    logs)
      logs "${2:-}"
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      echo "[dev-local] Unknown command: ${cmd}"
      usage
      exit 1
      ;;
  esac
}

main "$@"
