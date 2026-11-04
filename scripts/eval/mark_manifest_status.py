#!/usr/bin/env python3

"""给 image_manifest.md 的表格补一列「状态」，内容按 assets/ 目录里实际有什么算出来。

手工标注会过期——补一张图、删一张图，表里的状态就不准了。所以这里是重新生成的：
跑一次，整列按当前磁盘状态重写。补完图后再跑一次即可。

    python3 scripts/eval/mark_manifest_status.py            # 写入
    python3 scripts/eval/mark_manifest_status.py --check    # 只看统计，不改文件

状态取值：
    ✅ 已下载   检索来源，图片已抓到
    ✅ 已渲染   自制/合成，由 render_synthetic_images.py 产出
    ✅ 已合成   真实照片当底图 + 绘制元素叠加（spec 里有 photo）
    ⚠️ 示意图   已渲染，但 spec 里标了 approx（示意级近似，需人工确认）
    ⬜ 待摆拍   自制/合成，需实物摆拍，脚本不产出
    ⬜ 待下载   检索来源，图片还没抓
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "datasets/l3/eval/image_manifest.md"
ASSETS = REPO_ROOT / "datasets/l3/eval/assets"
SPEC = REPO_ROOT / "datasets/l3/eval/synthetic_spec.json"

STATUS_COLUMN = "状态"
PHOTO_TEMPLATE = "photo"
STATUS_VALUES = {"✅ 已下载", "✅ 已渲染", "✅ 已合成", "✅ 已摆拍",
                 "⚠️ 示意图", "⬜ 待合成", "⬜ 待摆拍", "⬜ 待下载"}


def photo_base_exists(entry):
    """底图是否已经在 assets/photos/ 里（slug 规则要和另两个脚本一致）。"""
    query = ((entry or {}).get("photo") or {}).get("query") or ""
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") or "photo"
    return (ASSETS / "photos" / f"{slug}.jpg").exists()


def load_spec():
    if not SPEC.exists():
        return {}
    raw = json.loads(SPEC.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def status_for(rid, spec):
    exists = (ASSETS / f"{rid}.jpg").exists()
    entry = spec.get(rid)
    if exists:
        if entry is None:
            return "✅ 已下载"                      # 检索来源
        # 人工提供的（spec 标了 supplied，或本来就要求摆拍但已有图）
        if entry.get("supplied") or entry.get("template") == PHOTO_TEMPLATE:
            return "✅ 已摆拍"
        # 照片底图合成：底图是真实照片、叠加的是绘制元素，和纯渲染要分开标
        if entry.get("photo"):
            return "✅ 已合成"
        return "⚠️ 示意图" if entry.get("approx") else "✅ 已渲染"
    if entry is None:
        return "⬜ 待下载"
    if entry.get("photo") and not photo_base_exists(entry):
        return "⬜ 待合成"                            # 底图还没抓
    return "⬜ 待摆拍"


def split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--check", action="store_true", help="只统计，不写入文件")
    args = parser.parse_args()

    spec = load_spec()
    lines = args.manifest.read_text(encoding="utf-8").splitlines()
    out, counts = [], {}
    ncols = 6  # 表头列数（含状态列）；遇到表头行会被刷新

    for line in lines:
        if not line.startswith("|"):
            out.append(line)
            continue

        cells = split_row(line)
        first = cells[0] if cells else ""

        # 幂等：重跑时先摘掉上一次留下的状态列（表头写的是列名，数据行写的是取值）
        if cells and cells[-1] in STATUS_VALUES | {STATUS_COLUMN}:
            cells = cells[:-1]
            line = "| " + " | ".join(cells) + " |"

        if set(first) <= set("-: ") and first:          # 分隔行：按表头列数重建
            out.append("| " + " | ".join(["---"] * ncols) + " |")
            continue
        if first == "id":                                # 表头
            out.append(line + f" {STATUS_COLUMN} |")
            ncols = len(cells) + 1
            continue
        if not first.startswith("l3-"):                  # 其他表格行，原样保留
            out.append(line)
            continue

        status = status_for(first, spec)
        counts[status] = counts.get(status, 0) + 1
        out.append(line + f" {status} |")

    total = sum(counts.values())
    print(f"清单共 {total} 条：")
    for status, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {status}  {n}")

    if args.check:
        print("\n--check 模式，未修改文件。")
        return 0

    args.manifest.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"\n已更新 {args.manifest.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
