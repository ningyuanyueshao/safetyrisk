#!/usr/bin/env python3

"""Fetch the L3 eval dataset images that the manifest marks as 检索 (searchable).

Reads datasets/l3/eval/image_manifest.md, takes the rows whose 获取方式 column starts
with 检索, queries a stock image API for each keyword, and writes the results to
datasets/l3/eval/assets/<id>.jpg.

Rows marked 自制 / 自制/合成 are skipped on purpose — those are the risky samples that
must be produced synthetically, not downloaded.

Provenance for every downloaded image (source page, author, license, query) is written
to assets/fetch_report.json, which the freeze checklist requires.

Usage:
    # 看看会查哪些词、哪些已下载、哪些还缺
    python3 scripts/eval/fetch_manifest_images.py --check

    # 正式抓取（Pexels 需要 key，见下）
    export PEXELS_API_KEY=xxxx
    python3 scripts/eval/fetch_manifest_images.py

    # 抓完生成一张对照表，人工核对图文是否相符
    python3 scripts/eval/fetch_manifest_images.py --contact-sheet

    # 只补某几条 / 只跑前 5 条 / 强制重下
    python3 scripts/eval/fetch_manifest_images.py --only l3-img-pass
    python3 scripts/eval/fetch_manifest_images.py --limit 5
    python3 scripts/eval/fetch_manifest_images.py --overwrite

渲染图的照片底图（--bases）：
    见 synthetic_spec.json 里带 photo.query 的条目。这些是「示意级近似」样本的
    真实照片底图——渲染时用照片当画布，再把画出来的元素叠上去。

    python3 scripts/eval/fetch_manifest_images.py --bases --check   # 看会搜哪些词
    python3 scripts/eval/fetch_manifest_images.py --bases           # 抓到 assets/photos/

    **检索词只能描述场景、器物或材质，不能描述风险概念。**
    搜 kitchen countertop 再画一把刀 = 对；搜 knife 拿回一张真实凶器照片 = 违规。
    脚本里 FORBIDDEN_QUERY_WORDS 做硬校验，命中直接报错退出。

获取检索源 key：
    Pexels   https://www.pexels.com/api/          免费，200 请求/小时
    Unsplash https://unsplash.com/developers      免费，50 请求/小时（demo 档偏少）

没配 key 时会退回 Wikimedia Commons。能跑通，但图片质量与关键词匹配度明显更差，
只适合应急。抓完务必要跑 --contact-sheet 人工扫一遍。
"""

import argparse
import html
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "datasets/l3/eval/image_manifest.md"
SPEC = REPO_ROOT / "datasets/l3/eval/synthetic_spec.json"
ASSETS = REPO_ROOT / "datasets/l3/eval/assets"
REPORT = ASSETS / "fetch_report.json"
PHOTO_REPORT = ASSETS / "photo_report.json"
CONTACT_SHEET = ASSETS / "contact_sheet.html"

# 本地 .env 回退：PEXELS_API_KEY 通常配在这里，而不是 shell 环境里。
ENV_FILE = REPO_ROOT / "infra/docker/.env"

# 底图检索词的红线。底图只能描述**场景、器物或材质**，不能描述风险概念本身：
# 搜 kitchen countertop 然后画一把刀是可以的；搜 knife 拿回一张真实凶器照片是违规的。
# 这份词表是硬校验——命中就报错退出，不静默跳过，免得日后有人图省事直接搜敏感词。
FORBIDDEN_QUERY_WORDS = (
    # 伤口 / 血迹 / 尸体
    "wound", "wounded", "blood", "bloody", "injur", "gore", "corpse", "mutilat",
    "laceration", "scar",
    # 武器 / 管制器具
    "gun", "weapon", "rifle", "pistol", "firearm", "ammo", "bullet", "knife", "blade",
    "dagger", "machete", "sword", "crossbow", "grenade",
    # 毒品 / 药品滥用
    "drug", "cocaine", "heroin", "meth", "cannabis", "marijuana", "narcotic", "opium",
    "syringe", "needle", "bong", "paraphernalia",
    # 色情 / 暴露
    "nude", "nudity", "naked", "erotic", "porn", "lingerie", "bikini", "topless",
    "sensual", "seductive",
    # 极端主义 / 仇恨
    "swastika", "nazi", "extremist",
    # 赌博
    "casino", "gambling", "betting", "poker chip",
)
FORBIDDEN_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in FORBIDDEN_QUERY_WORDS) + r")",
                          re.IGNORECASE)

