"""Excel / CSV 表格比较引擎。

契约见 docs/ui-contracts.md 2.3。要点：

* 按 Sheet 名称精确配对，与工作簿内顺序无关；
* 单元格严格坐标比较，空白/类型/公式/缓存/数值容差按契约处理；
* 合并单元格区域不一致在锚点生成一条橙色 UNCERTAIN 差异；
* 差异顺序稳定：工作表顺序（左侧优先，右侧仅有的随后）、行、列；
* 差异 id 稳定：``cell:{sheet}:{row}:{col}`` / ``sheet:{name}``；
* ``smart_rows=True`` 为实验性整行对齐模式，严格模式行为不受影响。

本模块不依赖 Qt。
"""

from __future__ import annotations

import datetime as _dt
import difflib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from ..models import (
    Cell,
    CellType,
    DiffItem,
    DiffKind,
    DiffLocation,
    Severity,
    Sheet,
    SheetComparison,
    SheetStatus,
    SpreadsheetOptions,
    Workbook,
    WorkbookComparison,
)
from .csv_parser import csv_to_workbook, parse_csv
from .loader import cell_display, classify_value, column_letter

_TYPE_LABEL = {
    CellType.BLANK: "空白",
    CellType.NUMBER: "数值",
    CellType.TEXT: "文本",
    CellType.BOOL: "布尔",
    CellType.DATE: "日期",
    CellType.ERROR: "错误",
    CellType.FORMULA: "公式",
}

_FORMULA_MODES = ("formula", "value")
_SMART_ROW_LIMIT = 3_000
_MERGE_DETAIL = "合并单元格区域不一致"


# ---------------------------------------------------------------------------
# 值规范化
# ---------------------------------------------------------------------------


def _normalize_number(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite():
        return None
    return number


def _normalize_date(value: Any) -> str:
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day).isoformat()
    if isinstance(value, _dt.time):
        return value.isoformat()
    return str(value)


def _cell_location(sheet_name: str, row: int, col: int, cell: Cell) -> DiffLocation:
    return DiffLocation(
        kind="cell",
        row=row,
        col=col,
        sheet=sheet_name,
        bbox=None,
        text=cell.display if cell is not None else "",
    )


def _merge_span_desc(span: tuple[int, int] | None) -> str:
    if not span:
        return "未合并"
    return f"{span[0]}行x{span[1]}列"


# ---------------------------------------------------------------------------
# 单单元格比较
# ---------------------------------------------------------------------------


@dataclass
class _CellCompareResult:
    equal: bool
    uncertain: bool = False
    detail: str = ""


def _effective_value(cell: Cell) -> tuple[CellType, Any, str, bool]:
    """按“值比较”语义返回 (类型, 值, 展示文本, 缓存是否缺失)。"""
    if cell.type == CellType.FORMULA:
        if cell.cached is None:
            return CellType.FORMULA, None, cell.formula or "", True
        cached = cell.cached
        cell_type = classify_value(cached)
        display = cell_display(cached, cell_type, cell.style.number_format)
        return cell_type, cached, display, False
    return cell.type, cell.value, cell.display, False


def _cache_missing_detail(left_cell: Cell, right_cell: Cell) -> str:
    left_formula = left_cell.formula or "无"
    right_formula = right_cell.formula or "无"
    return (
        "公式缓存值缺失，按值比较无法确认是否相同"
        f"（左侧公式：{left_formula}；右侧公式：{right_formula}）"
    )


def _compare_values(
    left_cell: Cell,
    right_cell: Cell,
    options: SpreadsheetOptions,
) -> _CellCompareResult:
    mode = options.formula_mode if options.formula_mode in _FORMULA_MODES else "formula"
    if mode == "formula" and (left_cell.formula is not None or right_cell.formula is not None):
        left_formula = (left_cell.formula or "").strip()
        right_formula = (right_cell.formula or "").strip()
        if left_cell.formula is not None and right_cell.formula is not None and left_formula == right_formula:
            return _CellCompareResult(True)
        if left_cell.formula is not None and right_cell.formula is not None:
            return _CellCompareResult(False, detail=f"公式不同：{left_formula} ≠ {right_formula}")
        return _CellCompareResult(
            False,
            detail=f"一侧为公式、另一侧不是：{left_formula or '无公式'} ≠ {right_formula or '无公式'}",
        )

    if mode == "value":
        left_type, left_value, left_display, left_missing = _effective_value(left_cell)
        right_type, right_value, right_display, right_missing = _effective_value(right_cell)
        if left_missing or right_missing:
            return _CellCompareResult(False, uncertain=True, detail=_cache_missing_detail(left_cell, right_cell))
    else:
        left_type, left_value, left_display = left_cell.type, left_cell.value, left_cell.display
        right_type, right_value, right_display = right_cell.type, right_cell.value, right_cell.display

    return _compare_literals(
        left_type,
        left_value,
        left_display,
        right_type,
        right_value,
        right_display,
        options,
    )


