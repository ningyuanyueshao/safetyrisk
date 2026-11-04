import json
import unittest
from argparse import Namespace
from unittest.mock import patch

from evaluate_moderation_dataset import (
    build_payload,
    build_summary,
    evaluate_async,
    extract_prediction,
    l2_metrics,
    quality_gate_failures,
    validate_record,
)


class EvaluateModerationDatasetTest(unittest.TestCase):
    def test_request_namespace_avoids_cache_reuse_without_changing_content(self):
        record = {
            "id": "safe-1",
            "contentType": "TEXT",
            "content": "原始标注内容",
            "expectedDecision": "PASS",
        }
        payload = build_payload(record, request_namespace="run-001")
        self.assertEqual(payload["content"], "原始标注内容")
        self.assertEqual(payload["userId"], "eval:run-001")

    def test_request_namespace_does_not_override_dataset_user_id(self):
        record = {
            "id": "blocked-1",
            "contentType": "TEXT",
            "content": "内容",
            "userId": "blocked-user-001",
            "expectedDecision": "REJECT",
        }
        payload = build_payload(record, request_namespace="run-001")
        self.assertEqual(payload["userId"], "blocked-user-001")

    def test_summary_contains_group_and_violation_metrics(self):
        results = [
            {
                "id": "safe-1",
                "scene": "safe",
                "category": "general",
                "contentType": "TEXT",
                "expectedDecision": "PASS",
                "predictedDecision": "PASS",
                "expectedViolation": False,
                "predictedViolation": False,
                "ok": True,
                "latencyMs": 10.0,
                "httpStatus": 200,
                "error": None,
                "reason": "ok",
            },
            {
                "id": "risk-1",
                "scene": "fraud",
                "category": "fraud",
                "contentType": "TEXT",
                "expectedDecision": "REJECT",
                "predictedDecision": "REVIEW",
                "expectedViolation": True,
                "predictedViolation": True,
                "ok": True,
                "latencyMs": 20.0,
                "httpStatus": 200,
                "error": None,
                "reason": "review",
            },
        ]
        summary = build_summary(results, "http://fixture", "fixture.jsonl")
        self.assertEqual(summary["totals"]["accuracy"], 0.5)
        self.assertEqual(summary["qualityRates"]["rejectRecall"], 0.0)
        self.assertEqual(summary["qualityRates"]["riskyPassRate"], 0.0)
        self.assertEqual(summary["violation"]["f1"], 1.0)
        self.assertIn("contentType=TEXT", summary["byGroup"])
        self.assertIn("scene=fraud", summary["byGroup"])

    def test_quality_gate_reports_missing_violation_labels(self):
        results = [
            {
                "id": "one",
                "contentType": "TEXT",
                "expectedDecision": "PASS",
                "predictedDecision": "PASS",
                "expectedViolation": None,
                "predictedViolation": False,
                "ok": True,
                "latencyMs": 1.0,
                "httpStatus": 200,
                "error": None,
                "reason": None,
            }
        ]
        summary = build_summary(results, "http://fixture", "fixture.jsonl")
        args = Namespace(
            min_accuracy=0.99,
            min_macro_f1=None,
            min_reject_recall=0.9,
            max_risky_pass_rate=None,
            max_safe_false_reject_rate=None,
            max_review_rate=None,
        )
        failures = quality_gate_failures(summary, args)
        self.assertIn("rejectRecall unavailable", " ".join(failures))

    def test_async_evaluation_uses_terminal_result_and_e2e_latency(self):
        records = [
            {
                "id": "async-risk",
                "contentType": "TEXT",
                "content": "内容",
                "expectedDecision": "REJECT",
                "expectedViolation": True,
            }
        ]
        submit = {
            "httpStatus": 200,
            "ok": True,
            "latencyMs": 1.0,
            "body": {"taskId": "fixture-task-001", "status": "PENDING"},
            "error": None,
        }
        terminal = {
            "httpStatus": 200,
            "ok": True,
            "latencyMs": 2.0,
            "body": {
                "taskId": "fixture-task-001",
                "status": "COMPLETED",
                "decision": "REJECT",
                "violation": True,
                "confidence": 0.98,
                "reason": "fixture",
            },
            "error": None,
        }
        with patch("evaluate_moderation_dataset.call_http", side_effect=[submit, terminal]):
            results = evaluate_async(
                records,
                "http://fixture/submit",
                "http://fixture/tasks/{taskId}",
                timeout_seconds=2.0,
                poll_interval_ms=0,
                max_polls=2,
            )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[0]["predictedDecision"], "REJECT")
        self.assertEqual(results[0]["status"], "COMPLETED")
        self.assertGreaterEqual(results[0]["e2eLatencyMs"], 0.0)

    def test_require_frozen_rejects_draft_record(self):
        with self.assertRaises(ValueError):
            validate_record(
                {
                    "id": "draft",
                    "contentType": "TEXT",
                    "content": "内容",
                    "expectedDecision": "PASS",
                    "annotationStatus": "DRAFT",
                },
                1,
                require_frozen=True,
            )

    def test_l2_route_is_projected_to_pass_but_retained_for_coverage(self):
        self.assertEqual(extract_prediction({"decision": "PASS_TO_L3"}, target="l2"), "PASS")
        results = [
            {
                "expectedDecision": "PASS",
                "expectedViolation": False,
                "rawL2Decision": "PASS_TO_L3",
            },
            {
                "expectedDecision": "REJECT",
                "expectedViolation": True,
                "rawL2Decision": "REJECT",
            },
            {
                "expectedDecision": "REJECT",
                "expectedViolation": True,
                "rawL2Decision": "PASS_TO_L3",
            },
        ]

        metrics = l2_metrics(results)

        self.assertEqual(metrics["routedToL3"], 2)
        self.assertEqual(metrics["terminalDecisions"], 1)
        self.assertEqual(metrics["terminalAccuracy"], 1.0)
        self.assertEqual(metrics["rejectPrecision"], 1.0)
        self.assertEqual(metrics["rejectRecallContribution"], 0.5)
        self.assertEqual(metrics["safeFalseRejectRate"], 0.0)


if __name__ == "__main__":
    unittest.main()