MAX_EDGE = 1280          # 长边上限
JPEG_QUALITY = 88
USER_AGENT = "multimodel-safetyrisk-l3-eval/1.0 (internal eval dataset)"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

# 清单里有 4 条中文关键词，Pexels / Wikimedia 都以英文检索为主，这里手工映射。
ZH_QUERY = {
    "青海 227 国道 油菜花 公路": "qinghai highway rapeseed flower field road",
    "牛肉面 拉面 餐桌 特写": "beef noodle soup bowl table closeup",
    "保温杯 办公桌 热水": "thermos bottle office desk",
    "番茄炒蛋 家常菜 摆盘": "scrambled eggs tomato home cooking plate",
}

# 许可白名单 / 黑名单（用于 Wikimedia 回退源）
PERMISSIVE_MARKERS = ("cc0", "public domain", "pdm", "no restrictions",
                      "cc by 2.0", "cc by 3.0", "cc by 4.0")
COPYLEFT_MARKERS = ("-sa", "sharealike", "share-alike", "-nc", "-nd", "gfdl", "fair use")

# 不要拿这些当配图：素材图库的占位图和明显跑偏的内容
BAD_TITLE_WORDS = ("logo", "icon", "clipart", "watermark", "screenshot of", "scan of")


class FatalApiError(Exception):
    """配置或配额问题，继续跑下去没有意义，直接中断。"""


# --------------------------------------------------------------------------- manifest

def parse_manifest(path):
    """抽出所有 获取方式 以「检索」开头的行。"""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or not cells[0].startswith("l3-"):
            continue
        rid, decision, description, how = cells[0], cells[1], cells[2], cells[3]
        # 必须是以「检索」开头；「自制/合成：不要检索真实素材」这类要排除
        if not how.startswith("检索"):
            continue
        match = re.search(r"「([^」]*)」", how)
        if not match:
            print(f"  ! {rid} 标记为检索但没有解析出关键词，跳过", file=sys.stderr)
            continue
        keyword = match.group(1).strip()
        rows.append({
            "id": rid,
            "decision": decision,
            "description": description,
            "keyword": ZH_QUERY.get(keyword, keyword),
            "raw_keyword": keyword,
        })
    return rows


# --------------------------------------------------------------------------- 底图（photo base）

def slugify(text):
    """检索词 -> 文件名。同一 query 共用一张底图，所以文件名要能反推回 query。

    注意 `pick`（选第几个结果）**不进 slug**：一个 query 对应一张底图，换 pick
    就是要覆盖那张，重抓时加 `--overwrite` 即可。渲染器那边只用 slug 找文件，
    所以这个函数必须和 render_synthetic_images.py 里的同名函数保持一致。
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "photo"


# 一个底图检索需求：一个 query 一张图，可能被多条样本共用。
PhotoQuery = namedtuple("PhotoQuery", "slug query orientation ids pick")


def load_env_file(path=ENV_FILE):
    """从 .env 补环境变量（不覆盖已有的）。没引 python-dotenv，这点解析够用了。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def orientation_for(cfg, fallback=None):
    """底图的构图方向：优先 spec 里写死的，否则按目标尺寸推。

    横图配竖底图会被裁掉大半，所以这里让目标尺寸说话。
    """
    photo = cfg.get("photo") or {}
    if photo.get("orientation"):
        return photo["orientation"]
    size = cfg.get("size")
    if not size or len(size) != 2:
        return fallback
    w, h = size
    if w > h * 1.15:
        return "landscape"
    if h > w * 1.15:
        return "portrait"
    return "square"