def _compare_literals(
    left_type: CellType,
    left_value: Any,
    left_display: str,
    right_type: CellType,
    right_value: Any,
    right_display: str,
    options: SpreadsheetOptions,
) -> _CellCompareResult:
    if left_type == right_type == CellType.BLANK:
        return _CellCompareResult(True)
    if left_type != right_type:
        return _CellCompareResult(
            False,
            detail=(
                f"类型不同：{_TYPE_LABEL.get(left_type, left_type.value)} ↔ "
                f"{_TYPE_LABEL.get(right_type, right_type.value)}"
                f"（{left_display or '空白'} ↔ {right_display or '空白'}）"
            ),
        )
    if left_type == CellType.BLANK:
        return _CellCompareResult(True)
    if left_type == CellType.NUMBER:
        return _compare_numbers(left_value, left_display, right_value, right_display, options)
    if left_type == CellType.TEXT:
        if str(left_value if left_value is not None else left_display) == str(
            right_value if right_value is not None else right_display
        ):
            return _CellCompareResult(True)
        return _CellCompareResult(False, detail=f"文本不同：“{left_display}” ≠ “{right_display}”")
    if left_type == CellType.BOOL:
        if bool(left_value) == bool(right_value):
            return _CellCompareResult(True)
        return _CellCompareResult(False, detail=f"布尔值不同：{left_display} ≠ {right_display}")
    if left_type == CellType.DATE:
        if _normalize_date(left_value) == _normalize_date(right_value):
            return _CellCompareResult(True)
        return _CellCompareResult(False, detail=f"日期不同：{left_display} ≠ {right_display}")
    if left_type == CellType.ERROR:
        if str(left_value) == str(right_value) and left_display == right_display:
            return _CellCompareResult(True)
        return _CellCompareResult(False, detail=f"错误值不同：{left_display} ≠ {right_display}")
    # 兜底：按展示文本严格比较
    if left_display == right_display:
        return _CellCompareResult(True)
    return _CellCompareResult(False, detail=f"内容不同：{left_display} ≠ {right_display}")


def _compare_numbers(
    left_value: Any,
    left_display: str,
    right_value: Any,
    right_display: str,
    options: SpreadsheetOptions,
) -> _CellCompareResult:
    left_number = _normalize_number(left_value)
    right_number = _normalize_number(right_value)
    if left_number is None or right_number is None:
        if str(left_value) == str(right_value):
            return _CellCompareResult(True)
        return _CellCompareResult(False, detail=f"数值无法比较：{left_display} ≠ {right_display}")
    if left_number == right_number:
        return _CellCompareResult(True)
    tolerance = float(options.numeric_tolerance or 0.0)
    if tolerance > 0:
        difference = abs(left_number - right_number)
        scale = max(abs(left_number), abs(right_number))
        if difference <= Decimal(str(tolerance)) or difference <= Decimal(str(tolerance)) * scale:
            return _CellCompareResult(True)
    if tolerance > 0:
        return _CellCompareResult(
            False,
            detail=f"数值不同（超出容差 {tolerance:g}）：{left_display} ≠ {right_display}",
        )
    return _CellCompareResult(False, detail=f"数值不同：{left_display} ≠ {right_display}")


# ---------------------------------------------------------------------------
# 差异构造
# ---------------------------------------------------------------------------


