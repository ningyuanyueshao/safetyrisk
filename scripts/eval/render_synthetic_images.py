#!/usr/bin/env python3

"""Render the L3 eval dataset's synthetic (自制) images from a declarative spec.

The manifest marks 115 samples as 自制 / 合成. Most of them are text layouts —
gambling posters, prostitution cards, chat screenshots, transfer confirmations,
meme overlays — which do NOT need a generative image model:

  * diffusion models garble Chinese text, and the OCR-exposed samples depend on
    the text being exactly readable (e.g.「稳赚不赔 日入过千」must be legible);
  * this dataset is FROZEN, so the images must be reproducible byte-for-byte;
  * rendering needs no model weights and raises no content-filter questions.

So the risky imagery is drawn deterministically from datasets/l3/eval/synthetic_spec.json.

Placeholder QR codes are deliberately non-scannable noise — they look like a QR
code but encode nothing and point nowhere.

Usage:
    python3 scripts/eval/render_synthetic_images.py --list
    python3 scripts/eval/render_synthetic_images.py                  # render all specs
    python3 scripts/eval/render_synthetic_images.py --only l3-img-reject-001
    python3 scripts/eval/render_synthetic_images.py --overwrite
"""

import argparse
import json
import math
import random
import re
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "datasets/l3/eval/synthetic_spec.json"
ASSETS = REPO_ROOT / "datasets/l3/eval/assets"
# 照片底图目录。main() 会按 --assets-dir 覆盖它。
PHOTOS = ASSETS / "photos"

# 中文字体候选，按优先级找第一个存在的
FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]

_font_cache = {}


def font_path():
    for path in FONT_CANDIDATES:
        if not Path(path).exists():
            continue
        try:
            ImageFont.truetype(path, 20)
            return path
        except Exception:
            continue  # 存在但 PIL 打不开（例如部分 PingFang.ttc 索引）
    raise SystemExit(
        "找不到可用的中文字体。请在 FONT_CANDIDATES 里补一个本机存在的中文字体路径，"
        "否则渲染出来的中文会全是方框。"
    )


# 系统字体都不含彩色 emoji 字形：STHeiti 落到 tofu 方框，Apple Color Emoji 经 PIL
# 解码只剩无色灰度轮廓。而本项目有若干样本的违规点恰恰在 emoji 上（🍬/🍵 指代违禁品），
# 所以这几个 emoji 用矢量图形画，保证语义可见。
EMOJI_SHAPES = {"🍬", "🍵", "👌", "🚗", "🔪", "🐎", "💰", "✅", "⬆"}


def draw_emoji(draw, ch, x, y, size):
    """在 (x, y) 画一个 size×size 的 emoji 替身图形。"""
    s = size
    if ch == "🍬":  # 糖果：中间圆 + 两侧包装纸三角
        draw.polygon([(x, y + s * 0.5), (x + s * 0.3, y + s * 0.28), (x + s * 0.3, y + s * 0.72)],
                     fill=(236, 64, 122))
        draw.polygon([(x + s, y + s * 0.5), (x + s * 0.7, y + s * 0.28), (x + s * 0.7, y + s * 0.72)],
                     fill=(236, 64, 122))
        draw.ellipse([x + s * 0.22, y + s * 0.22, x + s * 0.78, y + s * 0.78], fill=(244, 143, 177))
    elif ch == "🍵":  # 茶碗 + 热气
        draw.polygon([(x + s * 0.18, y + s * 0.42), (x + s * 0.82, y + s * 0.42),
                      (x + s * 0.68, y + s * 0.82), (x + s * 0.32, y + s * 0.82)],
                     fill=(76, 175, 80))
        draw.arc([x + s * 0.60, y + s * 0.50, x + s * 0.95, y + s * 0.75], -70, 70,
                 fill=(76, 175, 80), width=max(1, int(s * 0.06)))
        for i in range(2):
            xx = x + s * (0.38 + i * 0.22)
            draw.arc([xx, y + s * 0.08, xx + s * 0.14, y + s * 0.40], 90, 270,
                     fill=(158, 158, 158), width=max(1, int(s * 0.05)))
    elif ch == "👌":
        draw.ellipse([x + s * 0.08, y + s * 0.22, x + s * 0.72, y + s * 0.86], fill=(255, 204, 128))
        draw.ellipse([x + s * 0.50, y + s * 0.06, x + s * 0.92, y + s * 0.48], fill=(255, 204, 128))
        draw.ellipse([x + s * 0.30, y + s * 0.38, x + s * 0.84, y + s * 0.90],
                     outline=(230, 160, 90), width=max(1, int(s * 0.06)))
    elif ch == "🚗":
        draw.rounded_rectangle([x + s * 0.06, y + s * 0.42, x + s * 0.94, y + s * 0.74],
                               radius=int(s * 0.10), fill=(33, 150, 243))
        draw.polygon([(x + s * 0.26, y + s * 0.42), (x + s * 0.42, y + s * 0.18),
                      (x + s * 0.68, y + s * 0.18), (x + s * 0.80, y + s * 0.42)],
                     fill=(33, 150, 243))
        for cx in (0.26, 0.74):
            draw.ellipse([x + s * (cx - 0.11), y + s * 0.62, x + s * (cx + 0.11), y + s * 0.84],
                         fill=(55, 71, 79))
    elif ch == "🔪":  # 刀：细长梯形刀刃 + 刀柄
        draw.polygon([(x + s * 0.10, y + s * 0.40), (x + s * 0.68, y + s * 0.42),
                      (x + s * 0.68, y + s * 0.56), (x + s * 0.10, y + s * 0.50)],
                     fill=(189, 189, 189))
        draw.rectangle([x + s * 0.68, y + s * 0.40, x + s * 0.92, y + s * 0.58], fill=(93, 64, 55))
    elif ch == "🐎":  # 马：躯干 + 颈 + 腿
        draw.rectangle([x + s * 0.16, y + s * 0.40, x + s * 0.76, y + s * 0.64], fill=(141, 110, 99))
        draw.polygon([(x + s * 0.66, y + s * 0.44), (x + s * 0.86, y + s * 0.16),
                      (x + s * 0.94, y + s * 0.22), (x + s * 0.78, y + s * 0.48)],
                     fill=(141, 110, 99))
        for lx in (0.22, 0.36, 0.58, 0.72):
            draw.rectangle([x + s * lx, y + s * 0.62, x + s * (lx + 0.07), y + s * 0.86],
                           fill=(121, 85, 72))
    elif ch == "💰":
        draw.ellipse([x + s * 0.10, y + s * 0.34, x + s * 0.90, y + s * 0.92], fill=(240, 200, 60))
        draw.rectangle([x + s * 0.30, y + s * 0.08, x + s * 0.70, y + s * 0.40], fill=(240, 200, 60))
    elif ch == "⬆":  # 上箭头：撞库/上分类话术里用来替代敏感词
        draw.polygon([(x + s * 0.5, y + s * 0.12), (x + s * 0.88, y + s * 0.52),
                      (x + s * 0.62, y + s * 0.52), (x + s * 0.62, y + s * 0.88),
                      (x + s * 0.38, y + s * 0.88), (x + s * 0.38, y + s * 0.52),
                      (x + s * 0.12, y + s * 0.52)], fill=(211, 47, 47))
    elif ch == "✅":
        draw.line([(x + s * 0.16, y + s * 0.52), (x + s * 0.40, y + s * 0.78), (x + s * 0.86, y + s * 0.20)],
                  fill=(7, 193, 96), width=max(2, int(s * 0.14)))
    else:
        draw.rectangle([x, y, x + s, y + s], outline=(120, 120, 120))
    return s


def is_emoji(ch):
    return ch in EMOJI_SHAPES or (ord(ch) > 0x1F000 and ch not in EMOJI_SHAPES)


def load_font(size):
    if size not in _font_cache:
        _font_cache[size] = ImageFont.truetype(font_path(), size)
    return _font_cache[size]


# --------------------------------------------------------------------------- helpers