def load_spec_photos(spec_path):
    """从渲染规格里收集所有 photo.query，返回 [PhotoQuery, ...]。

    规格是底图的唯一事实来源——底图是渲染器的东西，跟 image_manifest 无关。

    `photo.pick` 是**选第几个检索结果**（1 起）。抓回来的图不对（有人脸、品牌、
    水印、或者根本不是那个场景）时用它换一张，而不是改检索词——改词往往只是
    换回同一类图，问题照旧。
    """
    if not spec_path.exists():
        raise SystemExit(f"缺少渲染规格文件：{spec_path}")
    raw = json.loads(spec_path.read_text(encoding="utf-8"))

    grouped = {}
    for rid, cfg in raw.items():
        if rid.startswith("_") or not isinstance(cfg, dict):
            continue
        photo = cfg.get("photo") or {}
        query = (photo.get("query") or "").strip()
        if not query:
            continue
        slug = slugify(query)
        entry = grouped.setdefault(slug, {"query": query, "orientation": None,
                                          "ids": [], "picks": set()})
        entry["ids"].append(rid)
        entry["orientation"] = entry["orientation"] or orientation_for(cfg)
        entry["picks"].add(int(photo.get("pick") or 0))

    entries = []
    for slug, v in sorted(grouped.items()):
        if len(v["picks"]) > 1:
            # 同一张底图不可能同时是第 2 和第 5 个结果。要么统一 pick，
            # 要么把检索词改得足够不同，让它们各自落到不同的 slug 上。
            raise SystemExit(
                f"检索词 {v['query']!r} 被多条样本用，但 pick 不一致："
                f"{sorted(v['picks'])}（涉及 {', '.join(sorted(v['ids']))}）。\n"
                "同一 query 共用一张底图，pick 只能有一个值。"
            )
        entries.append(PhotoQuery(slug, v["query"], v["orientation"],
                                  sorted(v["ids"]), v["picks"].pop()))
    return entries


def check_queries(entries):
    """检索词红线校验。在这批词被拿去检索之前就要过掉。"""
    for e in entries:
        hit = FORBIDDEN_RE.search(e.query)
        if not hit:
            continue
        raise SystemExit(
            f"\n检索词违规：{e.query!r}（命中 {hit.group(0)!r}）\n"
            f"  用在：{', '.join(e.ids)}\n\n"
            "  照片底图只能描述**场景、器物或材质**（台面、墙面、桌面、房间、纸张纹理……），\n"
            "  不能描述风险概念本身。搜 kitchen countertop 再画一把刀 = 对；\n"
            "  搜 knife 拿回一张真实凶器照片 = 违规，会引入真实敏感素材。\n"
            "  请改写成无害的环境描述后重跑。"
        )