def _build_cell_diff(
    sheet_name: str,
    left_row: int,
    left_col: int,
    right_row: int,
    right_col: int,
    left_cell: Cell | None,
    right_cell: Cell | None,
    left_present: bool,
    right_present: bool,
    left_display: str,
    right_display: str,
    kind: DiffKind,
    severity: Severity = Severity.CONFIRMED,
    detail: str = "",
    uncertain: bool = False,
    diff_id: str | None = None,
) -> DiffItem:
    left_location = (
        _cell_location(sheet_name, left_row, left_col, left_cell) if left_present else None
    )
    right_location = (
        _cell_location(sheet_name, right_row, right_col, right_cell) if right_present else None
    )
    if left_location is not None:
        left_location.text = left_display
    if right_location is not None:
        right_location.text = right_display
    return DiffItem(
        id=diff_id or f"cell:{sheet_name}:{left_row if left_present else right_row}:{left_col if left_present else right_col}",
        kind=kind,
        severity=severity,
        title=f"单元格 {column_letter(left_col if left_present else right_col)}{(left_row if left_present else right_row) + 1}",
        left=left_location,
        right=right_location,
        needs_review=uncertain,
        detail=detail,
        group="cell",
    )




def _make_merge_diff(
    sheet_name: str,
    row: int,
    col: int,
    left_cell: Cell,
    right_cell: Cell,
    left_span: tuple[int, int] | None,
    right_span: tuple[int, int] | None,
    left_present: bool,
    right_present: bool,
) -> DiffItem:
    diff = _build_cell_diff(
        sheet_name,
        row,
        col,
        row,
        col,
        left_cell if left_present else None,
        right_cell if right_present else None,
        left_present,
        right_present,
        left_cell.display if left_present else "",
        right_cell.display if right_present else "",
        DiffKind.MODIFIED,
        severity=Severity.UNCERTAIN,
        detail=_MERGE_DETAIL,
        uncertain=True,
    )
    for location, span in ((diff.left, left_span), (diff.right, right_span)):
        if location is not None:
            location.extra["merged"] = span is not None
            location.extra["span"] = list(span) if span else None
            location.extra["span_desc"] = _merge_span_desc(span)
    return diff


def _make_sheet_only_diff(sheet: Sheet, side: str) -> DiffItem:
    name = sheet.name
    location = DiffLocation(kind="sheet", sheet=name, text=name)
    if side == "left":
        return DiffItem(
            id=f"sheet:{name}",
            kind=DiffKind.ONLY_LEFT,
            severity=Severity.CONFIRMED,
            title=f"工作表“{name}”仅左侧存在",
            left=location,
            right=None,
            group="sheet",
            detail="该工作表仅存在于左侧工作簿",
        )
    return DiffItem(
        id=f"sheet:{name}",
        kind=DiffKind.ONLY_RIGHT,
        severity=Severity.CONFIRMED,
        title=f"工作表“{name}”仅右侧存在",
        left=None,
        right=location,
        group="sheet",
        detail="该工作表仅存在于右侧工作簿",
    )


# ---------------------------------------------------------------------------
# 合并单元格结构
# ---------------------------------------------------------------------------


def _merge_maps(sheet: Sheet) -> tuple[dict[tuple[int, int], tuple[int, int]], set[tuple[int, int]]]:
    anchors: dict[tuple[int, int], tuple[int, int]] = {}
    covered: set[tuple[int, int]] = set()
    for row, col, row_span, col_span in sheet.merged:
        if row_span <= 0 or col_span <= 0:
            continue
        if row >= sheet.nrows or col >= sheet.ncols:
            continue
        row_span = min(row_span, sheet.nrows - row)
        col_span = min(col_span, sheet.ncols - col)
        anchors[(row, col)] = (row_span, col_span)
        for rr in range(row, row + row_span):
            for cc in range(col, col + col_span):
                if (rr, cc) != (row, col):
                    covered.add((rr, cc))
    if sheet.merged:
        return anchors, covered
    # 兼容仅设置 Cell.span 而没有填写 Sheet.merged 的内存工作簿。
    for row in range(sheet.nrows):
        for col in range(sheet.ncols):
            span = sheet.cell(row, col).span
            if not span:
                continue
            row_span = min(span[0], sheet.nrows - row)
            col_span = min(span[1], sheet.ncols - col)
            anchors.setdefault((row, col), (row_span, col_span))
            for rr in range(row, row + row_span):
                for cc in range(col, col + col_span):
                    if (rr, cc) != (row, col):
                        covered.add((rr, cc))
    return anchors, covered


# ---------------------------------------------------------------------------
# 严格坐标比较
# ---------------------------------------------------------------------------


