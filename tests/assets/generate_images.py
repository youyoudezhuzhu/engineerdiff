"""合成“装置参数界面”截图生成器（仅测试使用）。

使用 Pillow + 仓库内 ``NotoSansSC-Regular.otf`` 绘制中文界面，可指定缩放/平移/
文本内容，生成不同分辨率与位置的左右截图。返回的元数据包含每段文字的**真实
绘制像素 bbox**（由字体的 ink bbox 计算），可用于校验 OCR 框是否落在文字上。

生成图片写到 ``tests/fixtures/generated/``（已被 .gitignore 忽略），不会提交大图。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = Path(__file__).with_name("NotoSansSC-Regular.otf")
GENERATED_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "generated"

#: 基准版面（未缩放坐标），(x, y, 字体类别)
BASE_LAYOUT: dict[str, tuple[int, int, str]] = {
    "title": (16, 4, "title"),
    "label_version": (16, 52, "body"),
    "version": (140, 52, "body"),
    "label_in_1": (16, 96, "body"),
    "value_in_1": (140, 96, "body"),
    "label_out_1": (16, 140, "body"),
    "value_out_1": (140, 140, "body"),
    "label_in_2": (235, 96, "body"),
    "value_in_2": (345, 96, "body"),
    "label_out_2": (235, 140, "body"),
    "value_out_2": (345, 140, "body"),
    "label_check": (16, 184, "body"),
    "check": (140, 184, "body"),
}

DEFAULT_TEXTS: dict[str, str] = {
    "title": "装置参数界面",
    "label_version": "装置版本",
    "version": "1.2.3",
    "label_in_1": "投入",
    "value_in_1": "1.50",
    "label_out_1": "退出",
    "value_out_1": "1.80",
    "label_in_2": "投入",
    "value_in_2": "0.00",
    "label_out_2": "退出",
    "value_out_2": "0.00",
    "label_check": "校验值",
    "check": "A1B2",
}

BASE_WIDTH = 400
BASE_HEIGHT = 240
BODY_FONT_SIZE = 17
TITLE_FONT_SIZE = 21

TEXT_COLOR = (24, 26, 30)
TITLE_COLOR = (28, 64, 120)
LINE_COLOR = (180, 186, 194)
BACKGROUND = (250, 250, 250)


def ensure_generated_dir() -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    return GENERATED_DIR


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), max(6, int(size)))


def _draw_text_with_bbox(
    draw: ImageDraw.ImageDraw,
    canvas: Image.Image,
    text: str,
    origin: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    color: tuple[int, int, int],
) -> list[int]:
    """绘制文字并返回真实墨迹 bbox（原图像素，x0,y0,x1,y1）。"""
    draw.text(origin, text, font=font, fill=color)
    # 用字体的 ink bbox 计算（Pillow 的 getbbox 相对绘制原点，含上下留白偏移）
    try:
        bbox = font.getbbox(text)
    except Exception:  # pragma: no cover - 极端字体问题
        bbox = (0, 0, max(1, int(font.size) * len(text)), int(font.size))
    x0 = int(origin[0] + bbox[0])
    y0 = int(origin[1] + bbox[1])
    x1 = int(origin[0] + bbox[2])
    y1 = int(origin[1] + bbox[3])
    x0 = max(0, min(canvas.width - 1, x0))
    y0 = max(0, min(canvas.height - 1, y0))
    x1 = max(x0 + 1, min(canvas.width, x1))
    y1 = max(y0 + 1, min(canvas.height, y1))
    return [x0, y0, x1, y1]


def render_ui_screenshot(
    path: str | Path,
    *,
    scale: float = 1.0,
    offset: tuple[int, int] = (0, 0),
    values: dict[str, str] | None = None,
    extra_texts: list[tuple[str, int, int]] | None = None,
    body_font_size: int | None = None,
    title_font_size: int | None = None,
    margin: int = 16,
    write_metadata: bool = True,
) -> dict[str, Any]:
    """生成一张合成界面截图。

    参数
    ----
    scale: 整体缩放（模拟不同分辨率/UI 缩放）
    offset: 整体平移像素（模拟窗口位置/截图边缘范围不同）
    values: 覆盖 ``DEFAULT_TEXTS`` 中的文字（例如版本号/小数）
    extra_texts: 额外文字 ``[(text, base_x, base_y), ...]``（用于仅一侧测试）
    """
    texts = dict(DEFAULT_TEXTS)
    if values:
        texts.update({str(k): str(v) for k, v in values.items()})
    body_size = body_font_size or round(BODY_FONT_SIZE * scale)
    title_size = title_font_size or round(TITLE_FONT_SIZE * scale)
    body_font = _load_font(body_size)
    title_font = _load_font(title_size)

    ox, oy = int(offset[0]), int(offset[1])
    width = int(round(BASE_WIDTH * scale)) + ox + margin
    height = int(round(BASE_HEIGHT * scale)) + oy + margin
    canvas = Image.new("RGB", (max(80, width), max(80, height)), BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    # 版面装饰（给 ORB 提供非文字的稳定特征，同时更接近真实界面截图）
    draw.rectangle(
        [ox + 4, oy + 4, ox + int(round((BASE_WIDTH - 8) * scale)), oy + int(round((BASE_HEIGHT - 8) * scale))],
        outline=(210, 214, 220),
        width=max(1, round(scale)),
    )
    draw.line(
        [
            (ox + 8, oy + int(round(40 * scale))),
            (ox + int(round((BASE_WIDTH - 12) * scale)), oy + int(round(40 * scale))),
        ],
        fill=LINE_COLOR,
        width=max(1, round(scale)),
    )
    draw.line(
        [
            (ox + 8, oy + int(round(214 * scale))),
            (ox + int(round((BASE_WIDTH - 12) * scale)), oy + int(round(214 * scale))),
        ],
        fill=LINE_COLOR,
        width=max(1, round(scale)),
    )
    draw.rectangle(
        [ox + 8, oy + int(round(12 * scale)), ox + int(round(14 * scale)), oy + int(round(30 * scale))],
        fill=(46, 92, 168),
    )

    boxes: dict[str, dict[str, Any]] = {}
    for key, (bx, by, kind) in BASE_LAYOUT.items():
        text = texts.get(key, "")
        if not text:
            continue
        font = title_font if kind == "title" else body_font
        color = TITLE_COLOR if kind == "title" else TEXT_COLOR
        origin = (ox + int(round(bx * scale)), oy + int(round(by * scale)))
        bbox = _draw_text_with_bbox(draw, canvas, text, origin, font, color)
        boxes[key] = {"text": text, "bbox": bbox, "font_size": int(font.size), "kind": kind}

    for index, (text, bx, by) in enumerate(extra_texts or []):
        origin = (ox + int(round(bx * scale)), oy + int(round(by * scale)))
        bbox = _draw_text_with_bbox(draw, canvas, text, origin, body_font, TEXT_COLOR)
        boxes[f"extra_{index}"] = {
            "text": text,
            "bbox": bbox,
            "font_size": int(body_font.size),
            "kind": "body",
        }

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    metadata: dict[str, Any] = {
        "path": str(output),
        "image_size": [canvas.width, canvas.height],
        "scale": float(scale),
        "offset": [ox, oy],
        "base_size": [BASE_WIDTH, BASE_HEIGHT],
        "font_size": {"body": int(body_size), "title": int(title_size)},
        "texts": boxes,
    }
    if write_metadata:
        output.with_suffix(output.suffix + ".json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return metadata


def render_default_pair(
    directory: str | Path | None = None,
    *,
    left_values: dict[str, str] | None = None,
    right_values: dict[str, str] | None = None,
    right_scale: float = 1.2,
    right_offset: tuple[int, int] = (30, 18),
    extra_right_texts: list[tuple[str, int, int]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """生成标准左右截图对（左图为基准，右图不同分辨率+平移）。"""
    out_dir = Path(directory) if directory else ensure_generated_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    left = render_ui_screenshot(out_dir / "ui_left.png", values=left_values)
    right = render_ui_screenshot(
        out_dir / "ui_right.png",
        scale=right_scale,
        offset=right_offset,
        values=right_values,
        extra_texts=extra_right_texts,
    )
    return left, right


__all__ = [
    "BASE_HEIGHT",
    "BASE_LAYOUT",
    "BASE_WIDTH",
    "DEFAULT_TEXTS",
    "FONT_PATH",
    "GENERATED_DIR",
    "ensure_generated_dir",
    "render_default_pair",
    "render_ui_screenshot",
]
