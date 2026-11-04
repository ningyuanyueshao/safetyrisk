#!/usr/bin/env python3

"""Evaluate moderation decisions against a JSONL Gold Dataset."""

import argparse
import base64
import json
import math
import mimetypes
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from pathlib import Path


LABELS = ("REJECT", "REVIEW", "PASS")
CONTENT_TYPES = ("TEXT", "IMAGE", "MIXED")
ERROR_LABEL = "ERROR"
L2_ROUTE_LABEL = "PASS_TO_L3"
TERMINAL_STATUSES = ("COMPLETED", "FAILED")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Evaluate a moderation dataset against a running endpoint."
    )
    parser.add_argument("--input", required=True, help="Path to a JSONL dataset.")
    parser.add_argument(
        "--target",
        choices=("pipeline", "l2", "l3"),
        default="pipeline",
        help=(
            "Scoring target. For l2, PASS_TO_L3 is retained as rawL2Decision and "
            "projected to PASS only for the shared three-class baseline."
        ),
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8080/api/v1/moderation/check",
        help="Sync/model endpoint, or async submit endpoint when --mode async.",
    )
    parser.add_argument(
        "--mode",
        choices=("sync", "async"),
        default="sync",
        help="Evaluate a direct response or submit and poll an async task.",
    )
    parser.add_argument(
        "--task-url-template",
        help="Async task query URL containing {taskId}; required with --mode async.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=40.0,
        help="Per-HTTP-request client timeout (default: 40s, covers the 32s Gateway budget).",
    )
    parser.add_argument("--poll-interval-ms", type=int, default=500)
    parser.add_argument("--max-polls", type=int, default=20)
    parser.add_argument(
        "--request-namespace",
        default="",
        help=(
            "Optional evaluation namespace written to userId when the record has no userId. "
            "Use a unique value per run to avoid Redis cache and async task-dedup reuse."
        ),
    )
    parser.add_argument(
        "--output-dir",
        help="Optional directory to write summary.json, report.md and predictions.jsonl.",
    )
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--asset-root", default=".", help="Root used to resolve local image references before Base64 encoding.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--require-frozen",
        action="store_true",
        help="Require every record to have annotationStatus=FROZEN.",
    )
    parser.add_argument(
        "--enforce-quality-gate",
        action="store_true",
        help="Exit non-zero when any configured quality threshold is not met.",
    )
    parser.add_argument("--min-accuracy", type=float)
    parser.add_argument("--min-macro-f1", type=float)
    parser.add_argument("--min-reject-recall", type=float)
    parser.add_argument("--max-risky-pass-rate", type=float)
    parser.add_argument("--max-safe-false-reject-rate", type=float)
    parser.add_argument("--max-review-rate", type=float)
    return parser.parse_args()


def load_records(path, require_frozen=False):
    records = []
    ids = set()
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Line {line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"Line {line_number}: record must be a JSON object.")
            validate_record(record, line_number, require_frozen=require_frozen)
            record_id = str(record.get("id", "")).strip()
            if record_id in ids:
                raise ValueError(f"Line {line_number}: duplicate id {record_id!r}.")
            ids.add(record_id)
            records.append(record)
    if not records:
        raise ValueError("No valid records found in the input file.")
    return records