def _compare_sheet_strict(
    name: str,
    left_sheet: Sheet,
    right_sheet: Sheet,
    options: SpreadsheetOptions,
) -> list[DiffItem]:
    left_anchors, left_covered = _merge_maps(left_sheet)
    right_anchors, right_covered = _merge_maps(right_sheet)
    nrows = max(left_sheet.nrows, right_sheet.nrows)
    ncols = max(left_sheet.ncols, right_sheet.ncols)
    diffs: list[DiffItem] = []
    for row in range(nrows):
        for col in range(ncols):
            left_present = row < left_sheet.nrows and col < left_sheet.ncols
            right_present = row < right_sheet.nrows and col < right_sheet.ncols
            left_cell = left_sheet.rows[row][col] if left_present else Cell()
            right_cell = right_sheet.rows[row][col] if right_present else Cell()
            left_span = left_anchors.get((row, col))
            right_span = right_anchors.get((row, col))
            if left_span != right_span:
                diffs.append(
                    _make_merge_diff(
                        name,
                        row,
                        col,
                        left_cell,
                        right_cell,
                        left_span,
                        right_span,
                        left_present,
                        right_present,
                    )
                )
                continue
            if (row, col) in left_covered or (row, col) in right_covered:
                continue
            result = _compare_values(left_cell, right_cell, options)
            if result.equal:
                continue
            if left_present and right_present:
                kind = DiffKind.MODIFIED
            elif left_present:
                kind = DiffKind.REMOVED
            else:
                kind = DiffKind.ADDED
            diffs.append(
                _build_cell_diff(
                    name,
                    row,
                    col,
                    row,
                    col,
                    left_cell if left_present else None,
                    right_cell if right_present else None,
                    left_present,
                    right_present,
                    left_cell.display,
                    right_cell.display,
                    kind,
                    severity=Severity.UNCERTAIN if result.uncertain else Severity.CONFIRMED,
                    detail=result.detail,
                    uncertain=result.uncertain,
                )
            )
    return diffs


# ---------------------------------------------------------------------------
# 智能行对齐（实验性）
# ---------------------------------------------------------------------------


def _cell_signature(cell: Cell) -> tuple:
    cell_type = cell.type
    if cell_type == CellType.FORMULA:
        cached = cell.cached
        cached_type = classify_value(cached) if cached is not None else CellType.BLANK
        return ("f", (cell.formula or "").strip(), _literal_signature(cached_type, cached, ""))
    return _literal_signature(cell_type, cell.value, cell.display)


def _literal_signature(cell_type: CellType, value: Any, display: str) -> tuple:
    if cell_type == CellType.NUMBER:
        number = _normalize_number(value)
        return ("n", str(number) if number is not None else display)
    if cell_type == CellType.DATE:
        return ("d", _normalize_date(value))
    if cell_type == CellType.BOOL:
        return ("b", bool(value))
    if cell_type == CellType.ERROR:
        return ("e", display or str(value))
    if cell_type == CellType.TEXT:
        return ("t", str(value if value is not None else display))
    return ("blank",)


def _row_signature(sheet: Sheet, row: int, ncols: int) -> tuple:
    signature: list[tuple] = []
    for col in range(ncols):
        if row < sheet.nrows and col < sheet.ncols:
            signature.append(_cell_signature(sheet.rows[row][col]))
        else:
            signature.append(("blank",))
    return tuple(signature)


def _smart_unpaired_row_diffs(
    sheet_name: str,
    side: str,
    row: int,
    sheet: Sheet,
    ncols: int,
) -> list[DiffItem]:
    diffs: list[DiffItem] = []
    for col in range(ncols):
        if col >= sheet.ncols or row >= sheet.nrows:
            break
        cell = sheet.rows[row][col]
        if cell.type == CellType.BLANK:
            continue
        present = side == "left"
        kind = DiffKind.REMOVED if present else DiffKind.ADDED
        diff = _build_cell_diff(
            sheet_name,
            row,
            col,
            row,
            col,
            cell if present else None,
            None if present else cell,
            present,
            not present,
            cell.display,
            "",
            kind,
            detail="整行没有对应行（智能行对齐）",
            diff_id=f"cell:{sheet_name}:{'l' if present else 'r'}:{row}:{col}",
        )
        diffs.append(diff)
    return diffs


