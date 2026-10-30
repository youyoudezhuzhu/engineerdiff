"""比较流程编排（非 UI，可被 GUI、CLI、self-test 共用）。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .file_loader import determine_mode
from .models import (
    AppSettings,
    CompareMode,
    ComparisonResult,
    CsvComparison,
    Workbook,
)
from .textdiff.engine import compare_text_files


class ComparisonCancelled(RuntimeError):
    pass


Progress = Callable[[int, str], None]
CancelCheck = Callable[[], bool]


def _noop_progress(_percent: int, _message: str) -> None:
    pass


def _never_cancel() -> bool:
    return False


def _check(cancel: CancelCheck) -> None:
    if cancel():
        raise ComparisonCancelled("用户取消了比较")


def run_comparison(
    mode: CompareMode,
    left_path: str | Path,
    right_path: str | Path,
    settings: AppSettings | None = None,
    progress: Progress | None = None,
    cancel: CancelCheck | None = None,
    ocr_service=None,
) -> ComparisonResult:
    """执行比较。异常均带中文消息；不修改输入文件。"""
    settings = settings or AppSettings()
    progress = progress or _noop_progress
    cancel = cancel or _never_cancel
    start = time.time()
    left_path, right_path = str(left_path), str(right_path)
    mode = CompareMode(mode)
    result = ComparisonResult(
        mode=mode,
        left_path=left_path,
        right_path=right_path,
        elapsed=0.0,
    )

    if mode == CompareMode.TEXT:
        progress(10, "正在读取并比较文本…")
        _check(cancel)
        cmp = compare_text_files(left_path, right_path, settings.text)
        result.text = cmp
        result.warnings.extend(cmp.warnings)
        progress(100, f"比较完成，共 {len(cmp.diffs)} 处差异")

    elif mode == CompareMode.CSV:
        from .spreadsheet.csv_parser import parse_csv
        from .spreadsheet.engine import compare_workbooks

        progress(8, "正在解析 CSV（文本视图）…")
        _check(cancel)
        text_cmp = compare_text_files(left_path, right_path, settings.text)
        progress(35, "正在解析 CSV 表格结构…")
        _check(cancel)
        l_sheet, delimiter, l_warn = parse_csv(left_path)
        r_sheet, r_delim, r_warn = parse_csv(right_path)
        if delimiter != r_delim:
            text_cmp.warnings.append(
                f"左右 CSV 分隔符不同（{delimiter!r} / {r_delim!r}），表格视图可能无法逐列对应。"
            )
        left_wb = Workbook(path=left_path, sheets=[l_sheet], fmt="csv", title=Path(left_path).name)
        right_wb = Workbook(path=right_path, sheets=[r_sheet], fmt="csv", title=Path(right_path).name)
        progress(55, "正在比较 CSV 单元格…")
        _check(cancel)
        table = compare_workbooks(left_wb, right_wb, settings.spreadsheet)
        for w in l_warn:
            table.warnings.append(f"左侧 CSV：{w}")
        for w in r_warn:
            table.warnings.append(f"右侧 CSV：{w}")
        result.csv = CsvComparison(
            left=l_sheet,
            right=r_sheet,
            table=table,
            text=text_cmp,
            delimiter=delimiter,
            warnings=table.warnings,
        )
        result.text = text_cmp
        result.workbook = table
        result.warnings.extend(text_cmp.warnings)
        result.warnings.extend(table.warnings)
        progress(100, f"比较完成，表格 {len(table.diffs)} 处差异")

    elif mode == CompareMode.EXCEL:
        from .spreadsheet.engine import compare_workbooks
        from .spreadsheet.loader import load_workbook

        progress(5, "正在读取工作簿 A…")
        _check(cancel)
        left_wb = load_workbook(left_path)
        progress(25, "正在读取工作簿 B…")
        _check(cancel)
        right_wb = load_workbook(right_path)
        progress(50, "正在按 Sheet 名称配对并比较单元格…")
        _check(cancel)
        cmp = compare_workbooks(left_wb, right_wb, settings.spreadsheet)
        result.workbook = cmp
        result.warnings.extend(left_wb.warnings)
        result.warnings.extend(right_wb.warnings)
        result.warnings.extend(cmp.warnings)
        progress(100, f"比较完成，共 {len(cmp.diffs)} 处差异")

    elif mode == CompareMode.IMAGE:
        from .image.engine import compare_images
        from .ocr.engine import OcrService

        if ocr_service is None:
            ocr_service = OcrService()
        progress(3, "正在加载 OCR 引擎…")
        _check(cancel)
        img_cmp = compare_images(
            left_path,
            right_path,
            settings.image,
            ocr_service,
            progress=lambda p, m: progress(5 + int(p * 0.9), m),
            cancel=cancel,
        )
        result.image = img_cmp
        result.warnings.extend(img_cmp.warnings)
        progress(100, f"OCR 比较完成，共 {len(img_cmp.diffs)} 处差异")
    else:  # pragma: no cover
        raise ValueError(f"未知比较模式：{mode}")

    result.elapsed = time.time() - start
    return result


def mode_for_files(left_path: str | Path, right_path: str | Path) -> CompareMode:
    return determine_mode(left_path, right_path)
