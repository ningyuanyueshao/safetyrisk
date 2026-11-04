#!/usr/bin/env python3

"""生成 L3 评测集的图片核对表（HTML），把清单描述和实际图片并排放在一起。

素材库的检索结果经常图文不符（要「树叶拉花」返回普通卡布奇诺，要「海边日落」
返回带摄影师水印的白天港口），渲染图也可能是示意级近似。脚本没法自动判断这些，
所以出这张表让人工逐张过一眼。

    python3 scripts/eval/build_contact_sheet.py
    python3 scripts/eval/build_contact_sheet.py --only-missing     # 只看还缺的

输出 datasets/l3/eval/assets/contact_sheet_all.html，用浏览器打开。
页面顶部有筛选按钮，可以直接切到「缺图」「待确认」。

注意：图片用的是相对于该 HTML 文件所在目录的路径（HTML 就在 assets/ 里），
不要再拼一层 assets/ 前缀，否则浏览器会去找 assets/assets/xxx.jpg。
"""

import argparse
import html
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = REPO_ROOT / "datasets/l3/eval"
MANIFEST = BASE / "image_manifest.md"
ASSETS = BASE / "assets"
SPEC = BASE / "synthetic_spec.json"
OUTPUT = ASSETS / "contact_sheet_all.html"

DECISION_COLOR = {"PASS": "#1b7f3b", "REJECT": "#b3261e", "REVIEW": "#8a6d00"}
STATUS_VALUES = {"✅ 已下载", "✅ 已渲染", "✅ 已合成", "✅ 已摆拍",
                 "⚠️ 示意图", "⬜ 待合成", "⬜ 待摆拍", "⬜ 待下载"}
PHOTO_TEMPLATE = "photo"


def parse_manifest(path):
    """读清单表格。状态列可能还没生成，所以按列数自适应。"""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or not cells[0].startswith("l3-"):
            continue
        status = cells[5] if len(cells) >= 6 and cells[5] in STATUS_VALUES else ""
        rows.append({
            "id": cells[0], "decision": cells[1], "description": cells[2],
            "how": cells[3], "note": cells[4], "status": status,
        })
    return rows


def load_spec():
    if not SPEC.exists():
        return {}
    raw = json.loads(SPEC.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def build_cards(rows, spec):
    cards, have, missing, approx, composed = [], 0, 0, 0, 0
    for r in rows:
        rid = r["id"]
        exists = (ASSETS / f"{rid}.jpg").exists()
        entry = spec.get(rid, {})
        # 人工提供的图不算示意级——approx 只是渲染版才有的属性
        is_approx = bool(entry.get("approx")) and not entry.get("supplied")
        is_composed = bool(entry.get("photo"))

        if exists:
            have += 1
            # 相对路径：HTML 本身就在 assets/ 下，直接用文件名
            img = f'<img src="{html.escape(rid)}.jpg" loading="lazy" alt="{html.escape(rid)}">'
        else:
            missing += 1
            img = '<div class="miss">缺图</div>'
        if is_approx:
            approx += 1
        if is_composed:
            composed += 1

        if entry:
            manual = entry.get("supplied") or entry.get("template") == PHOTO_TEMPLATE
            source = "摆拍" if manual else ("合成" if is_composed else "渲染")
        else:
            source = "检索"
        tags = f'<span class="tag">{source}</span>'
        if is_approx:
            tags += '<span class="tag warn">示意级</span>'

        if not exists:
            bucket = "missing"
        elif is_composed:
            bucket = "composed"
        elif is_approx:
            bucket = "approx"
        else:
            bucket = "done"

        cards.append(
            f'<div class="card" data-bucket="{bucket}" '
            f'style="border-color:{DECISION_COLOR.get(r["decision"], "#888")}">'
            f'{img}<div class="meta">'
            f'<div class="id">{html.escape(rid)} {tags}</div>'
            f'<div class="dec" style="color:{DECISION_COLOR.get(r["decision"], "#888")}">'
            f'{html.escape(r["decision"])}</div>'
            f'<div class="desc">{html.escape(r["description"])}</div>'
            f'</div></div>'
        )
    return "".join(cards), have, missing, approx, composed


TEMPLATE = """<!doctype html>
<meta charset="utf-8"><title>L3 图片核对表</title>
<style>
body{{font-family:-apple-system,"PingFang SC",sans-serif;margin:0;padding:24px;background:#fafafa}}
h1{{font-size:20px;margin:0 0 12px}}
.bar{{position:sticky;top:0;background:#fafafa;padding:10px 0;font-size:14px;color:#444;z-index:9;
     display:flex;gap:10px;align-items:center;flex-wrap:wrap;border-bottom:1px solid #ddd}}
button{{font:inherit;padding:5px 14px;border:1px solid #bbb;border-radius:6px;background:#fff;cursor:pointer}}
button.on{{background:#333;color:#fff;border-color:#333}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin-top:16px}}
.card{{background:#fff;border:2px solid #888;border-radius:8px;overflow:hidden;display:flex;flex-direction:column}}
.card img{{width:100%;height:210px;object-fit:contain;background:#f0f0f0}}
.miss{{height:210px;display:flex;align-items:center;justify-content:center;
      background:#ffe9e9;color:#b3261e;font-weight:600}}
.meta{{padding:8px 10px;font-size:12px;line-height:1.5}}
.id{{font-weight:600;font-family:ui-monospace,monospace}}
.dec{{font-weight:700;margin:2px 0}}
.desc{{color:#333}}
.tag{{background:#eceff1;border-radius:4px;padding:1px 5px;font-weight:400;margin-left:4px}}
.tag.warn{{background:#fff3cd}}
</style>
<h1>L3 评测集图片核对表</h1>
<div class="bar">
  <span>共 {total} 条 · 已有 {have} · 缺 {missing} · 合成 {composed} · 示意级 {approx}</span>
  <button class="on" data-f="all">全部</button>
  <button data-f="missing">只看缺图</button>
  <button data-f="composed">只看合成图</button>
  <button data-f="approx">只看示意级</button>
  <button data-f="done">只看已完成</button>
</div>
<div class="grid">{cards}</div>
<script>
document.querySelectorAll('.bar button').forEach(function (b) {{
  b.onclick = function () {{
    document.querySelectorAll('.bar button').forEach(function (x) {{ x.classList.remove('on'); }});
    b.classList.add('on');
    var f = b.dataset.f;
    document.querySelectorAll('.card').forEach(function (c) {{
      c.style.display = (f === 'all' || c.dataset.bucket === f) ? '' : 'none';
    }});
  }};
}});
</script>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--only-missing", action="store_true",
                        help="只输出还缺图的条目。")
    args = parser.parse_args()

    rows = parse_manifest(args.manifest)
    if not rows:
        raise SystemExit(f"没能从 {args.manifest} 解析出任何条目，检查表格格式。")

    if args.only_missing:
        rows = [r for r in rows if not (ASSETS / f"{r['id']}.jpg").exists()]

    spec = load_spec()
    cards, have, missing, approx, composed = build_cards(rows, spec)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        TEMPLATE.format(total=len(rows), have=have, missing=missing,
                        approx=approx, composed=composed, cards=cards),
        encoding="utf-8")

    print(f"共 {len(rows)} 条：已有 {have}，缺 {missing}，合成 {composed}，示意级 {approx}")
    print(f"→ {args.output.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