def validate_record(record, line_number, require_frozen=False):
    record_id = str(record.get("id", "")).strip()
    if not record_id:
        raise ValueError(f"Line {line_number}: id must be a non-empty string.")
    if require_frozen and str(record.get("annotationStatus", "")).upper().strip() != "FROZEN":
        raise ValueError(
            f"Line {line_number}: annotationStatus=FROZEN is required for a formal evaluation."
        )
    content_type = str(record.get("contentType", "")).upper().strip()
    if content_type not in CONTENT_TYPES:
        raise ValueError(
            f"Line {line_number}: contentType must be one of {CONTENT_TYPES}, got {content_type!r}."
        )
    expected = str(record.get("expectedDecision", "")).upper().strip()
    if expected not in LABELS:
        raise ValueError(
            f"Line {line_number}: expectedDecision must be one of {LABELS}, got {expected!r}."
        )
    if "expectedViolation" in record and not isinstance(record["expectedViolation"], bool):
        raise ValueError(f"Line {line_number}: expectedViolation must be boolean when present.")

    has_text = bool(str(record.get("content", "")).strip())
    has_image = any(
        bool(str(record.get(field, "")).strip())
        for field in ("imagePath", "imageUrl", "imageData")
    )
    if content_type == "TEXT" and not has_text:
        raise ValueError(f"Line {line_number}: TEXT record must contain non-empty content.")
    if content_type == "IMAGE" and not has_image:
        raise ValueError(
            f"Line {line_number}: IMAGE record must contain non-empty imagePath, imageUrl, or imageData."
        )
    if content_type == "MIXED" and not (has_text or has_image):
        raise ValueError(
            f"Line {line_number}: MIXED record must contain content or an imagePath/imageUrl/imageData source."
        )


def _is_remote_image_reference(value):
    lowered = str(value or "").lower().strip()
    return lowered.startswith(("http://", "https://", "data:"))


def _resolve_local_image_path(value, input_path, asset_root):
    raw = Path(str(value)).expanduser()
    candidates = [raw] if raw.is_absolute() else [Path(asset_root) / raw, Path.cwd() / raw, Path(input_path).resolve().parent / raw]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    raise ValueError(f"Local image resource not found: {value!r}; checked under {Path(asset_root).resolve()}")


def _image_data_from_record(record, input_path=None, asset_root="."):
    value = record.get("imagePath") or record.get("imageUrl")
    if not value or _is_remote_image_reference(value):
        return None
    path = _resolve_local_image_path(value, input_path or ".", asset_root)
    data = path.read_bytes()
    if not data:
        raise ValueError(f"Local image resource is empty: {path}")
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return base64.b64encode(data).decode("ascii"), mime_type, str(path)


def build_payload(record, input_path=None, asset_root=".", request_namespace=""):
    payload = {"contentType": str(record["contentType"]).upper().strip()}
    if str(record.get("content", "")).strip():
        payload["content"] = record["content"]
    if str(record.get("userId", "")).strip():
        payload["userId"] = record["userId"]
    elif str(request_namespace).strip():
        # userId participates in both the moderation cache key and async request hash,
        # but is not sent to the model prompt. This keeps repeated formal runs cold
        # without modifying the labelled text/image content.
        payload["userId"] = "eval:" + str(request_namespace).strip()
    direct_image_data = str(record.get("imageData", "")).strip()
    if direct_image_data:
        payload["imageData"] = record["imageData"]
        return payload
    image_ref = record.get("imagePath") or record.get("imageUrl")
    if image_ref:
        if _is_remote_image_reference(image_ref):
            if str(image_ref).lower().startswith("data:"):
                payload["imageData"] = str(image_ref)
            else:
                payload["imageUrl"] = image_ref
        else:
            image_data, _mime_type, _path = _image_data_from_record(record, input_path, asset_root)
            payload["imageData"] = image_data
    return payload


