#!/usr/bin/env python3

"""Run a reproducible L2-only or end-to-end moderation evaluation."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_DATASET = REPO_ROOT / "datasets/l3/eval/l3_eval_frozen_v1.jsonl"
DEFAULT_ASSET_ROOT = REPO_ROOT / "datasets/l3/eval/assets"
DEFAULT_ENV_FILE = REPO_ROOT / "infra/docker/.env"
DEFAULT_COMPOSE_FILE = REPO_ROOT / "infra/docker/docker-compose.yml"

PROVIDER_CONFIG = {
    "bailian": {"runtime": "bailian", "preflight": "bailian", "usesCloud": True},
    "local": {"runtime": "vllm", "preflight": "local", "usesCloud": False},
    "mixed": {"runtime": "failover", "preflight": "both", "usesCloud": True},
}

TIMEOUT_DEFAULTS = {
    "MODEL_L3_BAILIAN_TIMEOUT_MS": "18000",
    "MODEL_L3_VLLM_TIMEOUT_MS": "7000",
    "MODEL_SERVICE_INFER_TIMEOUT_MS": "27000",
    "MODERATION_MODEL_SERVICE_TIMEOUT_MS": "30000",
    "MODERATION_MODEL_SERVICE_ASYNC_TIMEOUT_MS": "30000",
    "GATEWAY_HTTP_CONNECT_TIMEOUT_MS": "3000",
    "GATEWAY_HTTP_RESPONSE_TIMEOUT_MS": "32000",
    "MODERATION_ASYNC_PROCESS_TIMEOUT_MS": "35000",
    "MODERATION_ASYNC_PROCESSING_LEASE_MS": "90000",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate L2 directly, or evaluate one L3 routing mode "
            "(Bailian/local/mixed) through the Gateway sync or async API."
        )
    )
    parser.add_argument("--scope", choices=("l2", "l3", "pipeline"), default="pipeline")
    parser.add_argument(
        "--provider",
        choices=tuple(PROVIDER_CONFIG),
        help="Required for --scope l3/pipeline; ignored for --scope l2.",
    )
    parser.add_argument("--mode", choices=("sync", "async"), required=True)
    parser.add_argument("--input", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--asset-root", type=Path, default=DEFAULT_ASSET_ROOT)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--gateway-base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--moderation-base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--model-base-url", default="http://127.0.0.1:8082")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id", help="Archive/namespace id; defaults to the current timestamp.")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=40.0)
    parser.add_argument("--poll-interval-ms", type=int, default=500)
    parser.add_argument(
        "--max-polls",
        type=int,
        default=120,
        help="Async terminal-state polls (default: 120 × 500ms = 60s).",
    )
    parser.add_argument("--no-restart", action="store_true", help="Use already-running services.")
    parser.add_argument("--no-preflight", action="store_true", help="Skip provider connectivity probes.")
    parser.add_argument("--build", action="store_true", help="Build app images before restarting them.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and print the plan only.")
    return parser.parse_args()


def load_simple_env(path, base_env=None):
    env = dict(base_env or os.environ)
    if not path.is_file():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        env.setdefault(key, value)
    return env


def run(command, *, env, cwd=REPO_ROOT):
    display = " ".join(str(item) for item in command)
    print(f"[l3-eval] $ {display}", flush=True)
    subprocess.run([str(item) for item in command], cwd=cwd, env=env, check=True)


def wait_for_health(name, base_url, timeout_seconds=120):
    health_url = base_url.rstrip("/") + "/actuator/health"
    deadline = time.monotonic() + timeout_seconds
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=3) as response:
                body = json.loads(response.read().decode("utf-8"))
                if response.status < 400 and body.get("status") == "UP":
                    print(f"[l3-eval] {name} health is UP: {health_url}")
                    return
                last_error = f"HTTP {response.status}: {body}"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = str(getattr(exc, "reason", None) or exc)
        time.sleep(2)
    raise RuntimeError(f"{name} did not become healthy within {timeout_seconds}s: {last_error}")


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(*args):
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def explicit_user_id_count(path):
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if not raw_line.strip():
                continue
            record = json.loads(raw_line)
            if str(record.get("userId", "")).strip():
                count += 1
    return count


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    asset_root = args.asset_root.expanduser().resolve()
    env_file = args.env_file.expanduser().resolve()
    compose_file = args.compose_file.expanduser().resolve()
    if not input_path.is_file():
        raise ValueError(f"Dataset not found: {input_path}")
    if not asset_root.is_dir():
        raise ValueError(f"Asset root not found: {asset_root}")
    if args.max_samples < 0 or args.timeout_seconds <= 0:
        raise ValueError("--max-samples cannot be negative and --timeout-seconds must be positive")
    if args.poll_interval_ms < 0 or args.max_polls <= 0:
        raise ValueError("--poll-interval-ms cannot be negative and --max-polls must be positive")
    if args.scope in ("l3", "pipeline") and not args.provider:
        raise ValueError("--provider is required when --scope is l3 or pipeline")
    if args.scope in ("l2", "l3") and args.mode != "sync":
        raise ValueError(f"{args.scope.upper()}-only evaluation is synchronous; use --mode sync")
    if args.no_restart and args.build:
        raise ValueError("--build cannot be combined with --no-restart")
    if not args.no_restart and not env_file.is_file():
        raise ValueError(f"Compose env file not found: {env_file}")
    if not args.no_restart and not compose_file.is_file():
        raise ValueError(f"Compose file not found: {compose_file}")

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise ValueError("--run-id may contain only letters, digits, dot, underscore and hyphen")
    provider = PROVIDER_CONFIG.get(args.provider) if args.scope in ("l3", "pipeline") else None
    gateway_base = args.gateway_base_url.rstrip("/")
    sync_url = gateway_base + "/api/v1/moderation/check"
    async_url = gateway_base + "/api/v1/moderation/check/async"
    task_template = gateway_base + "/api/v1/moderation/tasks/{taskId}"
    if args.scope == "l2":
        endpoint = args.model_base_url.rstrip("/") + "/api/v1/model/classify/l2"
    elif args.scope == "l3":
        endpoint = args.model_base_url.rstrip("/") + "/api/v1/model/classify/l3"
    else:
        endpoint = sync_url if args.mode == "sync" else async_url
    provider_name = args.provider if provider else "l2"
    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else REPO_ROOT
        / (
            "experiments/phase2/l2"
            if args.scope == "l2"
            else ("experiments/phase2/l3-direct" if args.scope == "l3" else "experiments/phase2/gateway-l3")
        )
        / f"{run_id}-{provider_name}-{args.mode}"
    )
    namespace = f"{run_id}-{provider_name}-{args.mode}"
    child_env = load_simple_env(env_file)
    if provider:
        child_env["MODEL_L3_PROVIDER"] = provider["runtime"]
        run(
            [REPO_ROOT / "scripts/validate-timeout-budget.sh", env_file],
            env=child_env,
        )

    plan = {
        "scope": args.scope,
        "provider": args.provider if provider else None,
        "modelServiceProvider": provider["runtime"] if provider else None,
        "mode": args.mode,
        "endpoint": endpoint,
        "dataset": str(input_path),
        "assetRoot": str(asset_root),
        "outputDir": str(output_dir),
        "requestNamespace": namespace,
        "usesBailian": provider["usesCloud"] if provider else False,
        "restartServices": not args.no_restart,
        "buildImages": args.build,
    }
    print("[l3-eval] Plan:\n" + json.dumps(plan, ensure_ascii=False, indent=2))
    if provider and provider["usesCloud"]:
        print("[l3-eval] Notice: this run sends dataset content/images to Bailian.")
    if args.no_restart and provider:
        print(
            "[l3-eval] Warning: --no-restart cannot verify that the running "
                f"model-service provider is '{provider['runtime']}'."
            )

    evaluator = SCRIPT_DIR / "evaluate_moderation_dataset.py"
    evaluation_command = [
        sys.executable,
        evaluator,
        "--input",
        input_path,
        "--asset-root",
        asset_root,
        "--target",
        args.scope,
        "--mode",
        args.mode,
        "--url",
        endpoint,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--max-samples",
        str(args.max_samples),
        "--request-namespace",
        namespace,
        "--require-frozen",
    ]
    if args.mode == "async":
        evaluation_command.extend(
            [
                "--task-url-template",
                task_template,
                "--poll-interval-ms",
                str(args.poll_interval_ms),
                "--max-polls",
                str(args.max_polls),
            ]
        )
    if args.dry_run:
        evaluation_command.append("--dry-run")
        run(evaluation_command, env=child_env)
        return 0

    if output_dir.exists():
        raise ValueError(f"Output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    explicit_ids = explicit_user_id_count(input_path)
    if explicit_ids:
        print(
            f"[l3-eval] Warning: {explicit_ids} records define userId; their cache/dedup key "
            "is intentionally preserved and may reuse prior async tasks."
        )

    started_at = datetime.now().astimezone().isoformat()
    run_config = {
        "status": "STARTED",
        "startedAt": started_at,
        **plan,
        "datasetSha256": sha256_file(input_path),
        "datasetOutboundToBailian": provider["usesCloud"] if provider else False,
        "models": {
            "bailian": child_env.get("MODEL_L3_BAILIAN_MODEL") or "qwen3.8-flash",
            "local": child_env.get("MODEL_L3_VLLM_MODEL") or "qwen3.5:0.8b",
            "l2TextEnabled": str(child_env.get("MODEL_L2_TEXT_ENABLED", "false")).lower() == "true",
            "l2Image": child_env.get("MODEL_L2_IMAGE_MODEL_PATH") or "/models/resnet50_finetune_onnx",
        },
        "timeoutsMs": {
            key: int(child_env.get(key) or default) for key, default in TIMEOUT_DEFAULTS.items()
        },
        "evaluation": {
            "timeoutSeconds": args.timeout_seconds,
            "maxSamples": args.max_samples,
            "pollIntervalMs": args.poll_interval_ms if args.mode == "async" else None,
            "maxPolls": args.max_polls if args.mode == "async" else None,
        },
        "recordsWithExplicitUserId": explicit_ids,
        "gitCommit": git_value("rev-parse", "HEAD"),
        "gitWorktreeDirty": bool(git_value("status", "--porcelain")),
    }
    config_path = output_dir / "run_config.json"
    write_json(config_path, run_config)

    try:
        if provider and not args.no_preflight:
            run(
                [
                    sys.executable,
                    SCRIPT_DIR / "preflight_l3_providers.py",
                    "--provider",
                    provider["preflight"],
                ],
                env=child_env,
            )
        if not args.no_restart:
            compose_prefix = [
                "docker",
                "compose",
                "-f",
                compose_file,
                "--env-file",
                env_file,
                "--profile",
                "apps",
            ]
            if args.build:
                build_services = (
                    ["model-service"]
                    if args.scope in ("l2", "l3")
                    else ["gateway-service", "moderation-service", "model-service"]
                )
                run(
                    compose_prefix + ["build", *build_services],
                    env=child_env,
                )
            restart_services = (
                ["model-service"]
                if args.scope in ("l2", "l3")
                else ["model-service", "moderation-service", "gateway-service"]
            )
            run(
                compose_prefix
                + [
                    "up",
                    "-d",
                    "--no-build",
                    "--force-recreate",
                    *restart_services,
                ],
                env=child_env,
            )
        wait_for_health("model-service", args.model_base_url)
        if args.scope == "pipeline":
            wait_for_health("moderation-service", args.moderation_base_url)
            wait_for_health("gateway-service", gateway_base)
        evaluation_command.extend(["--output-dir", output_dir])
        run(evaluation_command, env=child_env)
        run_config["status"] = "COMPLETED"
        summary_path = output_dir / "summary.json"
        if summary_path.is_file():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            run_config["observed"] = {
                "totals": summary.get("totals"),
                "qualityRates": summary.get("qualityRates"),
                "macroF1": summary.get("macroF1"),
                "l2Metrics": summary.get("l2Metrics"),
                "latencyMs": summary.get("latencyMs"),
            }
    except Exception as exc:
        run_config["status"] = "FAILED"
        run_config["error"] = str(exc)
        raise
    finally:
        run_config["finishedAt"] = datetime.now().astimezone().isoformat()
        write_json(config_path, run_config)

    print(f"[l3-eval] Completed. Report: {output_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[l3-eval] ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
