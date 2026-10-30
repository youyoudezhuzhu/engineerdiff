"""图片（截图）比较引擎：左右 OCR + 文字匹配 + 统一差异输出。"""

from __future__ import annotations

import time
from typing import Any, Callable

from PIL import Image

from ..models import ImageComparison, ImageOptions, OcrBox, OcrPage
from ..ocr.cache import sha256_file
from ..ocr.engine import CancelCallback, OcrCancelled, OcrError, OcrService, ProgressCallback
from .matcher import match_pages

#: 图片比较时左右两侧的进度区间
_LEFT_SPAN = (0, 35)
_RIGHT_SPAN = (35, 70)
_MATCH_SPAN = (70, 96)


class ImageCompareError(RuntimeError):
    """图片比较失败（中文消息可直接展示；OCR 失败不会被视为一致）。"""


def _blank_page(path: str) -> OcrPage:
    try:
        with Image.open(path) as image:
            width, height = int(image.width), int(image.height)
    except Exception:
        width = height = 0
    return OcrPage(path=str(path), width=width, height=height, boxes=[],
                   warnings=["图片完全一致，未执行 OCR"])


def _report(progress: ProgressCallback | None, percent: int, message: str) -> None:
    if progress is None:
        return
    try:
        progress(max(0, min(100, int(percent))), message)
    except Exception:
        pass


def _check_cancel(cancel: CancelCallback | None) -> None:
    if cancel is None:
        return
    try:
        cancelled = bool(cancel())
    except Exception:
        cancelled = False
    if cancelled:
        raise OcrCancelled("图片比较已取消")


def _sub_progress(
    progress: ProgressCallback | None,
    base: int,
    span: int,
    label: str,
) -> ProgressCallback | None:
    if progress is None:
        return None

    def callback(percent: int, message: str) -> None:
        _report(progress, base + round(span * max(0, min(100, percent)) / 100.0), f"{label}：{message}")

    return callback


def _run_ocr(
    ocr: OcrService,
    image_path: str,
    label: str,
    progress: ProgressCallback | None,
    cancel: CancelCallback | None,
    warnings: list[str],
) -> OcrPage:
    callback = _sub_progress(progress, _LEFT_SPAN[0] if label == "左侧" else _RIGHT_SPAN[0], 35, label)
    try:
        page = ocr.recognize(image_path, progress=callback, cancel=cancel)
    except OcrCancelled:
        raise
    except OcrError as exc:
        raise ImageCompareError(f"{label} OCR 识别失败：{exc}") from exc
    except Exception as exc:  # 未预期的实现错误同样不得当成“一致”
        raise ImageCompareError(f"{label} OCR 识别失败：{exc}") from exc
    if not page.boxes:
        warnings.append(f"{label}图片未识别到文字，无法确认内容是否一致；请检查截图清晰度或手动校正")
    return page


def _apply_overrides(
    page: OcrPage,
    side: str,
    overrides: dict[int, str] | None,
    warnings: list[str],
) -> list[OcrBox]:
    """应用人工修正文本，保留 raw_text / overridden 以便追溯。"""
    if not overrides:
        return page.boxes
    by_id = {box.id: box for box in page.boxes}
    label = "左侧" if side == "left" else "右侧"
    missing: list[int] = []
    for raw_id, new_text in overrides.items():
        try:
            box_id = int(raw_id)
        except (TypeError, ValueError):
            missing.append(raw_id)  # type: ignore[arg-type]
            continue
        box = by_id.get(box_id)
        if box is None:
            missing.append(box_id)
            continue
        original = box.raw_text if box.overridden else box.text
        box.raw_text = original
        box.text = str(new_text)
        box.overridden = box.text != original
    if missing:
        shown = ", ".join(str(v) for v in missing[:8])
        more = "" if len(missing) <= 8 else f" 等 {len(missing)} 个"
        warnings.append(f"{label}文本修正引用了不存在的文字框：{shown}{more}")
    return page.boxes