def safe_json_loads(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def call_http(url, payload=None, timeout_seconds=40.0, method="POST"):
    encoded = None
    headers = {"Accept": "application/json", "X-Request-Id": str(uuid.uuid4())}
    if payload is not None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url=url, data=encoded, headers=headers, method=method)
    started_at = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body_text = response.read().decode("utf-8", errors="replace")
            body = safe_json_loads(body_text)
            latency_ms = (time.perf_counter() - started_at) * 1000.0
            return {
                "httpStatus": response.status,
                "ok": response.status < 400 and isinstance(body, (dict, list)),
                "latencyMs": latency_ms,
                "body": body,
                "error": None if isinstance(body, (dict, list)) else "invalid JSON response",
            }
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        body = safe_json_loads(exc.read().decode("utf-8", errors="replace"))
        return {
            "httpStatus": exc.code,
            "ok": False,
            "latencyMs": latency_ms,
            "body": body,
            "error": f"HTTP {exc.code}",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        reason = getattr(exc, "reason", None) or str(exc)
        return {
            "httpStatus": None,
            "ok": False,
            "latencyMs": latency_ms,
            "body": None,
            "error": str(reason),
        }


def call_endpoint(url, payload, timeout_seconds):
    """Backward-compatible wrapper for callers of the original script."""
    return call_http(url, payload, timeout_seconds, "POST")


def percentile(values, p):
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def format_ratio(value):
    return round(value, 4)


def summarize_dry_run(records, input_path):
    decisions = defaultdict(int)
    content_types = defaultdict(int)
    scenes = defaultdict(int)
    for item in records:
        decisions[str(item["expectedDecision"]).upper().strip()] += 1
        content_types[str(item["contentType"]).upper().strip()] += 1
        scenes[str(item.get("scene", "UNKNOWN")).strip() or "UNKNOWN"] += 1
    print(f"Validated {len(records)} records from {input_path}.")
    print("Label distribution:")
    for label in LABELS:
        print(f"  - {label}: {decisions[label]}")
    print("Content type distribution:")
    for content_type in CONTENT_TYPES:
        print(f"  - {content_type}: {content_types[content_type]}")
    if any("expectedViolation" in item for item in records):
        print("Violation labels:")
        print(f"  - true: {sum(item.get('expectedViolation') is True for item in records)}")
        print(f"  - false: {sum(item.get('expectedViolation') is False for item in records)}")
    for scene, count in sorted(scenes.items(), key=lambda pair: pair[1], reverse=True)[:5]:
        print(f"  - scene {scene}: {count}")


def extract_prediction(body, target="pipeline"):
    body = body if isinstance(body, dict) else {}
    decision = str(body.get("decision", ERROR_LABEL)).upper().strip()
    if target == "l2" and decision == L2_ROUTE_LABEL:
        # The shared dataset has final PASS/REVIEW/REJECT labels. Project routing to
        # PASS only for a comparable standalone baseline, while preserving the raw
        # decision for L2 coverage and terminal-decision metrics.
        return "PASS"
    return decision if decision in LABELS else ERROR_LABEL


def _redact_payload_for_output(payload):
    redacted = dict(payload or {})
    if "imageData" in redacted:
        redacted["imageData"] = "<base64:" + str(len(str(redacted["imageData"]))) + " chars>"
    return redacted

def result_from_response(record, index, payload, response, body, extra=None, target="pipeline"):
    raw_decision = str(body.get("decision", ERROR_LABEL)).upper().strip() if isinstance(body, dict) else ERROR_LABEL
    result = {
        "id": record.get("id", f"sample-{index:04d}"),
        "scene": record.get("scene"),
        "category": record.get("category"),
        "contentType": str(record["contentType"]).upper().strip(),
        "expectedDecision": str(record["expectedDecision"]).upper().strip(),
        "predictedDecision": extract_prediction(body, target=target),
        "rawL2Decision": raw_decision if target == "l2" else None,
        "evaluationTarget": target,
        "expectedViolation": record.get("expectedViolation"),
        "predictedViolation": body.get("violation") if isinstance(body, dict) else None,
        "confidence": body.get("confidence") if isinstance(body, dict) else None,
        "reasonCode": body.get("reasonCode") if isinstance(body, dict) else None,
        "reason": body.get("reason") if isinstance(body, dict) else None,
        "decisionLayer": body.get("decisionLayer") if isinstance(body, dict) else None,
        "httpStatus": response["httpStatus"],
        "ok": response["ok"],
        "latencyMs": round(response["latencyMs"], 3),
        "error": response["error"],
        "payload": _redact_payload_for_output(payload),
        "rawResponse": body if isinstance(body, dict) else response["body"],
    }
    if extra:
        result.update(extra)
    return result


def print_result(index, total, result):
    print(
        f"[{index}/{total}] {result['id']} expected={result['expectedDecision']} "
        f"predicted={result['predictedDecision']} http={result['httpStatus']} "
        f"latencyMs={result.get('e2eLatencyMs', result['latencyMs'])}"
    )


def evaluate_sync(
    records,
    url,
    timeout_seconds,
    input_path=None,
    asset_root=".",
    request_namespace="",
    target="pipeline",
):
    results = []
    for index, record in enumerate(records, start=1):
        payload = build_payload(
            record,
            input_path=input_path,
            asset_root=asset_root,
            request_namespace=request_namespace,
        )
        response = call_http(url, payload, timeout_seconds, "POST")
        body = response["body"] if isinstance(response["body"], dict) else {}
        result = result_from_response(record, index, payload, response, body, target=target)
        results.append(result)
        print_result(index, len(records), result)
    return results


def evaluate(records, url, timeout_seconds, input_path=None, asset_root=".", request_namespace="", target="pipeline"):
    """Backward-compatible name for the original synchronous evaluator."""
    return evaluate_sync(
        records,
        url,
        timeout_seconds,
        input_path=input_path,
        asset_root=asset_root,
        request_namespace=request_namespace,
        target=target,
    )


def evaluate_async(
    records,
    submit_url,
    task_url_template,
    timeout_seconds,
    poll_interval_ms,
    max_polls,
    input_path=None,
    asset_root=".",
    request_namespace="",
    target="pipeline",
):
    results = []
    for index, record in enumerate(records, start=1):
        payload = build_payload(
            record,
            input_path=input_path,
            asset_root=asset_root,
            request_namespace=request_namespace,
        )
        started = time.perf_counter()
        submit = call_http(submit_url, payload, timeout_seconds, "POST")
        submit_body = submit["body"] if isinstance(submit["body"], dict) else {}
        task_id = submit_body.get("taskId")
        polls = 0
        terminal = submit
        terminal_body = submit_body
        status = str(submit_body.get("status", "")).upper()

        if submit["ok"] and task_id and status not in TERMINAL_STATUSES:
            while polls < max_polls:
                if poll_interval_ms > 0:
                    time.sleep(poll_interval_ms / 1000.0)
                polls += 1
                terminal = call_http(
                    task_url_template.format(taskId=task_id),
                    None,
                    timeout_seconds,
                    "GET",
                )
                terminal_body = terminal["body"] if isinstance(terminal["body"], dict) else {}
                status = str(terminal_body.get("status", "")).upper()
                if status in TERMINAL_STATUSES:
                    break

        total_latency_ms = (time.perf_counter() - started) * 1000.0
        body = terminal_body if terminal_body else submit_body
        result = result_from_response(
            record,
            index,
            payload,
            terminal,
            body,
            extra={
                "mode": "async",
                "taskId": task_id,
                "status": status or None,
                "submitHttpStatus": submit["httpStatus"],
                "submitOk": submit["ok"],
                "submitLatencyMs": round(submit["latencyMs"], 3),
                "pollCount": polls,
                "terminalHttpStatus": terminal["httpStatus"],
                "e2eLatencyMs": round(total_latency_ms, 3),
                "error": terminal["error"]
                or ("async task did not reach terminal status" if status not in TERMINAL_STATUSES else None),
            },
            target=target,
        )
        result["ok"] = bool(submit["ok"] and terminal["ok"] and status == "COMPLETED")
        results.append(result)
        print_result(index, len(records), result)
    return results


def classification_metrics(results):
    confusion_labels = list(LABELS) + [ERROR_LABEL]
    confusion = {
        expected: {predicted: 0 for predicted in confusion_labels}
        for expected in LABELS
    }
    for item in results:
        confusion[item["expectedDecision"]][item["predictedDecision"]] += 1

    per_label = {}
    f1_values = []
    for label in LABELS:
        tp = confusion[label][label]
        fp = sum(confusion[expected][label] for expected in LABELS if expected != label)
        fn = sum(
            confusion[label][predicted]
            for predicted in confusion_labels
            if predicted != label
        )
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_values.append(f1)
        per_label[label] = {
            "precision": format_ratio(precision),
            "recall": format_ratio(recall),
            "f1": format_ratio(f1),
            "support": sum(confusion[label].values()),
        }
    return confusion, per_label, format_ratio(statistics.fmean(f1_values) if f1_values else 0.0)


def violation_metrics(results):
    labelled = [item for item in results if isinstance(item.get("expectedViolation"), bool)]
    if not labelled:
        return None
    tp = sum(item["expectedViolation"] is True and item.get("predictedViolation") is True for item in labelled)
    fp = sum(item["expectedViolation"] is False and item.get("predictedViolation") is True for item in labelled)
    fn = sum(item["expectedViolation"] is True and item.get("predictedViolation") is not True for item in labelled)
    tn = sum(item["expectedViolation"] is False and item.get("predictedViolation") is not True for item in labelled)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "labelledSamples": len(labelled),
        "truePositive": tp,
        "falsePositive": fp,
        "falseNegative": fn,
        "trueNegative": tn,
        "precision": format_ratio(precision),
        "recall": format_ratio(recall),
        "f1": format_ratio(f1),
    }


