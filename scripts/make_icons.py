#!/usr/bin/env python3
"""生成 EngineerDiff 应用图标。

用法：
    python scripts/make_icons.py [--out-dir src/engineerdiff/resources]

产物：
    engineerdiff.ico  多尺寸（16/24/32/48/64/128/256）
    engineerdiff.png  512x512 PNG

所有图形由 Pillow 现场绘制，不使用任何外部素材，因此可重复生成、无版权风险。
设计：圆角深蓝底 + 两张文档面板 + 红色“≠”徽标（“两份工程文件存在差异”）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

# 品牌色
BG_TOP = (37, 99, 235)  # #2563EB
BG_BOTTOM = (30, 58, 138)  # #1E3A8A
PANEL = (248, 250, 252)  # #F8FAFC
PANEL_ALT = (241, 245, 249)  # #F1F5F9
LINE = (203, 213, 225)  # #CBD5E1
LINE_ACCENT = (59, 130, 246)  # #3B82F6
DIFF = (220, 38, 38)  # #DC2626
WHITE = (255, 255, 255)

SIZE = 1024
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        color = tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=color)
    return img


def radial_highlight(size: int) -> Image.Image:
    """左上角柔和白色高光，增加立体感（返回带 alpha 的白色层）。"""
    small = 256
    glow = Image.new("L", (small, small), 0)
    px = glow.load()
    cx, cy = int(small * 0.22), int(small * 0.14)
    max_d = small * 0.72
    for y in range(small):
        for x in range(small):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            val = max(0.0, 1.0 - d / max_d)
            px[x, y] = int(46 * val * val)
    glow = glow.resize((size, size), Image.Resampling.BICUBIC)
    layer = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    layer.putalpha(glow)
    return layer


def draw_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: tuple[int, int, int]) -> None:
    draw.rounded_rectangle(box, radius=26, fill=fill)


def draw_text_line(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int = 20,
    color: tuple[int, int, int] = LINE,
) -> None:
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=color)


def build_icon() -> Image.Image:
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    mask = rounded_mask(SIZE, 224)
    canvas.paste(vertical_gradient(SIZE, BG_TOP, BG_BOTTOM).convert("RGBA"), (0, 0), mask)
    glow = radial_highlight(SIZE)
    glow.putalpha(Image.composite(glow.getchannel("A"), Image.new("L", (SIZE, SIZE), 0), mask))
    canvas.alpha_composite(glow)

    # 文档阴影
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((150, 286, 470, 830), radius=26, fill=(0, 0, 0, 90))
    sd.rounded_rectangle((554, 286, 874, 830), radius=26, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(26))
    canvas.alpha_composite(shadow)

    draw = ImageDraw.Draw(canvas)
    # 左右文档面板
    draw_panel(draw, (150, 268, 470, 812), PANEL)
    draw_panel(draw, (554, 268, 874, 812), PANEL_ALT)

    # 面板顶部标题条
    draw_text_line(draw, 186, 316, 156, 26, LINE_ACCENT)
    draw_text_line(draw, 590, 316, 156, 26, LINE_ACCENT)

    # 左侧文档内容
    draw_text_line(draw, 186, 392, 220)
    draw_text_line(draw, 186, 456, 260)
    draw_text_line(draw, 186, 520, 176, 24, DIFF)  # 左侧差异行
    draw_text_line(draw, 186, 590, 236)
    draw_text_line(draw, 186, 654, 190)
    draw_text_line(draw, 186, 718, 214)

    # 右侧文档内容（行宽与左侧不同，表达“同结构、内容有差异”）
    draw_text_line(draw, 590, 392, 236)
    draw_text_line(draw, 590, 456, 218)
    draw_text_line(draw, 590, 520, 148)
    draw_text_line(draw, 590, 590, 240)
    draw_text_line(draw, 590, 654, 196)
    draw_text_line(draw, 590, 718, 232)
    draw_text_line(draw, 590, 782, 120, 24, DIFF)  # 右侧差异行

    # 红色“≠”徽标：白色描边圆 + 红圆 + 白色不等号（斜杠两侧留红色缝隙）
    cx, cy, r = 512, 524, 88
    draw.ellipse((cx - r - 9, cy - r - 9, cx + r + 9, cy + r + 9), fill=WHITE)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=DIFF)

    bar_w, bar_h = 94, 18
    for y in (cy - 44, cy + 26):
        draw.rounded_rectangle(
            (cx - bar_w // 2, y, cx + bar_w // 2, y + bar_h),
            radius=bar_h // 2,
            fill=WHITE,
        )
    slash = [(cx - 42, cy + 70), (cx + 42, cy - 70)]
    draw.line(slash, fill=DIFF, width=30)  # 先在等号上“切”出红色缝隙
    draw.line(slash, fill=WHITE, width=14)  # 再画白色斜杠

    # 白色细边框，提升深色/浅色背景下辨识度
    draw.rounded_rectangle((6, 6, SIZE - 7, SIZE - 7), radius=220, outline=(255, 255, 255, 70), width=8)
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 EngineerDiff 图标")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "src" / "engineerdiff" / "resources",
        help="输出目录（默认 src/engineerdiff/resources）",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        default=None,
        help="可选：生成预览拼图（PNG），用于人工目检各尺寸效果",
    )
    args = parser.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    icon = build_icon().convert("RGBA")
    ico_path = out_dir / "engineerdiff.ico"
    png_path = out_dir / "engineerdiff.png"
    icon.save(ico_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    icon.resize((512, 512), Image.Resampling.LANCZOS).save(png_path, format="PNG", optimize=True)

    if args.preview is not None:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        preview_canvas = Image.new("RGBA", (1500, 420), (245, 245, 245, 255))
        x = 30
        for s in (256, 128, 64, 48, 32, 24, 16):
            thumb = icon.resize((s, s), Image.Resampling.LANCZOS)
            preview_canvas.alpha_composite(thumb, (x, 60 + (256 - s) // 2))
            x += s + 36
        preview_canvas.save(args.preview)

    print(f"icon  -> {ico_path}")
    print(f"png   -> {png_path}")
    if args.preview is not None:
        print(f"preview -> {args.preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
