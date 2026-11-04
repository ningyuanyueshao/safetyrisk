#!/usr/bin/env python3
"""
读取 JMeter .jtl（CSV 或 XML），输出中文压测摘要。
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass
class Sample:
    ts_ms: int
    elapsed_ms: float
    success: bool
    label: str
    response_code: str
    response_message: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="读取 JMeter .jtl 并生成中文摘要"
    )
    parser.add_argument("jtl", help=".jtl 文件路径（CSV 或 XML）")
    parser.add_argument(
        "-o",
        "--output",
        help="摘要输出文件路径（默认仅打印到终端）",
    )
    parser.add_argument("--target-p95-ms", type=float, default=None, help="P95 目标阈值（毫秒）")
    parser.add_argument("--target-p99-ms", type=float, default=None, help="P99 目标阈值（毫秒）")
    parser.add_argument(
        "--target-error-rate",
        type=float,
        default=None,
        help="错误率目标阈值（百分比，例如 1 表示 1%%）",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="最慢接口和高错误接口展示数量（默认 5）",
    )
    return parser.parse_args()


def parse_timestamp_to_ms(value: str) -> int:
    raw = (value or "").strip()
    if not raw:
        return 0
    if raw.isdigit():
        num = int(raw)
        if num > 10_000_000_000:
            return num
        return num * 1000

    # 兼容部分非标准导出格式
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    try:
        return int(datetime.fromisoformat(raw).timestamp() * 1000)
    except ValueError:
        return 0


def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def parse_float(value: str) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def percentile(values: Iterable[float], p: float) -> float:
    arr = sorted(values)
    if not arr:
        return 0.0
    if p <= 0:
        return arr[0]
    if p >= 100:
        return arr[-1]
    rank = math.ceil((p / 100.0) * len(arr)) - 1
    rank = min(max(rank, 0), len(arr) - 1)
    return arr[rank]


def load_samples_csv(path: str) -> list[Sample]:
    samples: list[Sample] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            samples.append(
                Sample(
                    ts_ms=parse_timestamp_to_ms(row.get("timeStamp", "")),
                    elapsed_ms=parse_float(row.get("elapsed", "0")),
                    success=parse_bool(row.get("success", "")),
                    label=(row.get("label") or "UNKNOWN").strip(),
                    response_code=(row.get("responseCode") or "").strip(),
                    response_message=(row.get("responseMessage") or "").strip(),
                )
            )
    return samples


def load_samples_xml(path: str) -> list[Sample]:
    samples: list[Sample] = []
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag not in {"httpSample", "sample"}:
            continue
        samples.append(
            Sample(
                ts_ms=parse_timestamp_to_ms(elem.attrib.get("ts", "0")),
                elapsed_ms=parse_float(elem.attrib.get("t", "0")),
                success=parse_bool(elem.attrib.get("s", "false")),
                label=(elem.attrib.get("lb", "UNKNOWN") or "UNKNOWN").strip(),
                response_code=(elem.attrib.get("rc", "") or "").strip(),
                response_message=(elem.attrib.get("rm", "") or "").strip(),
            )
        )
        elem.clear()
    return samples


def is_xml_file(path: str) -> bool:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        head = f.read(256).lstrip()
    return head.startswith("<")


def fmt_ms(value: float) -> str:
    return f"{value:,.2f} ms"


def fmt_pct(value: float) -> str:
    return f"{value:.2f}%"


def evaluate_thresholds(
    p95: float,
    p99: float,
    err_rate: float,
    target_p95: float | None,
    target_p99: float | None,
    target_err: float | None,
) -> tuple[str, list[str]]:
    checks: list[str] = []
    failed = False

    if target_p95 is not None:
        ok = p95 <= target_p95
        failed = failed or (not ok)
        checks.append(f"P95 <= {target_p95} ms: {'通过' if ok else '不通过'}")
    if target_p99 is not None:
        ok = p99 <= target_p99
        failed = failed or (not ok)
        checks.append(f"P99 <= {target_p99} ms: {'通过' if ok else '不通过'}")
    if target_err is not None:
        ok = err_rate <= target_err
        failed = failed or (not ok)
        checks.append(f"错误率 <= {target_err}%: {'通过' if ok else '不通过'}")

    if not checks:
        return "未设置阈值", checks
    return ("不通过" if failed else "通过"), checks


def build_report(samples: list[Sample], args: argparse.Namespace) -> str:
    if not samples:
        return "未读取到任何样本，请检查 .jtl 文件是否为空。"

    latencies = [s.elapsed_ms for s in samples]
    total = len(samples)
    success = sum(1 for s in samples if s.success)
    failed = total - success
    error_rate = (failed / total) * 100 if total else 0.0

    ts_values = [s.ts_ms for s in samples if s.ts_ms > 0]
    if len(ts_values) >= 2:
        duration_sec = max((max(ts_values) - min(ts_values)) / 1000.0, 0.001)
    else:
        duration_sec = 0.0
    throughput = (total / duration_sec) if duration_sec > 0 else 0.0

    avg = statistics.fmean(latencies)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)

    by_label: dict[str, list[Sample]] = defaultdict(list)
    for s in samples:
        by_label[s.label].append(s)

    slow_labels: list[tuple[str, float, float, int]] = []
    err_labels: list[tuple[str, float, int]] = []
    for label, group in by_label.items():
        group_lats = [x.elapsed_ms for x in group]
        group_p95 = percentile(group_lats, 95)
        group_avg = statistics.fmean(group_lats)
        group_cnt = len(group)
        group_err = sum(1 for x in group if not x.success)
        group_err_rate = (group_err / group_cnt) * 100.0
        slow_labels.append((label, group_p95, group_avg, group_cnt))
        err_labels.append((label, group_err_rate, group_cnt))

    slow_labels.sort(key=lambda x: x[1], reverse=True)
    err_labels.sort(key=lambda x: (x[1], x[2]), reverse=True)

    verdict, checks = evaluate_thresholds(
        p95=p95,
        p99=p99,
        err_rate=error_rate,
        target_p95=args.target_p95_ms,
        target_p99=args.target_p99_ms,
        target_err=args.target_error_rate,
    )

    lines: list[str] = []
    lines.append("# 压测中文摘要")
    lines.append("")
    lines.append("## 总览")
    lines.append(f"- 样本总数：{total}")
    lines.append(f"- 成功数：{success}")
    lines.append(f"- 失败数：{failed}")
    lines.append(f"- 错误率：{fmt_pct(error_rate)}")
    lines.append(f"- 平均耗时：{fmt_ms(avg)}")
    lines.append(f"- P95：{fmt_ms(p95)}")
    lines.append(f"- P99：{fmt_ms(p99)}")
    lines.append(f"- 吞吐量：{throughput:,.2f} req/s")
    if duration_sec > 0:
        lines.append(f"- 测试时长：{duration_sec:,.2f} s")
    else:
        lines.append("- 测试时长：无法可靠计算（缺少有效 timeStamp）")
    lines.append("")
    lines.append("## 达标判断")
    lines.append(f"- 结论：{verdict}")
    if checks:
        for c in checks:
            lines.append(f"- {c}")
    else:
        lines.append("- 未传入阈值参数，仅做统计展示。")
    lines.append("")
    lines.append("## 最慢接口（按 P95）")
    for label, lp95, lavg, cnt in slow_labels[: max(args.top, 1)]:
        lines.append(f"- {label}：P95={fmt_ms(lp95)}，平均={fmt_ms(lavg)}，样本={cnt}")
    lines.append("")
    lines.append("## 高错误接口（按错误率）")
    for label, lerr, cnt in err_labels[: max(args.top, 1)]:
        lines.append(f"- {label}：错误率={fmt_pct(lerr)}，样本={cnt}")
    lines.append("")
    lines.append("## 说明")
    lines.append("- 该摘要基于 JTL 请求级数据计算。")
    lines.append("- 业务字段（如 decision=REVIEW 占比）通常不在 JTL 默认字段中，需结合服务日志或业务指标面板查看。")

    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    if not os.path.exists(args.jtl):
        print(f"文件不存在：{args.jtl}", file=sys.stderr)
        return 1

    samples = load_samples_xml(args.jtl) if is_xml_file(args.jtl) else load_samples_csv(args.jtl)
    report = build_report(samples, args)
    print(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
            if not report.endswith("\n"):
                f.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