def quality_rates(results):
    total = len(results)
    reject_targets = [item for item in results if item.get("expectedDecision") == "REJECT"]
    risky = [item for item in results if item.get("expectedViolation") is True]
    safe = [item for item in results if item.get("expectedViolation") is False]
    return {
        "rejectRecall": sum(item["predictedDecision"] == "REJECT" for item in reject_targets) / len(reject_targets) if reject_targets else None,
        "riskyPassRate": sum(item["predictedDecision"] == "PASS" for item in risky) / len(risky) if risky else None,
        "safeFalseRejectRate": sum(item["predictedDecision"] != "PASS" for item in safe) / len(safe) if safe else None,
        "reviewRate": sum(item["predictedDecision"] == "REVIEW" for item in results) / total if total else 0.0,
    }


def l2_metrics(results):
    routed = [item for item in results if item.get("rawL2Decision") == L2_ROUTE_LABEL]
    terminal = [item for item in results if item.get("rawL2Decision") in ("REJECT", "REVIEW")]
    rejected = [item for item in results if item.get("rawL2Decision") == "REJECT"]
    reviewed = [item for item in results if item.get("rawL2Decision") == "REVIEW"]
    expected_reject = [item for item in results if item.get("expectedDecision") == "REJECT"]
    expected_safe = [item for item in results if item.get("expectedDecision") == "PASS"]
    expected_risky = [item for item in results if item.get("expectedViolation") is True]
    terminal_correct = sum(
        item.get("rawL2Decision") == item.get("expectedDecision") for item in terminal
    )
    return {
        "routedToL3": len(routed),
        "routeRate": format_ratio(len(routed) / len(results) if results else 0.0),
        "terminalDecisions": len(terminal),
        "coverageRate": format_ratio(len(terminal) / len(results) if results else 0.0),
        "terminalCorrect": terminal_correct,
        "terminalAccuracy": format_ratio(terminal_correct / len(terminal)) if terminal else None,
        "rejected": len(rejected),
        "reviewed": len(reviewed),
        "rejectPrecision": format_ratio(
            sum(item.get("expectedDecision") == "REJECT" for item in rejected) / len(rejected)
        ) if rejected else None,
        "rejectRecallContribution": format_ratio(
            sum(item.get("rawL2Decision") == "REJECT" for item in expected_reject) / len(expected_reject)
        ) if expected_reject else None,
        "riskyTerminalCoverage": format_ratio(
            sum(item.get("rawL2Decision") in ("REJECT", "REVIEW") for item in expected_risky)
            / len(expected_risky)
        ) if expected_risky else None,
        "safeFalseRejectRate": format_ratio(
            sum(item.get("rawL2Decision") == "REJECT" for item in expected_safe) / len(expected_safe)
        ) if expected_safe else None,
        "safeTerminalRate": format_ratio(
            sum(item.get("rawL2Decision") in ("REJECT", "REVIEW") for item in expected_safe)
            / len(expected_safe)
        ) if expected_safe else None,
        "routedExpectedDecisions": {
            label: sum(item.get("expectedDecision") == label for item in routed) for label in LABELS
        },
    }