def gradient(size, start, end, vertical=True):
    """竖直或水平线性渐变底色。"""
    image = Image.new("RGB", size, start)
    draw = ImageDraw.Draw(image)
    span = size[1] if vertical else size[0]
    for i in range(span):
        ratio = i / max(1, span - 1)
        color = tuple(int(start[c] + (end[c] - start[c]) * ratio) for c in range(3))
        if vertical:
            draw.line([(0, i), (size[0], i)], fill=color)
        else:
            draw.line([(i, 0), (i, size[1])], fill=color)
    return image


def hexcolor(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def emoji_span(font):
    """emoji 替身图形按字号正方形的宽度参与排版。"""
    return int(font.size * 1.05)


def measure(draw, text, font):
    """文本像素宽度，emoji 记为一格正方形。"""
    total = 0
    for ch in text:
        total += emoji_span(font) if is_emoji(ch) else draw.textlength(ch, font=font)
    return int(total)


def text_size(draw, text, font):
    box = draw.textbbox((0, 0), text or "字", font=font)
    return measure(draw, text, font), box[3] - box[1]


def draw_run(draw, x, y, text, font, color):
    """逐字绘制，遇到 emoji 换成矢量图形。返回结束 x。"""
    for ch in text:
        if is_emoji(ch):
            draw_emoji(draw, ch, x, y, emoji_span(font))
            x += emoji_span(font)
        else:
            draw.text((x, y), ch, font=font, fill=color)
            x += draw.textlength(ch, font=font)
    return x


def draw_centered(draw, text, font, color, center_x, top):
    w, h = text_size(draw, text, font)
    draw_run(draw, center_x - w / 2, top, text, font, color)
    return h


def wrap(text, draw, font, max_width):
    """按像素宽度折行，中文按字断行。"""
    lines, current = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(current)
            current = ""
            continue
        if text_size(draw, current + ch, font)[0] > max_width and current:
            lines.append(current)
            current = ch
        else:
            current += ch
    if current:
        lines.append(current)
    return lines


def draw_qr_placeholder(image, box, seed=7):
    """画一个像二维码但不是二维码的图案：结构对、不可扫、不指向任何东西。"""
    x0, y0, x1, y1 = box
    side = min(x1 - x0, y1 - y0)
    module = max(2, side // 25)
    rng = random.Random(seed)
    draw = ImageDraw.Draw(image)
    draw.rectangle([x0 - 6, y0 - 6, x0 + side + 6, y0 + side + 6], fill=(255, 255, 255))
    for row in range(side // module):
        for col in range(side // module):
            if rng.random() < 0.45:
                px, py = x0 + col * module, y0 + row * module
                draw.rectangle([px, py, px + module - 1, py + module - 1], fill=(0, 0, 0))
    # 三个定位角，让它看起来像真的二维码
    for cx, cy in ((x0, y0), (x0 + side - 7 * module, y0), (x0, y0 + side - 7 * module)):
        draw.rectangle([cx, cy, cx + 7 * module, cy + 7 * module], fill=(255, 255, 255))
        draw.rectangle([cx, cy, cx + 7 * module, cy + 7 * module], outline=(0, 0, 0), width=module)
        draw.rectangle([cx + 2 * module, cy + 2 * module, cx + 5 * module, cy + 5 * module],
                       fill=(0, 0, 0))


def watermark(image, text="样例图 非真实", opacity=40):
    """角标，避免这些合成图被误当成真实违法素材传播。"""
    if not text:
        return image
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = load_font(max(14, image.width // 45))
    w, h = text_size(draw, text, font)
    draw.text((image.width - w - 16, image.height - h - 16), text, font=font,
              fill=(255, 255, 255, opacity))
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


# --------------------------------------------------------------------------- 照片底图

def slugify(text):
    """检索词 -> 底图文件名。必须和 fetch_manifest_images.py 里的同名函数保持一致。"""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "photo"


def load_photo(spec, size):
    """按 spec["photo"] 取真实照片底图，cover 裁切到 size。没配则返回 None。

    底图缺失**直接抛错**，不静默退回纯色底——那样会悄悄产出比改造前更差的图，
    而且没人会发现。宁可让这条渲染失败。
    """
    cfg = spec.get("photo")
    if not cfg:
        return None
    query = (cfg.get("query") or "").strip()
    if not query:
        raise ValueError("photo 字段缺少 query")

    path = PHOTOS / f"{slugify(query)}.jpg"
    if not path.exists():
        raise FileNotFoundError(
            f"缺少底图 {path.name}（query={query!r}）。先抓底图：\n"
            f"    python3 scripts/eval/fetch_manifest_images.py --bases"
        )

    image = Image.open(path).convert("RGB")
    w, h = size
    # cover：先按目标比例放大，再按 focus 锚点截取，保证铺满且不变形
    scale = max(w / image.width, h / image.height)
    image = image.resize((max(w, int(image.width * scale + 0.5)),
                          max(h, int(image.height * scale + 0.5))), Image.LANCZOS)
    fx, fy = cfg.get("focus", [0.5, 0.5])
    left = int((image.width - w) * float(fx))
    top = int((image.height - h) * float(fy))
    image = image.crop((left, top, left + w, top + h))

    if cfg.get("blur"):
        image = image.filter(ImageFilter.GaussianBlur(radius=float(cfg["blur"])))
    if cfg.get("dim"):
        image = Image.blend(image, Image.new("RGB", image.size, (0, 0, 0)),
                            min(0.85, float(cfg["dim"])))
    return image


def base_image(spec, size, fallback):
    """画布：配了 photo 就用真实照片，否则用 fallback 底色。

    fallback 传颜色字符串（纯色），或 [起色, 终色]（竖直渐变，poster 在用）。
    """
    photo = load_photo(spec, size)
    if photo is not None:
        return photo
    if isinstance(fallback, (list, tuple)) and len(fallback) == 2:
        return gradient(size, hexcolor(fallback[0]), hexcolor(fallback[1]))
    return Image.new("RGB", size, hexcolor(fallback))


def apply_noise(image, sigma, seed=3):
    """叠加高斯噪点，模拟夜间/低光拍摄。

    effect_noise 生成的灰度图以 128 为中心，所以用 add(offset=-128) 把它变成
    有正有负的偏移量再加到每个通道上——直接 blend 会把画面整体洗灰。
    """
    if not sigma:
        return image
    noise = Image.effect_noise(image.size, float(sigma)).convert("L")
    return Image.merge("RGB", [ImageChops.add(ch, noise, scale=1, offset=-128)
                               for ch in image.split()])


def draw_items(image, items, cols=None, seed=11, shadow=False):
    """在图上摆一组物件。

    item 用 box:[x,y,w,h]（相对画布的 0-1 比例）绝对定位，没有 box 就按网格自动排布。
    另支持 scale（缩放）、rotate（旋转角度）、alpha（0-255 不透明度）。

    旋转和半透明走「先画到独立 RGBA 图层再贴回」这条路——所有 _shape 函数都用
    局部坐标作画，搬进图层不用改任何形状代码。

    shadow=True 时给每个物件加一层模糊投影。底图是纯色时可以省（省了也和改造前
    逐字节一致），但底图是真实照片时必须加：没有投影的物件看着就是贴上去的贴纸。
    """
    if not items:
        return
    draw = ImageDraw.Draw(image)
    w, h = image.size
    rng = random.Random(seed)

    grid_cols = cols or max(1, min(4, len(items)))
    rows = (len(items) + grid_cols - 1) // grid_cols
    cell_w, cell_h = w / grid_cols, h / max(1, rows)

    for idx, item in enumerate(items):
        fn = SHAPES.get(item.get("shape"))
        if fn is None:
            print(f"  ! 未知物件 {item.get('shape')!r}", file=sys.stderr)
            continue
        scale = item.get("scale", 1.0)
        if item.get("box"):
            bx, by, bw, bh = item["box"]
            iw, ih = bw * w * scale, bh * h * scale
            x, y = bx * w, by * h
        else:
            col, row = idx % grid_cols, idx // grid_cols
            iw, ih = cell_w * 0.62 * scale, cell_h * 0.62 * scale
            # 轻微偏移，避免排得过于整齐像表格
            x = col * cell_w + (cell_w - iw) / 2 + rng.uniform(-cell_w * 0.06, cell_w * 0.06)
            y = row * cell_h + (cell_h - ih) / 2 + rng.uniform(-cell_h * 0.06, cell_h * 0.06)

        color = hexcolor(item.get("color", "#d7c9a8"))
        rotate = item.get("rotate", 0)
        alpha = item.get("alpha")

        if not rotate and alpha is None and not shadow:
            # 不取整：和改造前逐字节一致，FROZEN 数据集要能复现
            fn(draw, x, y, iw, ih, color, rng)
            continue

        pad = int(max(iw, ih) * 0.8) + 2
        layer = Image.new("RGBA", (int(iw) + pad * 2, int(ih) + pad * 2), (0, 0, 0, 0))
        fn(ImageDraw.Draw(layer), pad, pad, iw, ih, color, rng)
        if alpha is not None:
            layer.putalpha(layer.split()[-1].point(lambda v: int(v * alpha / 255)))
        if rotate:
            layer = layer.rotate(float(rotate), resample=Image.BICUBIC)
        if shadow:
            # 物件轮廓的模糊副本，右下方偏一点当投影
            off = max(2, int(max(iw, ih) * 0.045))
            dark = Image.new("RGBA", layer.size, (0, 0, 0, 0))
            dark.putalpha(layer.split()[-1].point(lambda v: int(v * 0.42)))
            dark = dark.filter(ImageFilter.GaussianBlur(max(2, int(max(iw, ih) * 0.05))))
            image.paste(dark, (int(x) - pad + off, int(y) - pad + off), dark)
        image.paste(layer, (int(x) - pad, int(y) - pad), layer)


def draw_labels(image, labels):
    """在指定 box 里居中画文字。一张图上有多处文字时用这个（价目表、工位标牌……）。"""
    if not labels:
        return
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for item in labels:
        text = item.get("text", "")
        if not text:
            continue
        bx, by, bw, _bh = item.get("box", [0.1, 0.1, 0.8, 0.1])
        font = load_font(item.get("size", int(h * 0.06)))
        line_h = text_size(draw, "字", font)[1] + int(h * 0.006)
        for i, line in enumerate(wrap(text, draw, font, int(bw * w))):
            draw_centered(draw, line, font, hexcolor(item.get("color", "#111111")),
                          (bx + bw / 2) * w, by * h + i * line_h)


# --------------------------------------------------------------------------- templates

def render_poster(spec):
    """竖版/横版文字海报：底色 + 大字标题 + 副文案 + 可选二维码 + 可选印章。

    配了 photo 时底色换成真实照片（宣纸纹理、斑驳墙面、旧纸……），文字直接落在照片上。
    """
    w, h = spec.get("size", [900, 1200])
    bg = spec.get("bg", ["#0b1e4b", "#123a8a"])
    image = base_image(spec, (w, h), bg)
    draw = ImageDraw.Draw(image)

    title_font = load_font(spec.get("title_size", int(w * 0.115)))
    sub_font = load_font(spec.get("sub_size", int(w * 0.045)))
    y = spec.get("title_top", int(h * 0.16))
    for line in spec.get("title", []):
        y += draw_centered(draw, line, title_font, hexcolor(spec.get("title_color", "#ffffff")),
                           w / 2, y) + int(h * 0.025)

    y += int(h * 0.03)
    for line in wrap(spec.get("subtitle", ""), draw, sub_font, int(w * 0.84)):
        y += draw_centered(draw, line, sub_font, hexcolor(spec.get("sub_color", "#d8def5")),
                           w / 2, y) + int(h * 0.012)

    if spec.get("qr"):
        pos = spec["qr"]
        side = int(w * spec.get("qr_scale", 0.26))
        margin = int(w * 0.08)
        if pos == "center":
            qx, qy = (w - side) // 2, (h - side) // 2
        else:
            qx = margin if "left" in pos else w - margin - side
            qy = margin if "top" in pos else h - margin - side
        draw_qr_placeholder(image, (qx, qy, qx + side, qy + side))
        if spec.get("qr_label"):
            draw_centered(draw, spec["qr_label"], load_font(int(w * 0.035)),
                          hexcolor(spec.get("qr_label_color", "#ffffff")),
                          qx + side / 2, qy + side + 8)

    # 印章、边框纹样之类的小件，用 box 绝对定位
    draw_items(image, spec.get("items", []), seed=spec.get("seed", 23),
               shadow=bool(spec.get("photo")))

    return watermark(image, spec.get("watermark", "样例图 非真实"))


def render_card(spec):
    """小卡片 / 小广告：纯色底 + 主副文案 + 可选占位号码。"""
    w, h = spec.get("size", [900, 600])
    image = base_image(spec, (w, h), spec.get("bg", "#ffffff"))
    draw = ImageDraw.Draw(image)

    if spec.get("border"):
        draw.rectangle([0, 0, w - 1, h - 1], outline=hexcolor(spec["border"]),
                       width=max(2, w // 200))

    main_font = load_font(spec.get("main_size", int(w * 0.085)))
    sub_font = load_font(spec.get("sub_size", int(w * 0.045)))
    y = spec.get("main_top", int(h * 0.16))
    for line in spec.get("main", []):
        y += draw_centered(draw, line, main_font, hexcolor(spec.get("main_color", "#111111")),
                           w / 2, y) + int(h * 0.03)

    y += int(h * 0.04)
    for line in spec.get("sub", []):
        y += draw_centered(draw, line, sub_font, hexcolor(spec.get("sub_color", "#444444")),
                           w / 2, y) + int(h * 0.022)

    if spec.get("phone"):
        draw_centered(draw, spec["phone"], load_font(int(w * 0.05)),
                      hexcolor(spec.get("phone_color", "#c0392b")), w / 2, h - int(h * 0.16))

    return watermark(image, spec.get("watermark", "样例图 非真实"))


def render_banner(spec):
    """社区横幅：纯色长条 + 白字 + 落款。"""
    w, h = spec.get("size", [1400, 420])
    image = base_image(spec, (w, h), spec.get("bg", "#c1272d"))
    draw = ImageDraw.Draw(image)
    font = load_font(spec.get("size_font", int(h * 0.28)))
    draw_centered(draw, spec.get("text", ""), font, hexcolor(spec.get("color", "#ffffff")),
                  w / 2, h * 0.22)
    if spec.get("footer"):
        draw_centered(draw, spec["footer"], load_font(int(h * 0.13)),
                      hexcolor(spec.get("color", "#ffffff")), w / 2, h * 0.66)
    return watermark(image, spec.get("watermark", "样例图 非真实"))


def render_chat(spec):
    """聊天截图：顶部标题栏 + 左右气泡。messages 里 side=left/right。"""
    w, h = spec.get("size", [900, 1200])
    image = base_image(spec, (w, h), spec.get("bg", "#ededed"))
    draw = ImageDraw.Draw(image)

    header_h = int(h * 0.07)
    draw.rectangle([0, 0, w, header_h], fill=hexcolor(spec.get("header_bg", "#2c2c2e")))
    draw_centered(draw, spec.get("title", ""), load_font(int(header_h * 0.42)),
                  hexcolor("#ffffff"), w / 2, header_h * 0.3)

    body_font = load_font(spec.get("font_size", int(w * 0.048)))
    pad = int(w * 0.04)
    y = header_h + pad

    for msg in spec.get("messages", []):
        lines = wrap(msg["text"], draw, body_font, int(w * 0.62))
        line_h = text_size(draw, "字", body_font)[1] + int(w * 0.022)
        bw = max(text_size(draw, ln, body_font)[0] for ln in lines) + pad
        bh = line_h * len(lines) + int(w * 0.03)

        left = msg.get("side", "left") == "left"
        bx = pad if left else w - pad - bw
        bubble_bg = "#ffffff" if left else "#95ec69"
        draw.rounded_rectangle([bx, y, bx + bw, y + bh], radius=int(w * 0.02),
                               fill=hexcolor(bubble_bg))
        ty = y + int(w * 0.015)
        for ln in lines:
            draw_run(draw, bx + pad / 2, ty, ln, body_font, hexcolor("#111111"))
            ty += line_h
        y += bh + int(h * 0.018)

    return watermark(image, spec.get("watermark", "样例图 非真实"))


def render_transfer(spec):
    """仿支付/转账结果页：绿色对勾 + 大字金额 + 收款方。"""
    w, h = spec.get("size", [900, 1400])
    image = base_image(spec, (w, h), spec.get("bg", "#f5f5f7"))
    draw = ImageDraw.Draw(image)

    cy = int(h * 0.26)
    r = int(w * 0.11)
    draw.ellipse([w / 2 - r, cy - r, w / 2 + r, cy + r], fill=hexcolor(spec.get("accent", "#07c160")))
    # 对勾
    draw.line([(w / 2 - r * 0.42, cy + r * 0.02), (w / 2 - r * 0.10, cy + r * 0.34)],
              fill=(255, 255, 255), width=max(4, int(r * 0.13)))
    draw.line([(w / 2 - r * 0.10, cy + r * 0.34), (w / 2 + r * 0.48, cy - r * 0.30)],
              fill=(255, 255, 255), width=max(4, int(r * 0.13)))

    text_color = hexcolor(spec.get("text_color", "#111111"))
    draw_centered(draw, spec.get("status", "转账成功"), load_font(int(w * 0.055)),
                  text_color, w / 2, cy + r + int(h * 0.03))
    draw_centered(draw, spec.get("amount", ""), load_font(spec.get("amount_size", int(w * 0.13))),
                  text_color, w / 2, cy + r + int(h * 0.10))

    y = int(h * 0.60)
    for label, value in spec.get("rows", []):
        draw.text((w * 0.12, y), label, font=load_font(int(w * 0.045)),
                  fill=hexcolor(spec.get("label_color", "#888888")))
        vw, _ = text_size(draw, value, load_font(int(w * 0.045)))
        draw.text((w * 0.88 - vw, y), value, font=load_font(int(w * 0.045)), fill=text_color)
        y += int(h * 0.055)
        draw.line([(w * 0.12, y - int(h * 0.012)), (w * 0.88, y - int(h * 0.012))],
                  fill=hexcolor("#e2e2e4"))

    return watermark(image, spec.get("watermark", "样例图 非真实"))


def draw_doc_content(draw, w, h, ox, oy, spec, fg, label_fg, rule_fg):
    """在 (w,h) 的画面上排版单据内容，(ox,oy) 是整体偏移。"""
    draw_centered(draw, spec.get("title", ""), load_font(int(w * 0.062)),
                  fg, w / 2 + ox, h * 0.05 + oy)
    draw.line([(w * 0.08 + ox, h * 0.10 + oy), (w * 0.92 + ox, h * 0.10 + oy)],
              fill=rule_fg, width=max(2, w // 400))

    label_font = load_font(int(w * 0.040))
    y = int(h * 0.13) + oy
    for row in spec.get("rows", []):
        draw.text((w * 0.10 + ox, y), row.get("label", ""), font=label_font, fill=label_fg)
        value = row.get("value", "")
        if row.get("masked"):
            vw = int(w * row.get("mask_width", 0.28))
            draw.rectangle([w * 0.42 + ox, y - 2, w * 0.42 + ox + vw, y + int(w * 0.055)],
                           fill=hexcolor("#9a9a9a"))
        else:
            draw.text((w * 0.42 + ox, y), value, font=label_font, fill=fg)
        y += int(h * 0.055)


def render_doc(spec):
    """表单/报告单：标题 + 若干行字段，可把某些字段打码。

    offset:[dx,dy] 按画布比例整体平移内容（超出画布的部分自然被裁掉），
    用来做「只剩右下角」「纸张偏出画面」这类裁切构图。

    paper: 先在底图上贴一张纸，内容画在纸面上。真实照片打底时文字直接画在照片上
    既读不出来也不像一张单据（暗光翻拍的处方笺就是这种情况）。给 dict 时支持
    box（0-1 比例，**可以是负数或大于 1**，超出画布的部分自然被裁掉——「只剩一角」
    的构图就靠这个）、color、alpha、rotate。文字位置一律相对纸面算，不是相对画布。
    """
    w, h = spec.get("size", [900, 1250])
    image = base_image(spec, (w, h), spec.get("bg", "#ffffff"))

    # offset 的单位是「容器」的比例：没纸张时是画布，有纸张时是纸面。别混用——
    # 用画布比例去偏纸面坐标，内容会被推到画布外，整张图变成一片空白。
    dx, dy = spec.get("offset", [0, 0])

    # 文字颜色可配：深色底图（影院座椅、暗光翻拍）上默认的黑色读不出来
    fg = hexcolor(spec.get("fg", "#111111"))
    label_fg = hexcolor(spec.get("label_color", "#555555"))
    rule_fg = hexcolor(spec.get("rule_color", "#333333"))

    paper = spec.get("paper")
    if not paper:
        draw_doc_content(ImageDraw.Draw(image), w, h, int(w * dx), int(h * dy),
                         spec, fg, label_fg, rule_fg)
        return watermark(image, spec.get("watermark", "样例图 非真实"))

    cfg = paper if isinstance(paper, dict) else {}
    bx, by, bw, bh = cfg.get("box", [0, 0, 1, 1])
    pw, ph = max(1, int(w * bw)), max(1, int(h * bh))
    sheet = Image.new("RGBA", (pw, ph),
                      hexcolor(cfg.get("color", "#ffffff"))
                      + (int(255 * float(cfg.get("alpha", 1.0))),))
    draw_doc_content(ImageDraw.Draw(sheet), pw, ph, int(pw * dx), int(ph * dy),
                     spec, fg, label_fg, rule_fg)

    left, top = int(w * bx), int(h * by)
    if cfg.get("rotate"):
        # 先贴到一张大一圈的透明画布上再转，否则四角会被切掉；旋转绕中心，中心不动
        pad = int(max(pw, ph) * 0.25) + 2
        big = Image.new("RGBA", (pw + pad * 2, ph + pad * 2), (0, 0, 0, 0))
        big.paste(sheet, (pad, pad))
        sheet = big.rotate(float(cfg["rotate"]), resample=Image.BICUBIC)
        left -= pad
        top -= pad
    image.paste(sheet, (left, top), sheet)
    return watermark(image, spec.get("watermark", "样例图 非真实"))


def render_meme(spec):
    """表情包二创：纯色/形状底 + 上下配文。不用真实人物素材。"""
    w, h = spec.get("size", [800, 800])
    image = base_image(spec, (w, h), spec.get("bg", "#f2f2f2"))
    draw = ImageDraw.Draw(image)

    # 简单的示意图形，代替真实表情包底图
    shape = spec.get("shape", "circle")
    pad = int(w * 0.18)
    if shape == "circle":
        draw.ellipse([pad, pad, w - pad, h - pad], fill=hexcolor(spec.get("shape_color", "#cfd8dc")))
    elif shape == "silhouette":
        draw.pieslice([pad, pad, w - pad, h - pad], 180, 360,
                      fill=hexcolor(spec.get("shape_color", "#37474f")))

    text_font = load_font(spec.get("font_size", int(w * 0.10)))
    if spec.get("top"):
        for i, line in enumerate(wrap(spec["top"], draw, text_font, int(w * 0.9))):
            draw_centered(draw, line, text_font, hexcolor(spec.get("color", "#111111")),
                          w / 2, int(h * 0.03) + i * int(w * 0.12))
    if spec.get("bottom"):
        lines = wrap(spec["bottom"], draw, text_font, int(w * 0.9))
        for i, line in enumerate(lines):
            draw_centered(draw, line, text_font, hexcolor(spec.get("color", "#111111")),
                          w / 2, h - int(h * 0.14) - (len(lines) - 1 - i) * int(w * 0.12))

    return watermark(image, spec.get("watermark", "样例图 非真实"))


# --------------------------------------------------------------------------- 摆拍/插画类

def shade(color, factor):
    """factor < 1 变暗，> 1 变亮。给图形加边缘和层次用。"""
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def _bag(draw, x, y, w, h, c, rng):
    """自封袋：袋身 + 顶部封口条。"""
    draw.rounded_rectangle([x, y, x + w, y + h], radius=int(w * 0.10), fill=c,
                           outline=shade(c, 0.75))
    draw.rectangle([x + w * 0.08, y + h * 0.05, x + w * 0.92, y + h * 0.15],
                   fill=shade(c, 1.12))


def _powder(draw, x, y, w, h, c, rng):
    """白色颗粒/晶体：一簇重叠椭圆，避免画成规则圆形。"""
    for _ in range(9):
        rx = x + rng.uniform(0, w * 0.55)
        ry = y + rng.uniform(0, h * 0.55)
        r = rng.uniform(w * 0.18, w * 0.34)
        draw.ellipse([rx, ry, rx + r, ry + r], fill=shade(c, rng.uniform(0.94, 1.0)))


def _pill(draw, x, y, w, h, c, rng):
    """药片：几颗小圆，颜色各异。"""
    palette = [(240, 98, 146), (255, 202, 40), (66, 165, 245), (102, 187, 106)]
    for i in range(rng.randint(5, 9)):
        r = w * rng.uniform(0.07, 0.13)
        px = x + rng.uniform(0, w - r)
        py = y + rng.uniform(0, h - r)
        draw.ellipse([px, py, px + r, py + r], fill=palette[i % len(palette)])


def _card(draw, x, y, w, h, c, rng):
    """银行卡：圆角矩形 + 磁条 + 芯片块。"""
    draw.rounded_rectangle([x, y, x + w, y + h], radius=int(h * 0.10), fill=c,
                           outline=shade(c, 0.8))
    draw.rectangle([x, y + h * 0.22, x + w, y + h * 0.38], fill=shade(c, 0.55))
    draw.rounded_rectangle([x + w * 0.10, y + h * 0.52, x + w * 0.30, y + h * 0.70],
                           radius=int(h * 0.04), fill=(212, 175, 55))


def _box(draw, x, y, w, h, c, rng):
    """药盒/包装盒：正面 + 顶部色带。"""
    draw.rectangle([x, y, x + w, y + h], fill=c, outline=shade(c, 0.78))
    draw.rectangle([x, y + h * 0.12, x + w, y + h * 0.30], fill=shade(c, 0.62))
    for i in range(2):
        ly = y + h * (0.50 + i * 0.16)
        draw.rectangle([x + w * 0.12, ly, x + w * 0.78, ly + h * 0.05],
                       fill=shade(c, 0.80))


def _bottle(draw, x, y, w, h, c, rng):
    """小瓶：瓶身 + 瓶颈 + 瓶盖。"""
    draw.rounded_rectangle([x, y + h * 0.28, x + w, y + h], radius=int(w * 0.14), fill=c)
    draw.rectangle([x + w * 0.32, y + h * 0.10, x + w * 0.68, y + h * 0.30], fill=shade(c, 0.9))
    draw.rectangle([x + w * 0.28, y, x + w * 0.72, y + h * 0.12], fill=(69, 90, 100))


def _scale(draw, x, y, w, h, c, rng):
    """电子秤：秤台 + 显示屏。"""
    draw.rounded_rectangle([x, y, x + w, y + h], radius=int(h * 0.14), fill=c)
    draw.rounded_rectangle([x + w * 0.12, y + h * 0.14, x + w * 0.88, y + h * 0.48],
                           radius=int(h * 0.06), fill=(120, 200, 140))


def _pipe(draw, x, y, w, h, c, rng):
    """冰壶形器皿：球体 + 颈部 + 吸管，玻璃质感用浅色描边表示。"""
    r = min(w, h * 1.4) * 0.38
    cx, cy = x + w * 0.42, y + h * 0.68
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c, outline=shade(c, 0.7), width=2)
    draw.rectangle([cx - r * 0.22, y + h * 0.10, cx + r * 0.22, cy - r * 0.7], fill=c,
                   outline=shade(c, 0.7))
    draw.line([cx + r * 0.6, cy - r * 0.2, x + w * 0.96, y + h * 0.16],
              fill=shade(c, 0.75), width=max(2, int(w * 0.04)))


def _foil(draw, x, y, w, h, c, rng):
    """锡纸：带锯齿边的灰色多边形。"""
    pts = [(x, y + h * 0.75)]
    steps = 7
    for i in range(steps + 1):
        pts.append((x + w * i / steps, y + h * rng.uniform(0.06, 0.34)))
    pts += [(x + w, y + h * 0.75)]
    draw.polygon(pts, fill=c, outline=shade(c, 0.7))


def _syringe(draw, x, y, w, h, c, rng):
    """注射器：筒身 + 推杆 + 针头。"""
    draw.rectangle([x, y + h * 0.40, x + w * 0.72, y + h * 0.60], fill=c,
                   outline=shade(c, 0.7))
    draw.rectangle([x - w * 0.10, y + h * 0.44, x, y + h * 0.56], fill=shade(c, 0.8))
    draw.line([x + w * 0.72, y + h * 0.50, x + w, y + h * 0.50], fill=(150, 150, 155),
              width=max(1, int(h * 0.05)))


def _gun(draw, x, y, w, h, c, rng):
    """仿真枪剪影：套筒 + 握把 + 扳机护圈，刻意保持抽象，不刻画细节。"""
    draw.polygon([(x, y + h * 0.28), (x + w * 0.82, y + h * 0.28),
                  (x + w * 0.82, y + h * 0.50), (x, y + h * 0.50)], fill=c)
    draw.polygon([(x + w * 0.18, y + h * 0.48), (x + w * 0.46, y + h * 0.48),
                  (x + w * 0.38, y + h * 0.92), (x + w * 0.14, y + h * 0.92)], fill=c)
    draw.arc([x + w * 0.44, y + h * 0.46, x + w * 0.66, y + h * 0.72], 0, 180,
             fill=shade(c, 0.8), width=max(2, int(h * 0.05)))


def _toygun(draw, x, y, w, h, c, rng):
    """玩具枪：同枪形，但枪口是醒目橙色 + 通体浅色，一眼可辨是玩具。"""
    _gun(draw, x, y, w, h, c, rng)
    draw.rectangle([x + w * 0.78, y + h * 0.30, x + w * 0.86, y + h * 0.48],
                   fill=(255, 111, 0))


def _knife(draw, x, y, w, h, c, rng):
    """刀具：刀刃 + 刀柄，抽象轮廓。"""
    draw.polygon([(x, y + h * 0.42), (x + w * 0.62, y + h * 0.34),
                  (x + w * 0.62, y + h * 0.58), (x, y + h * 0.54)], fill=c)
    draw.rectangle([x + w * 0.62, y + h * 0.38, x + w, y + h * 0.56],
                   fill=(93, 64, 55))


def _crossbow(draw, x, y, w, h, c, rng):
    """弩：弓臂弧线 + 弩身。"""
    draw.arc([x, y, x + w * 0.66, y + h], 200, 340, fill=c, width=max(3, int(h * 0.10)))
    draw.rectangle([x + w * 0.20, y + h * 0.46, x + w, y + h * 0.60], fill=shade(c, 0.85))


def _paper(draw, x, y, w, h, c, rng):
    """单据/面单/证件：纸面 + 若干文字行占位。"""
    draw.rectangle([x, y, x + w, y + h], fill=c, outline=shade(c, 0.85))
    for i in range(rng.randint(3, 5)):
        ly = y + h * (0.20 + i * 0.16)
        draw.rectangle([x + w * 0.10, ly, x + w * rng.uniform(0.55, 0.88), ly + h * 0.05],
                       fill=shade(c, 0.72))


def _phone(draw, x, y, w, h, c, rng):
    """手机：机身 + 屏幕。"""
    draw.rounded_rectangle([x, y, x + w, y + h], radius=int(w * 0.10), fill=(40, 40, 44))
    draw.rounded_rectangle([x + w * 0.06, y + h * 0.04, x + w * 0.94, y + h * 0.96],
                           radius=int(w * 0.07), fill=c)


def _model(draw, x, y, w, h, c, rng):
    """舰船模型：船体梯形 + 上层建筑 + 桅杆。"""
    draw.polygon([(x, y + h * 0.62), (x + w, y + h * 0.62),
                  (x + w * 0.88, y + h * 0.86), (x + w * 0.12, y + h * 0.86)], fill=c)
    draw.rectangle([x + w * 0.38, y + h * 0.40, x + w * 0.62, y + h * 0.64],
                   fill=shade(c, 0.85))
    draw.line([x + w * 0.50, y + h * 0.40, x + w * 0.50, y + h * 0.10],
              fill=shade(c, 0.7), width=max(2, int(w * 0.02)))


def _arm(draw, x, y, w, h, c, rng):
    """一段小臂 + 划伤，右端收成拳头，用于伤口类样本。

    等宽的圆角长条看着像一根香肠，所以臂身两端收窄、上缘压一道高光做出圆柱感，
    末端再补一个拳头。伤口自带——叠在真实皮肤照片上时不要再单独摆一个 scar，
    两道伤口会打架。
    """
    band = h * 0.46
    top, bot = y + (h - band) / 2, y + (h + band) / 2
    mid = (top + bot) / 2
    tip = x + w * 0.78

    draw.ellipse([x - band * 0.05, top, x + band * 0.45, bot], fill=c)        # 上臂端
    draw.polygon([(x, top), (tip, top + band * 0.22),
                  (tip, bot - band * 0.22), (x, bot)], fill=c)                # 臂身
    draw.ellipse([tip - band * 0.40, top + band * 0.14,
                  tip + band * 0.40, bot - band * 0.14], fill=c)              # 拳
    draw.line([x + w * 0.04, top + band * 0.22, tip - band * 0.30, top + band * 0.34],
              fill=shade(c, 1.10), width=max(2, int(band * 0.14)))            # 上缘高光

    px = x + w * 0.18                                                          # 伤痕
    for _ in range(7):
        nx = px + w * 0.065
        ny = mid + band * rng.uniform(-0.18, 0.18)
        draw.line([(px, mid), (nx, ny)], fill=(158, 32, 24),
                  width=max(2, int(band * rng.uniform(0.10, 0.18))))
        px, mid = nx, ny
    for _ in range(6):                                                         # 血迹
        bx = x + w * rng.uniform(0.20, 0.62)
        by = mid + band * rng.uniform(0.06, 0.40)
        r = band * rng.uniform(0.04, 0.09)
        draw.ellipse([bx - r, by - r * 0.8, bx + r, by + r * 0.8], fill=(150, 28, 22))


def _leaf(draw, x, y, w, h, c, rng):
    """锯齿状叶片。"""
    pts = [(x + w * 0.5, y)]
    for i in range(1, 7):
        pts.append((x + w * (0.5 + 0.42 * (1 if i % 2 else 0.6)), y + h * i / 7))
    for i in range(6, -1, -1):
        pts.append((x + w * (0.5 - 0.42 * (1 if i % 2 else 0.6)), y + h * i / 7))
    draw.polygon(pts, fill=c, outline=shade(c, 0.75))


def _seal(draw, x, y, w, h, c, rng):
    """公章：红色圆环 + 中间星形。"""
    r = min(w, h) * 0.44
    cx, cy = x + w / 2, y + h / 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=max(2, int(r * 0.14)))
    star = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r * (0.62 if i % 2 == 0 else 0.26)
        star.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    draw.polygon(star, fill=c)


def _hand(draw, x, y, w, h, c, rng):
    """握持的手：四指 + 手掌 + 拇指。

    专门用来遮住被握物的中段——比如刀刃与刀柄的连接处。那个位置能不能看清，
    正是「能不能判定为管制刀具」的分界，所以遮挡本身是样本语义的一部分。

    指节要伸出掌外、指间留缝并逐指调明度，否则同色叠在一起就是一坨色块，
    看不出是手。指尖朝左，手掌在右，拇指从掌侧斜插回来。
    """
    gap = h * 0.035
    fh = (h * 0.78 - gap * 3) / 4
    for i in range(4):
        fy = y + h * 0.10 + i * (fh + gap)
        draw.rounded_rectangle([x, fy, x + w * 0.76, fy + fh],
                               radius=int(fh * 0.46), fill=shade(c, 1.0 - i * 0.05))
    draw.rounded_rectangle([x + w * 0.44, y + h * 0.05, x + w, y + h * 0.97],
                           radius=int(w * 0.20), fill=c)               # 手掌/掌背
    draw.polygon([(x + w * 0.50, y + h * 0.02), (x + w * 0.96, y + h * 0.14),
                  (x + w * 0.88, y + h * 0.42), (x + w * 0.48, y + h * 0.28)],
                 fill=shade(c, 1.12))                                  # 拇指


def _scar(draw, x, y, w, h, c, rng):
    """划伤 + 血迹。不带肢体轮廓——底图已经是真实皮肤照片了，只叠伤口。

    画法上要避开两个「一眼假」：笔直的等宽线，和排列整齐的血点。所以走线用
    带随机抖动的折线、宽度沿程收放，血迹大小位置都打散，外圈再压一层淡红晕。
    """
    mid = y + h * 0.5
    steps = 16
    pts = []
    for i in range(steps + 1):
        t = i / steps
        # 抖动要小。幅度一大就不是伤口而是锯齿/红电缆了。
        pts.append((x + w * t, mid + h * (rng.uniform(-0.045, 0.045)
                                          + h * 0 + 0.03 * math.sin(t * 2.3))))

    halo = tuple(min(255, int(v * 0.5 + 255 * 0.5)) for v in c)       # 淡红晕：炎症感
    for width_scale, color in ((3.0, halo), (1.0, c)):
        for i in range(steps):
            thick = h * rng.uniform(0.040, 0.065) * width_scale
            draw.line([pts[i], pts[i + 1]], fill=color, width=max(1, int(thick)))

    for _ in range(7):                    # 血迹：大小、位置都打散
        cx = x + w * rng.uniform(0.04, 0.98)
        cy = mid + h * rng.uniform(0.02, 0.22)
        r = h * rng.uniform(0.02, 0.055)
        draw.ellipse([cx - r, cy - r * 0.8, cx + r, cy + r * 0.8], fill=shade(c, 0.9))


def _brush(draw, x, y, w, h, c, rng):
    """化妆笔：笔杆 + 金属箍 + 笔头。"""
    draw.rounded_rectangle([x, y + h * 0.34, x + w * 0.72, y + h * 0.66],
                           radius=int(h * 0.12), fill=c)
    draw.rectangle([x + w * 0.72, y + h * 0.30, x + w * 0.82, y + h * 0.70],
                   fill=(176, 190, 197))
    draw.polygon([(x + w * 0.82, y + h * 0.34), (x + w, y + h * 0.20),
                  (x + w, y + h * 0.80), (x + w * 0.82, y + h * 0.66)],
                 fill=shade(c, 0.7))


SHAPES = {
    "bag": _bag, "powder": _powder, "pill": _pill, "card": _card, "box": _box,
    "bottle": _bottle, "scale": _scale, "pipe": _pipe, "foil": _foil,
    "syringe": _syringe, "gun": _gun, "toygun": _toygun, "knife": _knife,
    "crossbow": _crossbow, "paper": _paper, "phone": _phone, "model": _model,
    "leaf": _leaf, "seal": _seal, "arm": _arm, "hand": _hand, "scar": _scar,
    "brush": _brush,
}


def render_flatlay(spec):
    """桌面俯拍摆拍：底色 + 一组摆放物件。

    物件用 items 描述，按网格自动排布；配了 photo 底图时改用 item 的 box 绝对定位。
    物件都是抽象几何图形，用来表达「摆着什么」的语义，不做写实刻画。
    真实敏感物品（枪支、管制刀具、毒品）一律用示意图形，不刻画细节。
    """
    w, h = spec.get("size", [1200, 900])
    image = base_image(spec, (w, h), spec.get("bg", "#e8e0d0"))

    draw_items(image, spec.get("items", []), cols=spec.get("cols"),
               seed=spec.get("seed", 11), shadow=bool(spec.get("photo")))
    draw_labels(image, spec.get("labels"))

    if spec.get("caption"):
        draw_centered(ImageDraw.Draw(image), spec["caption"], load_font(int(w * 0.045)),
                      hexcolor(spec.get("caption_color", "#333333")),
                      w / 2, h - int(h * 0.11))

    return watermark(image, spec.get("watermark", "样例图 非真实"))


def render_scene(spec):
    """剪影场景：人物 + 道具的轮廓构图。不出现真实人脸与写实细节。

    配了 photo 底图时，人物剪影叠在真实环境（暗巷、客厅、卧室……）上，
    敏感主体仍然只是剪影——只换背景，不动主体。
    """
    w, h = spec.get("size", [1000, 1000])
    image = base_image(spec, (w, h), spec.get("bg", "#eceff1"))
    draw = ImageDraw.Draw(image)
    color = hexcolor(spec.get("figure_color", "#37474f"))

    # 地面/台面。有真实底图时不能画——那条色带会糊住照片下缘
    if spec.get("ground") and not spec.get("photo"):
        draw.rectangle([0, h * 0.78, w, h], fill=hexcolor(spec["ground"]))

    pad = int(w * 0.16)
    shape = spec.get("pose", "half")
    if shape == "half":          # 头肩剪影，用于俯拍半身
        # 头 + 肩两段，比单个半圆更像人的轮廓
        head_r, cx, head_cy = w * 0.16, w / 2, h * 0.38
        draw.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r], fill=color)
        sh_top = head_cy + head_r * 0.75
        draw.rounded_rectangle([cx - w * 0.34, sh_top, cx + w * 0.34, h * 0.94],
                               radius=int(w * 0.16), fill=color)
    elif shape == "recline":     # 侧卧：横向轮廓
        draw.rounded_rectangle([w * 0.08, h * 0.46, w * 0.92, h * 0.66],
                               radius=int(h * 0.10), fill=color)
        draw.ellipse([w * 0.74, h * 0.40, w * 0.90, h * 0.56], fill=color)
    elif shape == "group":       # 并排数人
        n = spec.get("count", 5)
        for i in range(n):
            cx = w * (0.16 + 0.68 * i / max(1, n - 1))
            fh = h * 0.34
            draw.ellipse([cx - fh * 0.11, h * 0.30, cx + fh * 0.11, h * 0.30 + fh * 0.22],
                         fill=color)
            draw.rectangle([cx - fh * 0.14, h * 0.30 + fh * 0.20, cx + fh * 0.14, h * 0.30 + fh],
                           fill=color)
    elif shape == "wound":       # 手臂 + 划伤
        draw.rounded_rectangle([w * 0.10, h * 0.40, w * 0.90, h * 0.62],
                               radius=int(h * 0.11), fill=hexcolor(spec.get("skin", "#e8b98f")))
        draw.line([w * 0.28, h * 0.50, w * 0.62, h * 0.52],
                  fill=hexcolor(spec.get("wound_color", "#b3261e")),
                  width=max(3, int(h * 0.014)))
        for i in range(6):
            bx = w * (0.30 + 0.05 * i)
            draw.ellipse([bx, h * 0.545, bx + w * 0.018, h * 0.575],
                         fill=hexcolor(spec.get("wound_color", "#b3261e")))

    # 道具（长刀、棍棒……）叠在人物之上
    draw_items(image, spec.get("items", []), seed=spec.get("seed", 17),
               shadow=bool(spec.get("photo")))
    draw_labels(image, spec.get("labels"))

    if spec.get("caption"):
        lines = wrap(spec["caption"], draw, load_font(int(w * 0.055)), int(w * 0.88))
        for i, ln in enumerate(lines):
            draw_centered(draw, ln, load_font(int(w * 0.055)),
                          hexcolor(spec.get("caption_color", "#111111")),
                          w / 2, h * 0.02 + i * int(w * 0.075))

    return watermark(image, spec.get("watermark", "样例图 非真实"))


def render_chart(spec):
    """行情图：折线 + 成交量柱 + 均线，用于仿股票/博彩界面。"""
    w, h = spec.get("size", [900, 1200])
    image = base_image(spec, (w, h), spec.get("bg", "#1b1f24"))
    draw = ImageDraw.Draw(image)
    rng = random.Random(spec.get("seed", 5))
    top, bottom = h * 0.14, h * 0.62

    if spec.get("title"):
        draw.text((w * 0.06, h * 0.04), spec["title"], font=load_font(int(w * 0.045)),
                  fill=hexcolor(spec.get("fg", "#e0e0e0")))

    # 均线 + 分时线
    for line_color, weight in ((spec.get("line", "#26a69a"), 0.006),
                               (spec.get("line2", "#ef5350"), 0.004)):
        pts, y = [], (top + bottom) / 2
        for i in range(61):
            y += rng.uniform(-1, 1) * (bottom - top) * 0.05
            y = max(top, min(bottom, y))
            pts.append((w * 0.06 + (w * 0.88) * i / 60, y))
        draw.line(pts, fill=hexcolor(line_color), width=max(2, int(w * weight)))

    # 成交量柱
    for i in range(30):
        bx = w * 0.06 + (w * 0.88) * i / 30
        bh = rng.uniform(0.04, 0.18) * h
        draw.rectangle([bx, h * 0.88 - bh, bx + w * 0.022, h * 0.88],
                       fill=hexcolor(spec.get("volume", "#546e7a")))

    return watermark(image, spec.get("watermark", "样例图 非真实"))


def render_gamehud(spec):
    """射击游戏第一人称视角：准星 + 血条 + 弹药计数，场景为抽象的仓库空间。"""
    w, h = spec.get("size", [1400, 800])
    image = base_image(spec, (w, h), spec.get("bg", "#4e5b63"))
    draw = ImageDraw.Draw(image)

    # 简化的仓库空间：地面 + 若干箱体
    draw.rectangle([0, h * 0.62, w, h], fill=hexcolor(spec.get("floor", "#3a444a")))
    rng = random.Random(spec.get("seed", 3))
    for i in range(6):
        bw = w * rng.uniform(0.06, 0.13)
        bx = w * rng.uniform(0.05, 0.85)
        by = h * rng.uniform(0.45, 0.62)
        draw.rectangle([bx, by, bx + bw, h * 0.62], fill=shade(hexcolor("#5d4a3a"),
                                                              rng.uniform(0.8, 1.15)))

    # 准星
    cx, cy = w / 2, h / 2
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        draw.line([cx + dx * w * 0.012, cy + dy * w * 0.012,
                   cx + dx * w * 0.042, cy + dy * w * 0.042],
                  fill=hexcolor(spec.get("hud", "#e8f5e9")), width=3)

    # 血条与弹药
    draw.rectangle([w * 0.04, h * 0.88, w * 0.28, h * 0.93], fill=(60, 60, 60))
    draw.rectangle([w * 0.04, h * 0.88, w * 0.22, h * 0.93], fill=(198, 40, 40))
    draw.text((w * 0.80, h * 0.85), spec.get("ammo", "27 / 90"),
              font=load_font(int(h * 0.075)), fill=hexcolor(spec.get("hud", "#e8f5e9")))

    return watermark(image, spec.get("watermark", "样例图 非真实"))


def render_geometry(spec):
    """练习册几何题：两个三角形 + 已知条件标注 + 铅笔作图痕迹。"""
    w, h = spec.get("size", [1000, 1200])
    image = base_image(spec, (w, h), spec.get("bg", "#fbfaf5"))
    draw = ImageDraw.Draw(image)
    line = hexcolor(spec.get("line", "#2b2b2b"))

    draw_centered(draw, spec.get("title", "证明题"), load_font(int(w * 0.05)),
                  line, w / 2, h * 0.06)

    # 两个三角形
    for ox, oy, s in ((w * 0.12, h * 0.24, w * 0.34), (w * 0.54, h * 0.24, w * 0.34)):
        pts = [(ox, oy + s), (ox + s, oy + s), (ox + s * 0.45, oy)]
        draw.polygon(pts, outline=line, width=max(2, int(w * 0.005)))
        # 铅笔作图痕迹：淡色延伸线
        draw.line([pts[1], (ox + s * 1.28, oy + s)], fill=(150, 150, 150), width=1)

    y = h * 0.58
    for ln in spec.get("conditions", []):
        draw.text((w * 0.10, y), ln, font=load_font(int(w * 0.038)), fill=line)
        y += h * 0.06

    return watermark(image, spec.get("watermark", "样例图 非真实"))


def render_blur(spec):
    """在底图或纯色底上加高斯模糊，用于「糊到无法 OCR」类样本。

    清单里「气泡轮廓可辨、文字全糊」这种描述，靠纯色底加文字做不出来——
    轮廓本身也要被画出来再糊。所以支持 base 子规格：先渲染一个模板再模糊。
    """
    w, h = spec.get("size", [900, 900])
    if spec.get("base"):
        base_spec = dict(spec["base"])
        base_spec.setdefault("size", [w, h])
        base_spec["watermark"] = ""
        # 外层配了照片底图就一起透传下去，免得底图被内层模板的铺底盖掉
        if spec.get("photo"):
            base_spec.setdefault("photo", spec["photo"])
        image = TEMPLATES[base_spec.pop("template")](base_spec).convert("RGB")
        if image.size != (w, h):
            image = image.resize((w, h), Image.LANCZOS)
    else:
        image = Image.new("RGB", (w, h), hexcolor(spec.get("bg", "#7a7a7a")))
        if spec.get("text"):
            draw = ImageDraw.Draw(image)
            font = load_font(spec.get("font_size", int(w * 0.06)))
            draw_centered(draw, spec["text"], font, hexcolor(spec.get("color", "#333333")),
                          w / 2, h / 2)
    image = image.filter(ImageFilter.GaussianBlur(radius=spec.get("blur", 8)))
    return watermark(image, spec.get("watermark", "样例图 非真实"))


# "photo" 不是模板，是标记：这类样本要真实实物摆拍（假伤口、仿真枪、成堆药盒……），
# 程序渲染做不出可用素材，脚本只列出、不产出，由人工补齐。
PHOTO_TEMPLATE = "photo"

TEMPLATES = {
    "poster": render_poster,
    "card": render_card,
    "banner": render_banner,
    "chat": render_chat,
    "transfer": render_transfer,
    "doc": render_doc,
    "meme": render_meme,
    "blur": render_blur,
    "flatlay": render_flatlay,
    "scene": render_scene,
    "chart": render_chart,
    "gamehud": render_gamehud,
    "geometry": render_geometry,
}


# --------------------------------------------------------------------------- main

def parse_args():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", type=Path, default=SPEC)
    parser.add_argument("--assets-dir", type=Path, default=ASSETS)
    parser.add_argument("--only", help="只渲染 id 匹配该子串的记录。")
    parser.add_argument("--list", action="store_true", help="列出 spec 里的条目。")
    parser.add_argument("--overwrite", action="store_true", help="已存在的图片也重新渲染。")
    parser.add_argument("--quality", type=int, default=90)
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.spec.exists():
        raise SystemExit(f"缺少 spec 文件：{args.spec}")

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    # 下划线开头的键是注释，不是样本
    items = [(k, v) for k, v in spec.items() if not k.startswith("_")]
    if args.only:
        items = [(k, v) for k, v in items if args.only in k]

    if args.list:
        for rid, cfg in items:
            marks = []
            if cfg.get("template") == PHOTO_TEMPLATE:
                marks.append("需实物摆拍")
            if cfg.get("photo"):
                query = (cfg["photo"] or {}).get("query", "?")
                marks.append(f"底图 {slugify(query)}.jpg")
            if cfg.get("approx"):
                marks.append("示意级")
            mark = f"  （{'；'.join(marks)}）" if marks else ""
            print(f"  {rid}  [{cfg.get('template')}]{mark}")
        renderable = sum(1 for _, c in items if c.get("template") != PHOTO_TEMPLATE)
        with_photo = sum(1 for _, c in items if c.get("photo"))
        print(f"\n共 {len(items)} 条：程序渲染 {renderable}，需实物摆拍 "
              f"{len(items) - renderable}；其中 {with_photo} 条用照片底图")
        return 0

    args.assets_dir.mkdir(parents=True, exist_ok=True)
    global PHOTOS
    PHOTOS = args.assets_dir / "photos"
    ok = skipped = failed = photo = 0
    photo_ids = []
    approx_ids = []
    composed_ids = []

    for rid, cfg in items:
        dest = args.assets_dir / f"{rid}.jpg"
        # supplied 是人工实拍/手绘的图，脚本规格只是后备。**--overwrite 也不能碰**：
        # 那不是「重新渲染」，是拿示意图覆盖掉一张真图，且原图没有任何地方能恢复。
        if cfg.get("supplied"):
            if dest.exists():
                skipped += 1
            else:
                print(f"  ! {rid} 标了 supplied 但文件不存在，需要人工补图而非渲染",
                      file=sys.stderr)
                failed += 1
            continue
        if dest.exists() and not args.overwrite:
            skipped += 1
            continue

        template = cfg.get("template")
        if template == PHOTO_TEMPLATE:
            photo_ids.append(rid)
            photo += 1
            continue
        if template not in TEMPLATES:
            print(f"  ! {rid} 未知模板 {template!r}", file=sys.stderr)
            failed += 1
            continue
        try:
            image = TEMPLATES[template](cfg)
            # 拍摄质感的后处理：整图旋转（手持倾斜）和噪点（夜间低光）。
            # 放在这里而不是各模板里，13 个模板通用。
            if cfg.get("rotate"):
                # 旋转后按原尺寸从中心裁回，否则四角会露出底色，一看就是 P 的
                tw, th = image.size
                rotated = image.rotate(float(cfg["rotate"]), resample=Image.BICUBIC, expand=True)
                left = max(0, (rotated.width - tw) // 2)
                top = max(0, (rotated.height - th) // 2)
                image = rotated.crop((left, top, left + tw, top + th))
            if cfg.get("noise"):
                image = apply_noise(image, cfg["noise"], seed=cfg.get("seed", 3))
            if cfg.get("pixelate"):
                # 降采样再放回，做出马赛克质感（题面里写「像素化处理」的用这个）
                factor = max(2, int(cfg["pixelate"]))
                small = (max(1, image.width // factor), max(1, image.height // factor))
                image = image.resize(small, Image.BILINEAR).resize(image.size, Image.NEAREST)
            image.save(dest, "JPEG", quality=args.quality, optimize=True)
        except Exception as exc:
            print(f"  ! {rid} 渲染失败：{exc}", file=sys.stderr)
            failed += 1
            continue

        flags = []
        if cfg.get("approx"):
            approx_ids.append(rid)
            flags.append("示意级")
        if cfg.get("photo"):
            composed_ids.append(rid)
            flags.append("照片底图")
        print(f"  ok  {rid}  [{template}]  {image.size[0]}x{image.size[1]}"
              + (f"  ({'；'.join(flags)})" if flags else ""))
        ok += 1

    print(f"\n完成：渲染 {ok}，跳过 {skipped}，失败 {failed}，需实物摆拍 {photo}")
    if composed_ids:
        print(f"\n其中 {len(composed_ids)} 张为照片底图合成："
              f"底图是真实照片，叠加的敏感主体仍是绘制的，不等于实拍。")
    if approx_ids:
        print(f"\n其中 {len(approx_ids)} 张仍为示意级近似（清单描述的是实物/插画场景，"
              f"程序渲染只能表达大致语义，需人工确认是否够用）：")
        for rid in approx_ids:
            print(f"  - {rid}")
    if photo_ids:
        print("\n以下需人工实物摆拍，脚本不产出：")
        for rid in photo_ids:
            print(f"  - {rid}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