def fetch_bases(args):
    """抓渲染图用的照片底图，存到 assets/photos/<slug>.jpg。"""
    photos_dir = args.assets_dir / "photos"
    report_path = args.assets_dir / "photo_report.json"

    entries = load_spec_photos(args.spec)
    if not entries:
        raise SystemExit(
            f"规格 {args.spec} 里没有任何 photo.query，没有底图要抓。\n"
            "先给「示意级近似」的条目加上 photo 字段。"
        )

    # 红线校验跑在 --only 过滤之前：不能靠过滤把违规词筛掉
    check_queries(entries)

    if args.only:
        entries = [e for e in entries if any(args.only in i for i in e.ids)]
        if not entries:
            raise SystemExit(f"没有 id 匹配 {args.only!r} 的底图条目。")
    if args.limit:
        entries = entries[: args.limit]

    have = [e for e in entries if (photos_dir / f"{e.slug}.jpg").exists()]
    print(f"底图共 {len(entries)} 个检索词；已下载 {len(have)}，缺 {len(entries) - len(have)}")
    print(f"（对应 spec 里 {sum(len(e.ids) for e in entries)} 条样本）\n")

    if args.check or args.dry_run:
        for e in entries:
            mark = "  " if (photos_dir / f"{e.slug}.jpg").exists() else "缺"
            pick = f"  pick={e.pick}" if e.pick else ""
            print(f"  [{mark}] {e.slug}.jpg  <-  {e.query}  "
                  f"[{e.orientation or '任意'}]{pick}  ← {', '.join(e.ids)}")
        return 0

    primary, api_key = resolve_provider(args)
    photos_dir.mkdir(parents=True, exist_ok=True)
    # 一定要读回已有报告再合并：--overwrite 指的是「重下图片文件」，不是「清空来源记录」。
    # 之前写成 overwrite 就置空，结果 --overwrite --only X 跑一次就把其余条目的
    # 来源记录全抹了（图片还在，出处没了）。
    report = (json.loads(report_path.read_text(encoding="utf-8"))
              if report_path.exists() else {})

    used_ids = set()  # 跨查询去重：两个词撞到同一张照片时错开
    ok = skipped = failed = 0
    failures = []

    try:
        for index, e in enumerate(entries, start=1):
            slug, query, orientation, ids, pick = e
            dest = photos_dir / f"{slug}.jpg"
            if dest.exists() and not args.overwrite:
                skipped += 1
                continue

            print(f"[{index}/{len(entries)}] {slug}  <-  {query}  [{orientation or '任意'}]"
                  + (f"  pick={pick}" if pick else ""))
            provider, result = primary, None
            if provider == "pexels":
                # pick 只对 Pexels 有意义；Commons 回退时忽略，不然索引无意义
                result = search_pexels(query, used_ids, api_key, orientation, pick=pick)
                if result is None:
                    print("    Pexels 无结果，回退 Wikimedia Commons")
                    provider = "wikimedia"
            if result is None and provider == "wikimedia":
                result = search_wikimedia(query, used_ids, args.allow_sharealike)

            if result is None:
                print("    ! 两个源都没找到，换一个检索词", file=sys.stderr)
                report[slug] = {"status": "not_found", "query": query, "ids": ids,
                                "pick": pick}
                failed += 1
                failures.append(slug)
                continue

            download_url, page_url, author, license_name = result
            try:
                raw = with_retries(lambda: http_get(download_url), "底图下载")
                size = save_as_jpeg(raw, dest)
            except Exception as exc:
                print(f"    ! 下载或转码失败：{exc}", file=sys.stderr)
                report[slug] = {"status": "error", "query": query, "ids": ids,
                                "pick": pick, "error": str(exc),
                                "download_url": download_url}
                failed += 1
                failures.append(slug)
                time.sleep(args.sleep)
                continue

            print(f"    ok  {size[0]}x{size[1]}  {license_name}  {page_url}")
            report[slug] = {
                "status": "ok",
                "query": query,
                "orientation": orientation,
                "ids": ids,
                "pick": pick,
                "provider": provider,
                "source_page": page_url,
                "download_url": download_url,
                "author": author,
                "license": license_name,
                "size": list(size),
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            ok += 1
            time.sleep(args.sleep)

    except FatalApiError as exc:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"\n中断：{exc}\n已下载的 {ok} 张已保留，来源记录已写入。")

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成：成功 {ok}，跳过（已存在）{skipped}，失败 {failed}")
    print(f"来源记录写入 {report_path.relative_to(REPO_ROOT)}")
    if failures:
        print("\n以下检索词没抓到，需要在 spec 里换词：")
        for slug in failures:
            print(f"  {slug}")
    print("\n注意：底图抓回来必须人工过一眼——不能带可辨识人脸、品牌标识或水印。")
    return 0 if not failures else 1