def build_summary(results, url, input_path, mode="sync", target="pipeline"):
    total = len(results)
    errors = sum(1 for item in results if not item["ok"])
    correct = sum(item["expectedDecision"] == item["predictedDecision"] for item in results)
    latency_key = "e2eLatencyMs" if mode == "async" else "latencyMs"
    latencies = [item[latency_key] for item in results if item.get(latency_key) is not None]
    success_latencies = [item[latency_key] for item in results if item["ok"] and item.get(latency_key) is not None]
    confusion, per_label, macro_f1 = classification_metrics(results)
    rates = quality_rates(results)

    grouped = defaultdict(list)
    for item in results:
        for dimension in ("contentType", "scene", "category"):
            value = item.get(dimension)
            if value is not None and str(value).strip():
                grouped[f"{dimension}={value}"].append(item)
    by_group = {}
    for group, group_results in sorted(grouped.items()):
        group_confusion, group_labels, group_macro_f1 = classification_metrics(group_results)
        group_total = len(group_results)
        group_rates = quality_rates(group_results)
        by_group[group] = {
            "samples": group_total,
            "accuracy": format_ratio(sum(x["expectedDecision"] == x["predictedDecision"] for x in group_results) / group_total),
            "macroF1": group_macro_f1,
            "perLabel": group_labels,
            "violation": violation_metrics(group_results),
            "qualityRates": group_rates,
            "confusionMatrix": group_confusion,
        }

    return {
        "input": str(input_path),
        "url": url,
        "mode": mode,
        "target": target,
        "totals": {
            "samples": total,
            "correct": correct,
            "errors": errors,
            "accuracy": format_ratio(correct / total if total else 0.0),
            "errorRate": format_ratio(errors / total if total else 0.0),
            "reviewRate": rates["reviewRate"],
        },
        "qualityRates": rates,
        "violation": violation_metrics(results),
        "latencyMs": {
            "measure": latency_key,
            "meanAll": round(statistics.fmean(latencies), 3) if latencies else None,
            "meanSuccess": round(statistics.fmean(success_latencies), 3) if success_latencies else None,
            "p50": round(percentile(latencies, 0.50), 3) if latencies else None,
            "p95": round(percentile(latencies, 0.95), 3) if latencies else None,
            "p99": round(percentile(latencies, 0.99), 3) if latencies else None,
        },
        "perLabel": per_label,
        "macroF1": macro_f1,
        "l2Metrics": l2_metrics(results) if target == "l2" else None,
        "byGroup": by_group,
        "confusionMatrix": confusion,
        "failedSamples": [
            {
                "id": item["id"],
                "expectedDecision": item["expectedDecision"],
                "predictedDecision": item["predictedDecision"],
                "httpStatus": item["httpStatus"],
                "error": item["error"],
                "reason": item["reason"],
            }
            for item in results
            if item["expectedDecision"] != item["predictedDecision"] or not item["ok"]
        ],
    }