def _confidence_warning(page: OcrPage, side: str, threshold: float, warnings: list[str]) -> None:
    if not page.boxes:
        return
    values = sorted(box.confidence for box in page.boxes)
    median = values[len(values) // 2]
    if median < threshold:
        label = "左侧" if side == "left" else "右侧"
        warnings.append(f"{label}图片 OCR 整体置信度偏低（中位数 {median:.2f}），结果可能不准确，建议人工校对")


def compare_images(
    left_path: str,
    right_path: str,
    options: ImageOptions | None = None,
    ocr: OcrService | None = None,
    progress: Callable[[int, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> ImageComparison:
    """比较两张截图：分别 OCR，再按文字匹配生成 ``ImageComparison``。

    - ``options.text_overrides`` 会先应用到对应 OCR 结果（记录 raw_text/overridden）；
    - ``options.manual_pairs`` 强制左/右文字框对应；
    - 任一侧 OCR 失败抛 ``ImageCompareError``；无文字时写 warning，绝不判为一致。
    """
    if ocr is None:
        raise ImageCompareError("未提供 OCR 服务，无法进行图片比较")
    options = options or ImageOptions()
    warnings: list[str] = []
    started = time.perf_counter()
    _report(progress, 0, "准备图片比较")
    _check_cancel(cancel)

    # 完全相同的文件无需 OCR（常见于批量比较中同一截图被重复加入）。
    # 这不是“用 OCR 失败冒充一致”：只有字节级 SHA-256 完全一致才跳过。
    try:
        has_overrides = bool(options.manual_pairs) or any(
            bool(v) for v in (options.text_overrides or {}).values()
        )
        if (
            isinstance(ocr, OcrService)
            and not has_overrides
            and sha256_file(left_path) == sha256_file(right_path)
        ):
            left_page = _blank_page(left_path)
            right_page = _blank_page(right_path)
            warnings.append("左右图片文件内容完全一致，已跳过 OCR。")
            _report(progress, 100, "图片完全一致，跳过 OCR")
            return ImageComparison(
                left=left_page,
                right=right_page,
                diffs=[],
                warnings=warnings,
                transform={"method": "identical-file", "pairs": 0},
                settings=options.as_dict(),
                elapsed=time.perf_counter() - started,
            )
    except OSError:
        pass

    left_page = _run_ocr(ocr, left_path, "左侧", progress, cancel, warnings)
    _check_cancel(cancel)
    right_page = _run_ocr(ocr, right_path, "右侧", progress, cancel, warnings)
    _check_cancel(cancel)

    try:
        _apply_overrides(left_page, "left", options.text_overrides.get("left"), warnings)
        _apply_overrides(right_page, "right", options.text_overrides.get("right"), warnings)
    except Exception as exc:
        raise ImageCompareError(f"应用人工修正文本失败：{exc}") from exc

    _confidence_warning(left_page, "left", float(options.confidence_threshold), warnings)
    _confidence_warning(right_page, "right", float(options.confidence_threshold), warnings)

    _report(progress, _MATCH_SPAN[0], "匹配文字差异")
    _check_cancel(cancel)
    try:
        diffs, transform_info = match_pages(left_page, right_page, options)
    except OcrCancelled:
        raise
    except Exception as exc:
        raise ImageCompareError(f"文字匹配失败：{exc}") from exc
    _check_cancel(cancel)

    _report(progress, 96, "整理比较结果")
    elapsed = time.perf_counter() - started
    comparison = ImageComparison(
        left=left_page,
        right=right_page,
        diffs=diffs,
        warnings=warnings,
        transform=transform_info,
        settings=options.as_dict(),
        elapsed=elapsed,
    )
    _report(progress, 100, f"图片比较完成：{len(diffs)} 处差异")
    return comparison


__all__ = ["ImageCompareError", "compare_images"]