def _compare_aligned_cells(
    sheet_name: str,
    left_row: int,
    left_col: int,
    right_row: int,
    right_col: int,
    left_sheet: Sheet,
    right_sheet: Sheet,
    options: SpreadsheetOptions,
) -> DiffItem | None:
    left_present = left_row < left_sheet.nrows and left_col < left_sheet.ncols
    right_present = right_row < right_sheet.nrows and right_col < right_sheet.ncols
    left_cell = left_sheet.rows[left_row][left_col] if left_present else Cell()
    right_cell = right_sheet.rows[right_row][right_col] if right_present else Cell()
    result = _compare_values(left_cell, right_cell, options)
    if result.equal:
        return None
    if left_present and right_present:
        kind = DiffKind.MODIFIED
    elif left_present:
        kind = DiffKind.REMOVED
    else:
        kind = DiffKind.ADDED
    return _build_cell_diff(
        sheet_name,
        left_row,
        left_col,
        right_row,
        right_col,
        left_cell if left_present else None,
        right_cell if right_present else None,
        left_present,
        right_present,
        left_cell.display,
        right_cell.display,
        kind,
        severity=Severity.UNCERTAIN if result.uncertain else Severity.CONFIRMED,
        detail=result.detail,
        uncertain=result.uncertain,
    )


def _compare_sheet_smart(
    name: str,
    left_sheet: Sheet,
    right_sheet: Sheet,
    options: SpreadsheetOptions,
) -> tuple[list[DiffItem], list[str]]:
    warnings: list[str] = []
    if left_sheet.merged or right_sheet.merged:
        warnings.append(f"工作表“{name}”包含合并单元格，智能行对齐已回退为严格坐标比较。")
        return _compare_sheet_strict(name, left_sheet, right_sheet, options), warnings
    if max(left_sheet.nrows, right_sheet.nrows) > _SMART_ROW_LIMIT:
        warnings.append(
            f"工作表“{name}”行数超过 {_SMART_ROW_LIMIT}，智能行对齐已回退为严格坐标比较。"
        )
        return _compare_sheet_strict(name, left_sheet, right_sheet, options), warnings

    ncols = max(left_sheet.ncols, right_sheet.ncols)
    left_signatures = [_row_signature(left_sheet, row, ncols) for row in range(left_sheet.nrows)]
    right_signatures = [_row_signature(right_sheet, row, ncols) for row in range(right_sheet.nrows)]
    matcher = difflib.SequenceMatcher(None, left_signatures, right_signatures, autojunk=False)
    diffs: list[DiffItem] = []
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        left_rows = list(range(left_start, left_end))
        right_rows = list(range(right_start, right_end))
        if tag == "equal":
            for left_row, right_row in zip(left_rows, right_rows):
                for col in range(ncols):
                    diff = _compare_aligned_cells(
                        name, left_row, col, right_row, col, left_sheet, right_sheet, options
                    )
                    if diff is not None:
                        diffs.append(diff)
            continue
        paired = min(len(left_rows), len(right_rows))
        for index in range(paired):
            left_row, right_row = left_rows[index], right_rows[index]
            for col in range(ncols):
                diff = _compare_aligned_cells(
                    name, left_row, col, right_row, col, left_sheet, right_sheet, options
                )
                if diff is not None:
                    diffs.append(diff)
        for left_row in left_rows[paired:]:
            diffs.extend(_smart_unpaired_row_diffs(name, "left", left_row, left_sheet, ncols))
        for right_row in right_rows[paired:]:
            diffs.extend(_smart_unpaired_row_diffs(name, "right", right_row, right_sheet, ncols))

    diffs.sort(key=_diff_sort_key)
    warnings.append("智能行对齐为实验性功能：按行签名对齐后再比较，结果可能与严格坐标模式不同。")
    return diffs, warnings


def _diff_sort_key(diff: DiffItem) -> tuple[int, int, str]:
    if diff.left is not None and diff.left.row is not None:
        return diff.left.row, diff.left.col or 0, diff.id
    if diff.right is not None and diff.right.row is not None:
        return diff.right.row, diff.right.col or 0, diff.id
    return 0, 0, diff.id


# ---------------------------------------------------------------------------
# 工作簿比较
# ---------------------------------------------------------------------------


def _pair_sheet_names(left: Workbook, right: Workbook) -> list[str]:
    left_names = [sheet.name for sheet in left.sheets]
    right_names = [sheet.name for sheet in right.sheets]
    pairs = list(left_names)
    for name in right_names:
        if name not in pairs:
            pairs.append(name)
    return pairs