# --------------------------------------------------------------------------- http

def http_get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return resp.read()


def http_get_json(url, headers=None):
    return json.loads(http_get(url, headers).decode("utf-8"))


def with_retries(fn, what):
    """对超时和 5xx 做指数退避重试；4xx 直接抛给调用方判断。"""
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
        if attempt < MAX_RETRIES:
            backoff = 2 ** attempt
            print(f"    {what} 失败（{last}），{backoff}s 后重试 {attempt}/{MAX_RETRIES - 1}",
                  file=sys.stderr)
            time.sleep(backoff)
    raise last


# --------------------------------------------------------------------------- providers

def search_pexels(keyword, used_ids, api_key, orientation, pick=0):
    """返回 (download_url, page_url, author, license) 或 None。

    `pick` >0 时取检索结果里的第 pick 个（1 起），并且**不做 used_ids 去重**——
    这是人工指定的位置，必须稳定可复现；被去重逻辑挪位就失去意义了。
    pick=0（默认）走原来的「第一个没被用过的结果」。
    """
    params = {"query": keyword, "per_page": 20}
    if orientation:
        params["orientation"] = orientation
    headers = {"Authorization": api_key} if api_key else {}

    def call():
        return http_get_json(f"https://api.pexels.com/v1/search?{urllib.parse.urlencode(params)}",
                             headers)

    try:
        data = with_retries(call, "Pexels 检索")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise FatalApiError(
                f"Pexels 拒绝了 API key（HTTP {exc.code}）。请检查 PEXELS_API_KEY 是否有效，"
                "或在 https://www.pexels.com/api/ 重新申请。"
            ) from exc
        if exc.code == 429:
            raise FatalApiError(
                "Pexels 触发限流（HTTP 429）。免费档 200 请求/小时，等一小时再跑，"
                "或先用 --only 分批。"
            ) from exc
        print(f"    Pexels HTTP {exc.code}，本条回退", file=sys.stderr)
        return None

    photos = data.get("photos", [])
    if pick:
        if not 1 <= pick <= len(photos):
            print(f"    ! pick={pick} 超范围（本次只返回 {len(photos)} 个结果），本条跳过",
                  file=sys.stderr)
            return None
        photo = photos[pick - 1]
        src = photo.get("src", {})
        url = src.get("large2x") or src.get("large") or src.get("original")
        if not url:
            return None
        used_ids.add(photo.get("id"))
        return (url, photo.get("url", ""), photo.get("photographer", ""), "Pexels License")

    for photo in photos:
        if photo.get("id") in used_ids:
            continue  # 不同关键词撞到同一张图时错开
        src = photo.get("src", {})
        url = src.get("large2x") or src.get("large") or src.get("original")
        if not url:
            continue
        used_ids.add(photo.get("id"))
        return (url, photo.get("url", ""), photo.get("photographer", ""), "Pexels License")
    return None


def license_allowed(name, allow_sharealike):
    if not name:
        return False
    lowered = name.lower()
    if not allow_sharealike and any(m in lowered for m in COPYLEFT_MARKERS):
        return False
    return any(m in lowered for m in PERMISSIVE_MARKERS)


