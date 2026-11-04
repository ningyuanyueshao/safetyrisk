#!/usr/bin/env python3

"""Run L2-only, L3-only, and end-to-end evaluations as one archived suite."""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
RUNNER = SCRIPT_DIR / "run_evaluation.py"
DEFAULT_DATASET = REPO_ROOT / "datasets/l3/eval/l3_eval_frozen_v1.jsonl"
DEFAULT_ASSET_ROOT = REPO_ROOT / "datasets/l3/eval/assets"
DEFAULT_ENV_FILE = REPO_ROOT / "infra/docker/.env"
DEFAULT_COMPOSE_FILE = REPO_ROOT / "infra/docker/docker-compose.yml"
PROVIDERS = ("bailian", "local", "mixed")
MODES = ("sync", "async")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run a complete suite: L2-only once, L3-only for each selected provider, "
            "and the end-to-end pipeline for each selected provider/API mode."
        )
    )
    parser.add_argument("--provider", choices=(*PROVIDERS, "all"), required=True)
    parser.add_argument("--mode", choices=(*MODES, "all"), required=True)
    parser.add_argument("--input", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--asset-root", type=Path, default=DEFAULT_ASSET_ROOT)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--gateway-base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--moderation-base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--model-base-url", default="http://127.0.0.1:8082")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id", help="Suite id; defaults to the current timestamp.")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=40.0)
    parser.add_argument("--poll-interval-ms", type=int, default=500)
    parser.add_argument("--max-polls", type=int, default=120)
    parser.add_argument("--build", action="store_true", help="Build all three app images once before the suite.")
    parser.add_argument("--no-preflight", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def selected(value, all_values):
    return list(all_values) if value == "all" else [value]


def build_jobs(providers, modes):
    jobs = [{"name": "l2", "scope": "l2", "provider": None, "mode": "sync"}]
    jobs.extend(
        {"name": f"l3-{provider}", "scope": "l3", "provider": provider, "mode": "sync"}
        for provider in providers
    )
    jobs.extend(
        {
            "name": f"pipeline-{provider}-{mode}",
            "scope": "pipeline",
            "provider": provider,
            "mode": mode,
        }
        for provider in providers
        for mode in modes
    )
    return jobs


def child_command(args, job, suite_id, output_dir):
    command = [
        sys.executable,
        RUNNER,
        "--scope",
        job["scope"],
        "--mode",
        job["mode"],
        "--input",
        args.input.expanduser().resolve(),
        "--asset-root",
        args.asset_root.expanduser().resolve(),
        "--env-file",
        args.env_file.expanduser().resolve(),
        "--compose-file",
        args.compose_file.expanduser().resolve(),
        "--gateway-base-url",
        args.gateway_base_url,
        "--moderation-base-url",
        args.moderation_base_url,
        "--model-base-url",
        args.model_base_url,
        "--output-dir",
        output_dir,
        "--run-id",
        f"{suite_id}-{job['name']}",
        "--max-samples",
        str(args.max_samples),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--poll-interval-ms",
        str(args.poll_interval_ms),
        "--max-polls",
        str(args.max_polls),
    ]
    if job["provider"]:
        command.extend(["--provider", job["provider"]])
    # The L3-only job performs the provider probe. The subsequent pipeline job
    # reuses that result and avoids duplicate cloud/local probe requests.
    if args.no_preflight or job["scope"] == "pipeline":
        command.append("--no-preflight")
    if args.dry_run:
        command.append("--dry-run")
    return [str(item) for item in command]


def render_report(config):
    lines = [
        "# Full Moderation Evaluation Suite",
        "",
        f"- Suite: `{config['suiteId']}`",
        f"- Status: `{config['status']}`",
        f"- Dataset: `{config['dataset']}`",
        "",
        "| Job | Scope | Provider | Mode | Samples | Accuracy | Macro F1 | Errors | L2 coverage |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for job in config.get("jobs", []):
        observed = job.get("observed") or {}
        totals = observed.get("totals") or {}
        l2 = observed.get("l2Metrics") or {}
        lines.append(
            f"| {job['name']} | {job['scope']} | {job.get('provider') or '-'} | {job['mode']} | "
            f"{totals.get('samples', '-')} | {totals.get('accuracy', '-')} | "
            f"{observed.get('macroF1', '-')} | {totals.get('errors', '-')} | "
            f"{l2.get('coverageRate', '-')} |"
        )
    lines.extend([
        "",
        "L2 `PASS_TO_L3` is projected to PASS only for its shared three-class baseline; "
        "use the L2 coverage/contribution fields for routing quality.",
        "",
    ])
    return "\n".join(lines)


def main():
    args = parse_args()
    if args.max_samples < 0 or args.timeout_seconds <= 0:
        raise ValueError("--max-samples cannot be negative and --timeout-seconds must be positive")
    if args.poll_interval_ms < 0 or args.max_polls <= 0:
        raise ValueError("--poll-interval-ms cannot be negative and --max-polls must be positive")

    suite_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", suite_id):
        raise ValueError("--run-id may contain only letters, digits, dot, underscore and hyphen")
    providers = selected(args.provider, PROVIDERS)
    modes = selected(args.mode, MODES)
    jobs = build_jobs(providers, modes)
    output_root = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else REPO_ROOT / "experiments/phase2/full-suite" / suite_id
    )
    if not args.dry_run and output_root.exists():
        raise ValueError(f"Output directory already exists: {output_root}")

    cloud_jobs = sum(
        job["provider"] in ("bailian", "mixed") and job["scope"] in ("l3", "pipeline")
        for job in jobs
    )
    print(
        f"[full-eval] jobs={len(jobs)} providers={providers} modes={modes} "
        f"cloudJobs={cloud_jobs} maxSamples={args.max_samples or 'all'}",
        flush=True,
    )
    if cloud_jobs:
        print("[full-eval] Notice: Bailian/mixed L3 jobs send dataset content and images to Bailian.")

    if args.build:
        build_command = [
            "docker",
            "compose",
            "-f",
            str(args.compose_file.expanduser().resolve()),
            "--env-file",
            str(args.env_file.expanduser().resolve()),
            "--profile",
            "apps",
            "build",
            "gateway-service",
            "moderation-service",
            "model-service",
        ]
        print("[full-eval] $ " + " ".join(build_command), flush=True)
        if not args.dry_run:
            subprocess.run(build_command, cwd=REPO_ROOT, env=os.environ, check=True)

    config = {
        "suiteId": suite_id,
        "status": "PLANNED" if args.dry_run else "STARTED",
        "dataset": str(args.input.expanduser().resolve()),
        "assetRoot": str(args.asset_root.expanduser().resolve()),
        "providers": providers,
        "modes": modes,
        "maxSamples": args.max_samples,
        "jobs": [],
    }
    if not args.dry_run:
        output_root.mkdir(parents=True)
        write_json(output_root / "suite_config.json", config)

    try:
        for job in jobs:
            job_output = output_root / job["name"]
            command = child_command(args, job, suite_id, job_output)
            print("[full-eval] $ " + " ".join(command), flush=True)
            subprocess.run(command, cwd=REPO_ROOT, env=os.environ, check=True)
            entry = {**job, "outputDir": str(job_output)}
            summary_path = job_output / "summary.json"
            if summary_path.is_file():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                entry["observed"] = {
                    "totals": summary.get("totals"),
                    "macroF1": summary.get("macroF1"),
                    "qualityRates": summary.get("qualityRates"),
                    "l2Metrics": summary.get("l2Metrics"),
                    "latencyMs": summary.get("latencyMs"),
                }
            config["jobs"].append(entry)
            if not args.dry_run:
                write_json(output_root / "suite_config.json", config)
        if args.dry_run:
            return 0
        config["status"] = "COMPLETED"
    except Exception as exc:
        config["status"] = "FAILED"
        config["error"] = str(exc)
        raise
    finally:
        if not args.dry_run and output_root.exists():
            config["finishedAt"] = datetime.now().astimezone().isoformat()
            write_json(output_root / "suite_config.json", config)
            (output_root / "report.md").write_text(render_report(config), encoding="utf-8")

    print(f"[full-eval] Completed. Aggregate report: {output_root / 'report.md'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[full-eval] ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