def _dedupe_warnings(warnings: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for warning in warnings:
        if warning and warning not in seen:
            seen.add(warning)
            result.append(warning)
    return result


def compare_workbooks(
    left: Workbook,
    right: Workbook,
    options: SpreadsheetOptions | None = None,
) -> WorkbookComparison:
    """按 Sheet 名称配对比较两个工作簿。"""
    options = options or SpreadsheetOptions()
    comparison = WorkbookComparison(left=left, right=right, settings=options.as_dict())
    comparison.warnings.extend(left.warnings)
    comparison.warnings.extend(right.warnings)

    if options.formula_mode == "formula" and (left.fmt == "xls" or right.fmt == "xls"):
        comparison.warnings.append(
            "XLS 格式无法读取公式表达式，公式单元格只能按缓存值比较；"
            "如需严格比较公式请两侧都使用 XLSX。"
        )

    for name in _pair_sheet_names(left, right):
        left_sheet = left.sheet(name)
        right_sheet = right.sheet(name)
        sheet_comparison = SheetComparison(name=name)
        if left_sheet is None:
            sheet_comparison.right = right_sheet
            sheet_comparison.right_index = _sheet_index(right, name)
            sheet_comparison.status = SheetStatus.ONLY_RIGHT
            sheet_comparison.diffs = [_make_sheet_only_diff(right_sheet, "right")]
        elif right_sheet is None:
            sheet_comparison.left = left_sheet
            sheet_comparison.left_index = _sheet_index(left, name)
            sheet_comparison.status = SheetStatus.ONLY_LEFT
            sheet_comparison.diffs = [_make_sheet_only_diff(left_sheet, "left")]
        else:
            sheet_comparison.left = left_sheet
            sheet_comparison.right = right_sheet
            sheet_comparison.left_index = _sheet_index(left, name)
            sheet_comparison.right_index = _sheet_index(right, name)
            if options.smart_rows:
                diffs, smart_warnings = _compare_sheet_smart(name, left_sheet, right_sheet, options)
                sheet_comparison.warnings.extend(smart_warnings)
                comparison.warnings.extend(smart_warnings)
            else:
                diffs = _compare_sheet_strict(name, left_sheet, right_sheet, options)
            sheet_comparison.diffs = diffs
            sheet_comparison.status = SheetStatus.DIFFERENT if diffs else SheetStatus.EQUAL
        comparison.sheets.append(sheet_comparison)
        comparison.diffs.extend(sheet_comparison.diffs)

    missing_cache = sum(
        1
        for diff in comparison.diffs
        if diff.group == "cell" and diff.severity == Severity.UNCERTAIN and "缓存值缺失" in diff.detail
    )
    if missing_cache:
        comparison.warnings.append(
            f"{missing_cache} 个公式单元格缺少缓存值，已标记为橙色需要人工确认。"
        )
    uncertain = sum(1 for diff in comparison.diffs if diff.severity == Severity.UNCERTAIN)
    if uncertain and not missing_cache:
        comparison.warnings.append(f"{uncertain} 处差异无法完全确认，已标记为橙色需要人工复核。")
    comparison.warnings = _dedupe_warnings(comparison.warnings)
    return comparison


def _sheet_index(workbook: Workbook, name: str) -> int | None:
    for index, sheet in enumerate(workbook.sheets):
        if sheet.name == name:
            return index
    return None


# ---------------------------------------------------------------------------
# CSV 便捷入口
# ---------------------------------------------------------------------------


def compare_csv_files(
    left_path: str | Path,
    right_path: str | Path,
    options: SpreadsheetOptions | None = None,
) -> tuple[WorkbookComparison, str, list[str]]:
    """比较两个 CSV 文件，返回 ``(工作簿比较结果, 左侧分隔符, 警告)``。

    原始文本的逐行比较由 Lead 的 ``textdiff`` 引擎负责；本函数只做表格比较，
    供 MainWindow 组装 ``CsvComparison``。
    """
    left_sheet, left_delimiter, left_warnings = parse_csv(left_path)
    right_sheet, right_delimiter, right_warnings = parse_csv(right_path)
    left_workbook = csv_to_workbook(left_sheet, left_path, left_warnings)
    right_workbook = csv_to_workbook(right_sheet, right_path, right_warnings)
    comparison = compare_workbooks(left_workbook, right_workbook, options)
    warnings = list(comparison.warnings)
    if left_delimiter != right_delimiter:
        warnings.append(
            f"左右 CSV 分隔符不同（左侧 {left_delimiter!r}，右侧 {right_delimiter!r}），"
            "表格比较按各自解析后的单元格进行。"
        )
    return comparison, left_delimiter, _dedupe_warnings(warnings)


__all__ = ["compare_csv_files", "compare_workbooks"]
