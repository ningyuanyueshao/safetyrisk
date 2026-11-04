#!/usr/bin/env python3

"""Run low-cost connectivity probes against the configured L3 providers."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check Bailian and the local OpenAI-compatible provider before L3 evaluation."
    )
    parser.add_argument(
        "--provider",
        choices=("bailian", "local", "both"),
        default="both",
        help="Probe only the provider(s) required by the planned run (default: both).",
    )
    parser.add_argument(
        "--bailian-base-url",
        default=os.getenv(
            "MODEL_L3_BAILIAN_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    )
    parser.add_argument(
        "--bailian-model",
        default=os.getenv("MODEL_L3_BAILIAN_MODEL", "qwen3.8-flash"),
    )
    parser.add_argument(
        "--vllm-base-url",
        default=os.getenv("MODEL_L3_VLLM_BASE_URL", "http://127.0.0.1:11434/v1"),
    )
    parser.add_argument(
        "--vllm-model",
        default=os.getenv("MODEL_L3_VLLM_MODEL", "qwen3.5:0.8b"),
    )
    parser.add_argument(
        "--vllm-reasoning-effort",
        default=os.getenv("MODEL_L3_VLLM_REASONING_EFFORT", "none"),
        help="OpenAI-compatible reasoning effort; use an empty value to omit it.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=35.0,
        help="Per-request timeout (default: 35s, covers the observed Bailian long tail).",
    )
    parser.add_argument(
        "--require-both",
        action="store_true",
        help="Fail unless both providers complete a minimal chat request.",
    )
    return parser.parse_args()


def request_json(method, url, payload, timeout_seconds, bearer_token=None):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if bearer_token:
        headers["Authorization"] = "Bearer " + bearer_token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {
                "ok": response.status < 400,
                "status": response.status,
                "latencyMs": round((time.perf_counter() - started) * 1000, 1),
                "body": body,
                "error": None,
            }
    except urllib.error.HTTPError as exception:
        return {
            "ok": False,
            "status": exception.code,
            "latencyMs": round((time.perf_counter() - started) * 1000, 1),
            "body": None,
            "error": f"HTTP {exception.code}",
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exception:
        reason = getattr(exception, "reason", None) or str(exception)
        return {
            "ok": False,
            "status": None,
            "latencyMs": round((time.perf_counter() - started) * 1000, 1),
            "body": None,
            "error": str(reason),
        }


def chat_payload(model, reasoning_effort=None):
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 64,
        "messages": [
            {
                "role": "user",
                "content": "只输出 JSON：{\"status\":\"ok\"}",
            }
        ],
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    return payload


def valid_chat_response(result):
    body = result.get("body")
    if not (
        result.get("ok")
        and isinstance(body, dict)
        and isinstance(body.get("choices"), list)
        and body["choices"]
    ):
        return False
    message = body["choices"][0].get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(
            isinstance(part, dict) and str(part.get("text", "")).strip()
            for part in content
        )
    return False


def print_result(name, result, detail=None):
    state = "OK" if result.get("available") else "UNAVAILABLE"
    fields = [f"status={result.get('status')}", f"latencyMs={result.get('latencyMs')}"]
    if detail:
        fields.append(detail)
    if result.get("error"):
        fields.append(f"error={result['error']}")
    print(f"[{state}] {name}: " + ", ".join(fields))


def check_bailian(args):
    api_key = (
        os.getenv("DASHSCOPE_API_KEY", "").strip()
        or os.getenv("BAILIAN_API_KEY", "").strip()
    )
    if not api_key:
        result = {
            "available": False,
            "status": None,
            "latencyMs": 0.0,
            "error": "DASHSCOPE_API_KEY/BAILIAN_API_KEY is not set",
        }
        print_result("Bailian", result, f"model={args.bailian_model}")
        return result

    result = request_json(
        "POST",
        args.bailian_base_url.rstrip("/") + "/chat/completions",
        chat_payload(args.bailian_model),
        args.timeout_seconds,
        bearer_token=api_key,
    )
    result["available"] = valid_chat_response(result)
    print_result("Bailian", result, f"model={args.bailian_model}")
    return result


def check_vllm(args):
    base_url = args.vllm_base_url.rstrip("/")
    models = request_json("GET", base_url + "/models", None, args.timeout_seconds)
    advertised = []
    if models.get("ok") and isinstance(models.get("body"), dict):
        advertised = [
            str(item.get("id"))
            for item in models["body"].get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
    if not models.get("ok"):
        models["available"] = False
        print_result("Local OpenAI-compatible provider", models, f"model={args.vllm_model}")
        return models

    result = request_json(
        "POST",
        base_url + "/chat/completions",
        chat_payload(args.vllm_model, args.vllm_reasoning_effort),
        args.timeout_seconds,
    )
    result["available"] = valid_chat_response(result)
    advertised_state = "configured-model-advertised=" + str(args.vllm_model in advertised).lower()
    print_result(
        "Local OpenAI-compatible provider",
        result,
        f"model={args.vllm_model}, {advertised_state}",
    )
    return result


def main():
    args = parse_args()
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")

    selected = "both" if args.require_both else args.provider
    results = []
    if selected in ("bailian", "both"):
        results.append(check_bailian(args))
    if selected in ("local", "both"):
        results.append(check_vllm(args))

    available = sum(bool(item.get("available")) for item in results)
    if selected == "both" and available != 2:
        print("Preflight failed: both L3 providers are required.", file=sys.stderr)
        return 2
    if available != len(results):
        print(f"Preflight failed: required provider mode '{selected}' is unavailable.", file=sys.stderr)
        return 2
    print(f"Preflight passed: {available}/{len(results)} required providers available.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as exception:
        print(f"Configuration error: {exception}", file=sys.stderr)
        sys.exit(2)