def quality_gate_failures(summary, args):
    rates = summary["qualityRates"]
    totals = summary["totals"]
    failures = []
    thresholds = (
        ("accuracy", totals["accuracy"], args.min_accuracy, "min"),
        ("macroF1", summary["macroF1"], args.min_macro_f1, "min"),
        ("rejectRecall", rates.get("rejectRecall"), args.min_reject_recall, "min"),
        ("riskyPassRate", rates.get("riskyPassRate"), args.max_risky_pass_rate, "max"),
        ("safeFalseRejectRate", rates.get("safeFalseRejectRate"), args.max_safe_false_reject_rate, "max"),
        ("reviewRate", rates.get("reviewRate"), args.max_review_rate, "max"),
    )
    for name, actual, threshold, comparator in thresholds:
        if threshold is None:
            continue
        if actual is None:
            if name == "rejectRecall":
                failures.append(f"{name} unavailable because there are no expected REJECT samples")
            else:
                failures.append(f"{name} unavailable because expectedViolation labels are missing")
        elif (comparator == "min" and actual < threshold) or (comparator == "max" and actual > threshold):
            failures.append(f"{name} {actual} violates {comparator} threshold {threshold}")
    return failures


def render_markdown(summary, gate_failures=None):
    lines = [
        "# Moderation Evaluation Report",
        "",
        f"- Input: `{summary['input']}`",
        f"- URL: `{summary['url']}`",
        f"- Mode: `{summary['mode']}`",
        f"- Target: `{summary.get('target', 'pipeline')}`",
        f"- Samples: `{summary['totals']['samples']}`",
        f"- Accuracy: `{summary['totals']['accuracy']}`",
        f"- Macro F1: `{summary['macroF1']}`",
        f"- Error Rate: `{summary['totals']['errorRate']}`",
        f"- REVIEW Rate: `{summary['totals']['reviewRate']}`",
    ]
    if summary.get("l2Metrics"):
        l2 = summary["l2Metrics"]
        lines.extend([
            "",
            "## L2 Routing and Contribution",
            "",
            "`PASS_TO_L3` is projected to `PASS` only for the shared three-class baseline above; "
            "the following metrics use the raw L2 decision.",
            "",
            f"- Routed to L3: `{l2['routedToL3']}` (`{l2['routeRate']}`)",
            f"- Terminal decisions: `{l2['terminalDecisions']}` (`{l2['coverageRate']}` coverage)",
            f"- Terminal accuracy: `{l2['terminalAccuracy']}`",
            f"- REJECT precision: `{l2['rejectPrecision']}`",
            f"- REJECT recall contribution: `{l2['rejectRecallContribution']}`",
            f"- Risky terminal coverage: `{l2['riskyTerminalCoverage']}`",
            f"- Safe false-reject rate: `{l2['safeFalseRejectRate']}`",
            f"- Safe terminal rate (REJECT or REVIEW): `{l2['safeTerminalRate']}`",
        ])
    lines.extend([
        "",
        "## Quality Rates",
        "",
        f"- REJECT recall on expected REJECT samples: `{summary['qualityRates']['rejectRecall']}`",
        f"- Risky samples incorrectly passed: `{summary['qualityRates']['riskyPassRate']}`",
        f"- Safe samples incorrectly not passed: `{summary['qualityRates']['safeFalseRejectRate']}`",
        "",
        "## Latency",
        "",
        f"- Measure: `{summary['latencyMs']['measure']}`",
        f"- Mean(all): `{summary['latencyMs']['meanAll']}` ms",
        f"- Mean(success): `{summary['latencyMs']['meanSuccess']}` ms",
        f"- P50: `{summary['latencyMs']['p50']}` ms",
        f"- P95: `{summary['latencyMs']['p95']}` ms",
        f"- P99: `{summary['latencyMs']['p99']}` ms",
        "",
        "## Per Label Metrics",
        "",
        "| Label | Precision | Recall | F1 | Support |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for label in LABELS:
        metrics = summary["perLabel"][label]
        lines.append(
            f"| {label} | {metrics['precision']} | {metrics['recall']} | "
            f"{metrics['f1']} | {metrics['support']} |"
        )

    if summary.get("violation"):
        violation = summary["violation"]
        lines.extend([
            "",
            "## Violation Metrics",
            "",
            f"- Labelled samples: `{violation['labelledSamples']}`",
            f"- Precision: `{violation['precision']}`",
            f"- Recall: `{violation['recall']}`",
            f"- F1: `{violation['f1']}`",
        ])

    lines.extend([
        "",
        "## Confusion Matrix",
        "",
        "| Expected \\ Predicted | REJECT | REVIEW | PASS | ERROR |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for expected in LABELS:
        row = summary["confusionMatrix"][expected]
        lines.append(f"| {expected} | {row['REJECT']} | {row['REVIEW']} | {row['PASS']} | {row['ERROR']} |")

    if summary["byGroup"]:
        lines.extend([
            "",
            "## Group Metrics",
            "",
            "| Group | Samples | Accuracy | Macro F1 | REVIEW Rate |",
            "| --- | ---: | ---: | ---: | ---: |",
        ])
        for group, metrics in summary["byGroup"].items():
            lines.append(f"| {group} | {metrics['samples']} | {metrics['accuracy']} | {metrics['macroF1']} | {metrics['qualityRates']['reviewRate']} |")

    lines.extend(["", "## Quality Gate", ""])
    if gate_failures:
        lines.append("- FAILED")
        lines.extend(f"- {failure}" for failure in gate_failures)
    else:
        lines.append("- No failed thresholds (or no thresholds configured).")

    failed_samples = summary["failedSamples"][:20]
    lines.extend(["", "## Failed Samples", ""])
    if not failed_samples:
        lines.append("- None")
    else:
        for item in failed_samples:
            lines.append(
                f"- `{item['id']}` expected={item['expectedDecision']} "
                f"predicted={item['predictedDecision']} http={item['httpStatus']} "
                f"error={item['error']} reason={item['reason']}"
            )
    return "\n".join(lines) + "\n"


def write_outputs(output_dir, summary, results, gate_failures=None):
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "report.md").write_text(
        render_markdown(summary, gate_failures), encoding="utf-8"
    )
    with (directory / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for item in results:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Wrote summary to {directory / 'summary.json'}")
    print(f"Wrote report to {directory / 'report.md'}")
    print(f"Wrote predictions to {directory / 'predictions.jsonl'}")


def main():
    args = parse_args()
    if args.timeout_seconds <= 0 or args.max_polls <= 0 or args.poll_interval_ms < 0:
        raise ValueError("timeout-seconds and max-polls must be positive; poll-interval-ms cannot be negative.")
    if args.target == "l2" and args.mode != "sync":
        raise ValueError("L2-only evaluation is synchronous; use --mode sync.")
    if args.mode == "async" and not args.task_url_template:
        raise ValueError("--task-url-template is required when --mode async.")
    records = load_records(args.input, require_frozen=args.require_frozen)
    if args.max_samples and args.max_samples > 0:
        records = records[: args.max_samples]
    if args.dry_run:
        summarize_dry_run(records, args.input)
        return 0

    if args.mode == "async":
        results = evaluate_async(
            records,
            args.url,
            args.task_url_template,
            args.timeout_seconds,
            args.poll_interval_ms,
            args.max_polls,
            input_path=args.input,
            asset_root=args.asset_root,
            request_namespace=args.request_namespace,
            target=args.target,
        )
    else:
        results = evaluate_sync(
            records,
            args.url,
            args.timeout_seconds,
            input_path=args.input,
            asset_root=args.asset_root,
            request_namespace=args.request_namespace,
            target=args.target,
        )
    summary = build_summary(results, args.url, args.input, args.mode, args.target)
    gate_failures = quality_gate_failures(summary, args)
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2))
    if args.output_dir:
        write_outputs(args.output_dir, summary, results, gate_failures)
    if gate_failures:
        print("Quality gate failed:", file=sys.stderr)
        for failure in gate_failures:
            print(f"  - {failure}", file=sys.stderr)
        if args.enforce_quality_gate:
            return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as exc:
        print(f"Input/configuration error: {exc}", file=sys.stderr)
        sys.exit(2)