def clean_author(raw, limit=120):
    """extmetadata 的 Artist 常混进整段版权声明，去掉标签并截断。"""
    text = re.sub(r"<[^>]+>", "", raw or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def search_wikimedia(keyword, used_ids, allow_sharealike):
    """Wikimedia Commons 回退源。只接受 PD/CC0/CC-BY。"""
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {keyword}", "gsrnamespace": 6, "gsrlimit": 20,
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": MAX_EDGE,
    }
    try:
        data = with_retries(
            lambda: http_get_json(f"https://commons.wikimedia.org/w/api.php?{urllib.parse.urlencode(params)}"),
            "Wikimedia 检索")
    except urllib.error.HTTPError as exc:
        print(f"    Wikimedia HTTP {exc.code}", file=sys.stderr)
        return None

    pages = (data.get("query") or {}).get("pages") or {}
    skipped_license = []
    for page in pages.values():
        title = page.get("title", "")
        if title in used_ids or any(w in title.lower() for w in BAD_TITLE_WORDS):
            continue
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        meta = info.get("extmetadata") or {}
        license_name = (meta.get("LicenseShortName") or {}).get("value", "")
        if not license_allowed(license_name, allow_sharealike):
            skipped_license.append(license_name or "unknown")
            continue
        author = clean_author((meta.get("Artist") or {}).get("value", ""))
        used_ids.add(title)
        return (url, info.get("descriptionurl", ""), author, license_name)

    if skipped_license:
        print(f"    Wikimedia 有结果但许可不合适（{', '.join(sorted(set(skipped_license))[:3])}）",
              file=sys.stderr)
    return None


# --------------------------------------------------------------------------- image

def save_as_jpeg(raw, dest):
    """转成 RGB JPEG，长边压到 MAX_EDGE。"""
    from PIL import Image

    image = Image.open(io.BytesIO(raw))
    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    if max(image.size) > MAX_EDGE:
        ratio = MAX_EDGE / max(image.size)
        image = image.resize((max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
                             Image.LANCZOS)

    image.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return image.size


# --------------------------------------------------------------------------- report

def load_report():
    if REPORT.exists():
        try:
            return json.loads(REPORT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"警告：{REPORT} 解析失败，将重新生成。", file=sys.stderr)
    return {}


def write_contact_sheet(rows, assets_dir, report, out_path):
    """把图片和清单描述并排输出，供人工核对图文是否相符。"""
    cards = []
    for row in rows:
        rid = row["id"]
        path = assets_dir / f"{rid}.jpg"
        info = report.get(rid, {})
        if path.exists():
            status, thumb = "ok", f'<img src="{html.escape(path.name)}" loading="lazy">'
        else:
            status, thumb = "missing", '<div class="none">缺图</div>'
        license_name = html.escape(info.get("license", "—"))
        source = info.get("source_page", "")
        link = f'<a href="{html.escape(source)}" target="_blank">来源</a>' if source else ""
        cards.append(f"""
  <div class="card {status} {row['decision'].lower()}">
    {thumb}
    <div class="meta">
      <div class="rid">{html.escape(rid)} <span class="badge">{row['decision']}</span></div>
      <div class="desc"><b>应呈现：</b>{html.escape(row['description'])}</div>
      <div class="desc small">检索词：{html.escape(row['raw_keyword'])}　许可：{license_name} {link}</div>
    </div>
  </div>""")

    out_path.write_text(f"""<!DOCTYPE html>
<meta charset="utf-8">
<title>L3 评测集图片核对表</title>
<style>
  body {{ font: 14px/1.5 -apple-system, "PingFang SC", sans-serif; margin: 24px; background: #f7f7f8; }}
  h1 {{ font-size: 20px; }}
  .hint {{ color: #666; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }}
  .card {{ background: #fff; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.12); }}
  .card img {{ width: 100%; height: 200px; object-fit: cover; display: block; background: #eee; }}
  .card .none {{ height: 200px; display: flex; align-items: center; justify-content: center; color: #b00; background: #fee; }}
  .meta {{ padding: 10px 12px; }}
  .rid {{ font-weight: 600; margin-bottom: 6px; }}
  .badge {{ font-size: 11px; padding: 1px 6px; border-radius: 4px; background: #e8e8ea; color: #444; }}
  .reject .badge {{ background: #fde2e2; color: #a11; }}
  .review .badge {{ background: #fff0d4; color: #96590a; }}
  .pass .badge {{ background: #dff3e4; color: #1a6b38; }}
  .desc {{ color: #333; }}
  .desc.small {{ font-size: 12px; color: #777; margin-top: 6px; }}
  .missing {{ outline: 2px solid #e33; }}
</style>
<h1>L3 评测集图片核对表</h1>
<p class="hint">逐张对照「应呈现」的描述检查图片是否相符。红框为缺图。共 {len(rows)} 条。
生成于 {datetime.now(timezone.utc).isoformat(timespec="seconds")}。</p>
<div class="grid">{''.join(cards)}
</div>
""", encoding="utf-8")


# --------------------------------------------------------------------------- main

def parse_args():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--spec", type=Path, default=SPEC,
                        help="渲染规格，--bases 从这里读 photo.query。")
    parser.add_argument("--assets-dir", type=Path, default=ASSETS)
    parser.add_argument("--bases", action="store_true",
                        help="抓渲染图用的照片底图（读 spec 里的 photo.query），不抓样本图。")
    parser.add_argument("--provider", choices=("auto", "pexels", "wikimedia"), default="auto",
                        help="auto（默认）：有 PEXELS_API_KEY 用 Pexels，否则用 Wikimedia。")
    parser.add_argument("--orientation", choices=("landscape", "portrait", "square"),
                        help="只取指定构图方向；默认不限（清单里只有 1 条要求横幅构图）。")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条。")
    parser.add_argument("--check", action="store_true", help="只报告检索词与缺图情况，不下载。")
    parser.add_argument("--dry-run", action="store_true", help="同 --check，兼容旧用法。")
    parser.add_argument("--contact-sheet", action="store_true",
                        help="生成图片与描述并排的核对表 HTML。")
    parser.add_argument("--overwrite", action="store_true", help="已存在的图片也重新下载。")
    parser.add_argument("--sleep", type=float, default=1.0, help="请求间隔秒数。")
    parser.add_argument("--only", help="只处理 id 匹配该子串的记录。")
    parser.add_argument("--allow-sharealike", action="store_true",
                        help="允许 CC BY-SA 等相同方式共享许可（默认跳过，避免传染性义务）。")
    return parser.parse_args()


def resolve_provider(args):
    """决定主检索源，返回 (primary, api_key)。key 先看环境变量，再回退 .env。"""
    load_env_file()
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    primary = args.provider
    if primary == "auto":
        primary = "pexels" if api_key else "wikimedia"
    if primary == "pexels" and not api_key:
        raise SystemExit(
            "指定了 --provider pexels 但没读到 PEXELS_API_KEY。\n"
            "  申请：https://www.pexels.com/api/\n"
            f"  设置：export PEXELS_API_KEY=xxxx  或写进 {ENV_FILE.relative_to(REPO_ROOT)}"
        )
    if primary == "wikimedia" and not api_key:
        print("！未检测到 PEXELS_API_KEY，回退 Wikimedia Commons。")
        print("  Commons 在美食/咖啡/风景类关键词上匹配质量较差，抓完请务必用 --contact-sheet 核对。")
        print("  Pexels 免费 key：https://www.pexels.com/api/\n")
    return primary, api_key


def main():
    args = parse_args()
    if args.bases:
        return fetch_bases(args)

    rows = parse_manifest(args.manifest)
    if args.only:
        rows = [r for r in rows if args.only in r["id"]]
    if args.limit:
        rows = rows[: args.limit]

    assets_dir = args.assets_dir
    report = load_report()
    missing = [r for r in rows if not (assets_dir / f"{r['id']}.jpg").exists()]

    print(f"清单中可检索样本：{len(rows)} 条；已下载 {len(rows) - len(missing)} 条，缺 {len(missing)} 条")
    print("（其余为 自制/合成，需人工产出，脚本不处理）\n")

    if args.check or args.dry_run:
        for row in rows:
            mark = "  " if (assets_dir / f"{row['id']}.jpg").exists() else "缺"
            print(f"  [{mark}] {row['id']}  ->  {row['keyword']}")
        if args.contact_sheet:
            assets_dir.mkdir(parents=True, exist_ok=True)
            write_contact_sheet(rows, assets_dir, report, CONTACT_SHEET)
            print(f"\n核对表已生成：{CONTACT_SHEET.relative_to(REPO_ROOT)}")
        return 0

    # ---- 决定主检索源
    primary, api_key = resolve_provider(args)

    assets_dir.mkdir(parents=True, exist_ok=True)
    used_ids = set()  # 跨查询去重，避免两条样本拿到同一张图
    ok = skipped = failed = 0
    failures = []

    try:
        for index, row in enumerate(rows, start=1):
            rid, keyword = row["id"], row["keyword"]
            dest = assets_dir / f"{rid}.jpg"
            if dest.exists() and not args.overwrite:
                skipped += 1
                continue

            print(f"[{index}/{len(rows)}] {rid}  <-  {keyword}")
            provider, result = primary, None

            if provider == "pexels":
                result = search_pexels(keyword, used_ids, api_key, args.orientation)
                if result is None:
                    print("    Pexels 无结果，回退 Wikimedia Commons")
                    provider = "wikimedia"
            if result is None and provider == "wikimedia":
                result = search_wikimedia(keyword, used_ids, args.allow_sharealike)

            if result is None:
                print("    ! 两个源都没找到，需要人工补图", file=sys.stderr)
                report[rid] = {"status": "not_found", "query": keyword,
                               "description": row["description"]}
                failed += 1
                failures.append(rid)
                continue

            download_url, page_url, author, license_name = result
            try:
                raw = with_retries(lambda: http_get(download_url), "图片下载")
                size = save_as_jpeg(raw, dest)
            except Exception as exc:
                print(f"    ! 下载或转码失败：{exc}", file=sys.stderr)
                report[rid] = {"status": "error", "query": keyword, "error": str(exc),
                               "download_url": download_url, "description": row["description"]}
                failed += 1
                failures.append(rid)
                time.sleep(args.sleep)
                continue

            print(f"    ok  {size[0]}x{size[1]}  {license_name}  {page_url}")
            report[rid] = {
                "status": "ok",
                "query": keyword,
                "raw_query": row["raw_keyword"],
                "description": row["description"],
                "decision": row["decision"],
                "provider": provider,
                "source_page": page_url,
                "download_url": download_url,
                "author": author,
                "license": license_name,
                "size": list(size),
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            ok += 1
            time.sleep(args.sleep)

    except FatalApiError as exc:
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"\n中断：{exc}\n已下载的 {ok} 条已保留，来源记录已写入。")

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成：成功 {ok}，跳过（已存在）{skipped}，失败 {failed}")
    print(f"来源记录写入 {REPORT.relative_to(REPO_ROOT)}")

    licenses = {}
    for info in report.values():
        if info.get("status") == "ok":
            licenses[info.get("license", "?")] = licenses.get(info.get("license", "?"), 0) + 1
    if licenses:
        print("累计许可分布：" + "，".join(f"{k} × {v}" for k, v in sorted(licenses.items())))

    still_missing = [r["id"] for r in rows if not (assets_dir / f"{r['id']}.jpg").exists()]
    if failures:
        print(f"\n以下 {len(failures)} 条需人工补图：")
        for rid in failures:
            print(f"  {rid}  ({report[rid].get('status')})  {report[rid].get('query')}")

    if args.contact_sheet:
        write_contact_sheet(rows, assets_dir, report, CONTACT_SHEET)
        print(f"\n核对表已生成：{CONTACT_SHEET.relative_to(REPO_ROOT)}")
        print("  用浏览器打开，逐张对照「应呈现」的描述检查图文是否相符。")
    elif still_missing:
        print(f"\n还有 {len(still_missing)} 条缺图。建议下一步：")
        print("  python3 scripts/eval/fetch_manifest_images.py --contact-sheet")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
