"""Excel 工作簿读取（.xlsx / .xls）。

本模块只依赖 openpyxl / xlrd 与 ``engineerdiff.models``，不依赖 Qt。

实现约定（见 docs/ui-contracts.md 2.1）：

* XLSX：用 openpyxl 加载两次（``data_only=False`` 取公式、``data_only=True``
  取缓存值），同时读取合并单元格、列宽行高、隐藏行列与基本单元格样式。
* XLS：用 xlrd 的 ``formatting_info=True`` 读取值、日期、合并单元格、列宽
  行高与基本样式。xls 格式不保存（xlrd 也不暴露）公式表达式，因此始终给出
  中文 warning，公式相关单元格只能按缓存值处理。
* ``Sheet.rows`` 为矩形 ``nrows x ncols``，空白位置放 ``Cell()``。
* 列宽 / 行高统一换算为 96dpi 像素；列宽按 Excel 字符宽度换算
  （``px = round(chars * 7 + 5)``），行高按磅换算（``px = round(pt * 4 / 3)``）。
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any, Iterator

from ..models import Cell, CellStyle, CellType, Sheet, Workbook

MAX_ROWS = 50_000
MAX_COLS = 2_000
MAX_CELLS = 500_000

_SUPPORTED_EXTS = {".xlsx", ".xlsm", ".xls"}

ERROR_TEXT_FALLBACK = "#ERROR!"


class SpreadsheetLoadError(ValueError):
    """Excel 文件读取失败。消息为可直接展示给用户的中文。"""


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def column_letter(index: int) -> str:
    """0-based 列索引转 Excel 列标（0 -> A, 26 -> AA）。"""
    if index < 0:
        raise ValueError("列索引不能为负数")
    letters: list[str] = []
    n = index + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def classify_value(raw: Any) -> CellType:
    """按 Python 原生值判定单元格类型。"""
    if raw is None:
        return CellType.BLANK
    if isinstance(raw, bool):
        return CellType.BOOL
    if isinstance(raw, (_dt.datetime, _dt.date, _dt.time)):
        return CellType.DATE
    if isinstance(raw, (int, float)):
        return CellType.NUMBER
    return CellType.TEXT


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _general_number(value: Any) -> str:
    """Excel "常规" 数值格式的近似显示。"""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)
    if number == 0:
        return "0"
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    text = format(number, ".15g")
    if "e" in text or "E" in text:
        mantissa, exponent = re.split("[eE]", text)
        sign = "+" if not exponent.startswith("-") else "-"
        exponent = exponent.lstrip("+-").lstrip("0") or "0"
        text = f"{mantissa}E{sign}{exponent}"
    return text


def _number_format_decimals(section: str) -> int | None:
    match = re.search(r"\.([0#]+)", section)
    if match:
        return len(match.group(1))
    if "0" in section or "#" in section:
        return 0
    return None


def format_number(value: Any, number_format: str | None) -> str:
    """按 Excel 数字格式做基础还原（常规 / 固定小数 / 千分位 / 百分比）。"""
    fmt = (number_format or "").strip()
    if not fmt or fmt.lower() == "general":
        return _general_number(value)

    # 去掉颜色/条件等方括号段，取正数区段（Excel 以 ; 分隔多个区段）。
    section = re.sub(r"\[[^\]]*\]", "", fmt.split(";")[0]).strip()
    if not section:
        return _general_number(value)
    negative = False
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)
    if number < 0:
        negative = True
        number = abs(number)

    percent = "%" in section
    if percent:
        number *= 100.0
    decimals = _number_format_decimals(section)
    thousands = "," in section.split(".")[0]
    if "e" in section.lower() and ("0" in section or "#" in section):
        # 科学计数法：交给 Python，保持足够精度。
        text = f"{number:.6E}"
    elif decimals is None:
        text = _general_number(number)
    elif thousands:
        text = f"{number:,.{decimals}f}"
    else:
        text = f"{number:.{decimals}f}"
    if percent:
        text = f"{text}%"
    if negative:
        text = "-" + text
    return text


_TIME_FORMAT_HINT = re.compile(r"[hs]", re.IGNORECASE)
_DATE_FORMAT_HINT = re.compile(r"[yd]", re.IGNORECASE)


def format_date(value: Any, number_format: str | None) -> str:
    """日期显示：尽量按单元格数字格式，否则使用 ISO 风格。"""
    if isinstance(value, _dt.datetime):
        moment = value
    elif isinstance(value, _dt.date):
        moment = _dt.datetime(value.year, value.month, value.day)
    elif isinstance(value, _dt.time):
        return value.strftime("%H:%M:%S")
    else:
        return str(value)

    fmt = number_format or ""
    if fmt:
        fmt_lower = fmt.lower()
        time_only = bool(_TIME_FORMAT_HINT.search(fmt_lower)) and not bool(_DATE_FORMAT_HINT.search(fmt_lower))
        if time_only:
            return moment.strftime("%H:%M:%S")
        if _DATE_FORMAT_HINT.search(fmt_lower):
            if _TIME_FORMAT_HINT.search(fmt_lower):
                return moment.strftime("%Y-%m-%d %H:%M:%S")
            return moment.strftime("%Y-%m-%d")
    if isinstance(value, _dt.datetime) and value.time() != _dt.time(0, 0):
        return moment.strftime("%Y-%m-%d %H:%M:%S")
    return moment.strftime("%Y-%m-%d")


def cell_display(raw: Any, cell_type: CellType, number_format: str | None = None) -> str:
    """把规范化值渲染为表格中展示的文本。"""
    if cell_type == CellType.BLANK or raw is None:
        return ""
    if cell_type == CellType.BOOL:
        return "TRUE" if bool(raw) else "FALSE"
    if cell_type == CellType.DATE:
        return format_date(raw, number_format)
    if cell_type == CellType.NUMBER:
        return format_number(raw, number_format)
    if cell_type == CellType.ERROR:
        return str(raw) or ERROR_TEXT_FALLBACK
    return str(raw)


def _align_for_general(cell_type: CellType) -> str:
    if cell_type in (CellType.NUMBER, CellType.DATE):
        return "right"
    if cell_type in (CellType.BOOL, CellType.ERROR):
        return "center"
    return "left"


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------


def _normalize_hex_color(rgb: Any) -> str | None:
    if rgb is None:
        return None
    text = str(rgb).strip().lstrip("#").upper()
    if len(text) == 8:
        text = text[2:]
    if len(text) != 6 or not re.fullmatch(r"[0-9A-F]{6}", text):
        return None
    if text == "000000":
        return "#000000"
    return "#" + text


def _xlsx_color(color: Any) -> str | None:
    """把 openpyxl Color 转为 #RRGGBB；主题色无法离线还原时返回 None。"""
    if color is None:
        return None
    try:
        color_type = getattr(color, "type", None)
        rgb = None
        if color_type == "rgb":
            rgb = getattr(color, "rgb", None)
        elif color_type == "indexed":
            from openpyxl.styles.colors import COLOR_INDEX

            indexed = getattr(color, "indexed", None)
            if indexed is not None and 0 <= int(indexed) < len(COLOR_INDEX):
                rgb = COLOR_INDEX[int(indexed)]
        elif color_type == "theme":
            # 主题色需要解析 theme1.xml 与 tint，超出“基本样式还原”范围。
            return None
        else:
            rgb = getattr(color, "rgb", None)
        return _normalize_hex_color(rgb)
    except (AttributeError, TypeError, ValueError):
        return None


def _xlsx_style(cell: Any) -> tuple[CellStyle, bool]:
    """返回 (样式, 是否为“常规/未显式指定”水平对齐)。"""
    style = CellStyle()
    general_align = True
    try:
        font = cell.font
        if font is not None:
            style.bold = bool(font.bold)
            style.italic = bool(font.italic)
            if font.sz:
                style.font_size = float(font.sz)
            color = _xlsx_color(getattr(font, "color", None))
            if color:
                style.font_color = color
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        fill = cell.fill
        if fill is not None and getattr(fill, "fill_type", None) not in (None, "none"):
            color = _xlsx_color(getattr(fill, "fgColor", None))
            if color:
                style.fill_color = color
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        alignment = cell.alignment
        if alignment is not None:
            horizontal = getattr(alignment, "horizontal", None)
            if horizontal in ("left", "center", "right"):
                style.h_align = horizontal
                general_align = False
            elif horizontal in ("centerContinuous", "justify", "distributed", "fill"):
                style.h_align = "center" if horizontal == "centerContinuous" else "left"
                general_align = False
            vertical = getattr(alignment, "vertical", None)
            if vertical in ("top", "center", "bottom"):
                style.v_align = vertical
            elif vertical in ("justify", "distributed"):
                style.v_align = "center"
            style.wrap = bool(getattr(alignment, "wrapText", False))
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        style.number_format = cell.number_format
    except (AttributeError, TypeError):
        style.number_format = None
    return style, general_align


def _iter_worksheet_cells(ws: Any) -> Iterator[Any]:
    """尽量只遍历真实存在的单元格，避免为空白区域创建对象。"""
    cells = getattr(ws, "_cells", None)
    if isinstance(cells, dict):
        yield from cells.values()
    else:  # pragma: no cover - openpyxl 结构变化时的兜底
        for row in ws.iter_rows():
            yield from row


def _cell_type_for_xlsx(cell: Any, raw: Any, has_formula: bool) -> CellType:
    if has_formula:
        return CellType.FORMULA
    try:
        data_type = getattr(cell, "data_type", None)
    except AttributeError:  # pragma: no cover
        data_type = None
    if data_type == "e":
        return CellType.ERROR
    if data_type == "b" or isinstance(raw, bool):
        return CellType.BOOL
    return classify_value(raw)


def _make_xlsx_cell(fcell: Any, cached: Any) -> Cell:
    raw_value = fcell.value
    has_formula = getattr(fcell, "data_type", None) == "f" and isinstance(raw_value, str)
    style, general_align = _xlsx_style(fcell)
    number_format = style.number_format
    if has_formula:
        formula = raw_value
        cell = Cell(
            type=CellType.FORMULA,
            value=cached,
            formula=formula,
            cached=cached,
            style=style,
            display=formula,
        )
        if cached is not None:
            cached_type = classify_value(cached)
            if general_align:
                style.h_align = _align_for_general(cached_type)
            cell.display = cell_display(cached, cached_type, number_format)
        return cell

    cell_type = _cell_type_for_xlsx(fcell, raw_value, False)
    if general_align:
        style.h_align = _align_for_general(cell_type)
    display = cell_display(raw_value, cell_type, number_format)
    return Cell(display=display, type=cell_type, value=raw_value, style=style)


def _excel_col_px(width_chars: float) -> int:
    return max(8, int(round(float(width_chars) * 7.0 + 5.0)))


def _excel_row_px(height_points: float) -> int:
    return max(6, int(round(float(height_points) * 4.0 / 3.0)))


def _clamp_bounds(rows: int, cols: int, warnings: list[str], sheet_name: str) -> tuple[int, int]:
    if rows <= 0 or cols <= 0:
        return 0, 0
    if rows > MAX_ROWS:
        warnings.append(f"工作表“{sheet_name}”行数 {rows} 超过 {MAX_ROWS}，已截断读取。")
        rows = MAX_ROWS
    if cols > MAX_COLS:
        warnings.append(f"工作表“{sheet_name}”列数 {cols} 超过 {MAX_COLS}，已截断读取。")
        cols = MAX_COLS
    if rows * cols > MAX_CELLS:
        allowed_rows = max(1, MAX_CELLS // cols)
        warnings.append(
            f"工作表“{sheet_name}”数据量 {rows}x{cols} 过大，"
            f"已限制为前 {allowed_rows} 行（请拆分后比较）。"
        )
        rows = allowed_rows
    return rows, cols


def _load_xlsx(path: Path) -> Workbook:
    import openpyxl

    try:
        wb_formula = openpyxl.load_workbook(str(path), data_only=False, read_only=False)
    except Exception as exc:  # openpyxl 抛出的异常类型较多，统一转中文错误
        raise SpreadsheetLoadError(f"无法读取 Excel 文件“{path.name}”：{exc}") from exc
    try:
        wb_values = openpyxl.load_workbook(str(path), data_only=True, read_only=False)
    except Exception:  # 缓存值读取失败不应导致整个文件不可读，但必须提示
        wb_values = None

    workbook = Workbook(path=str(path.resolve()), fmt="xlsx", title=path.stem)
    warnings = workbook.warnings
    if wb_values is None:
        warnings.append("无法读取 XLSX 缓存值（公式结果可能不可见），已仅按公式表达式读取。")

    missing_cache = 0
    for ws in wb_formula.worksheets:
        wsv = wb_values[ws.title] if wb_values is not None and ws.title in wb_values.sheetnames else None
        sheet = Sheet(name=ws.title)
        rows = int(ws.max_row or 0)
        cols = int(ws.max_column or 0)
        merged_ranges: list[tuple[int, int, int, int]] = []
        for rng in ws.merged_cells.ranges:
            rlo, rhi = int(rng.min_row) - 1, int(rng.max_row) - 1
            clo, chi = int(rng.min_col) - 1, int(rng.max_col) - 1
            rows = max(rows, rhi + 1)
            cols = max(cols, chi + 1)
            merged_ranges.append((rlo, clo, rhi - rlo + 1, chi - clo + 1))
        rows, cols = _clamp_bounds(rows, cols, warnings, ws.title)
        sheet.nrows, sheet.ncols = rows, cols
        if rows == 0 or cols == 0:
            workbook.sheets.append(sheet)
            continue

        data: list[list[Cell]] = [[Cell() for _ in range(cols)] for _ in range(rows)]
        for fcell in _iter_worksheet_cells(ws):
            row, col = int(fcell.row) - 1, int(fcell.column) - 1
            if not (0 <= row < rows and 0 <= col < cols):
                continue
            vcell = None
            if wsv is not None:
                cells_map = getattr(wsv, "_cells", {})
                vcell = cells_map.get((fcell.row, fcell.column)) if isinstance(cells_map, dict) else None
            cached = vcell.value if vcell is not None else None
            data[row][col] = _make_xlsx_cell(fcell, cached)
            if getattr(fcell, "data_type", None) == "f" and cached is None:
                missing_cache += 1

        # 合并单元格：锚点写 span，其余单元格写 merged_anchor。
        for rlo, clo, rspan, cspan in merged_ranges:
            if rlo >= rows or clo >= cols:
                continue
            rspan = min(rspan, rows - rlo)
            cspan = min(cspan, cols - clo)
            if rspan <= 0 or cspan <= 0:
                continue
            sheet.merged.append((rlo, clo, rspan, cspan))
            data[rlo][clo].span = (rspan, cspan)
            for rr in range(rlo, rlo + rspan):
                for cc in range(clo, clo + cspan):
                    if (rr, cc) != (rlo, clo):
                        data[rr][cc].merged_anchor = (rlo, clo)
                        data[rr][cc].display = ""
                        data[rr][cc].value = None
                        data[rr][cc].type = CellType.BLANK
                        data[rr][cc].style = data[rlo][clo].style
        sheet.rows = data

        # 列宽 / 隐藏列
        for key, dim in ws.column_dimensions.items():
            indices: list[int] = []
            if getattr(dim, "min", None) and getattr(dim, "max", None):
                indices = list(range(int(dim.min) - 1, int(dim.max)))
            else:
                index = getattr(dim, "index", None) or key
                if isinstance(index, str):
                    try:
                        from openpyxl.utils import column_index_from_string

                        indices = [column_index_from_string(index) - 1]
                    except (ValueError, TypeError):
                        indices = []
                elif isinstance(index, int):
                    indices = [index - 1]
            for col in indices:
                if not (0 <= col < cols):
                    continue
                if getattr(dim, "width", None):
                    sheet.col_widths[col] = float(_excel_col_px(dim.width))
                if getattr(dim, "hidden", False):
                    sheet.hidden_cols.add(col)
        default_width = getattr(ws.sheet_format, "defaultColWidth", None)
        if default_width:
            sheet.default_col_width = float(_excel_col_px(default_width))

        # 行高 / 隐藏行
        for index, dim in ws.row_dimensions.items():
            row = int(index) - 1
            if not (0 <= row < rows):
                continue
            if getattr(dim, "height", None):
                sheet.row_heights[row] = float(_excel_row_px(dim.height))
            if getattr(dim, "hidden", False):
                sheet.hidden_rows.add(row)
        default_height = getattr(ws.sheet_format, "defaultRowHeight", None)
        if default_height:
            sheet.default_row_height = float(_excel_row_px(default_height))

        tab_color = getattr(ws.sheet_properties, "tabColor", None)
        if tab_color is not None:
            hex_color = _xlsx_color(tab_color)
            if hex_color:
                sheet.tab_color = hex_color

        workbook.sheets.append(sheet)

    if missing_cache:
        warnings.append(
            f"{missing_cache} 个公式单元格缺少缓存值（文件可能未在 Excel 中保存过计算结果），"
            "按值比较时这些单元格会标记为需要人工确认。"
        )
    return workbook


# ---------------------------------------------------------------------------
# XLS
# ---------------------------------------------------------------------------


def _xls_color(book: Any, colour_index: Any) -> str | None:
    try:
        rgb = book.colour_map.get(int(colour_index)) if colour_index is not None else None
    except (TypeError, ValueError):
        return None
    if not rgb:
        return None
    return _normalize_hex_color("%02X%02X%02X" % (rgb[0], rgb[1], rgb[2]))


_XLS_H_ALIGN = {0: None, 1: "left", 2: "center", 3: "right"}
_XLS_V_ALIGN = {0: "top", 1: "center", 2: "bottom"}


def _xls_style(book: Any, cell: Any) -> tuple[CellStyle, bool]:
    style = CellStyle()
    general_align = True
    try:
        xf = book.xf_list[cell.xf_index]
    except (IndexError, TypeError, AttributeError):
        return style, general_align

    try:
        font = book.font_list[xf.font_index]
        style.bold = bool(font.bold)
        style.italic = bool(font.italic)
        if font.height:
            style.font_size = float(font.height) / 20.0
        color = _xls_color(book, font.colour_index)
        if color:
            style.font_color = color
    except (IndexError, TypeError, AttributeError):
        pass

    try:
        background = xf.background
        pattern = int(getattr(background, "fill_pattern", 0) or 0)
        if pattern:
            fill_index = getattr(background, "pattern_colour_index", None)
            if fill_index in (None, 64, 65):
                fill_index = getattr(background, "background_colour_index", None)
            color = _xls_color(book, fill_index)
            if color:
                style.fill_color = color
    except (IndexError, TypeError, AttributeError):
        pass

    try:
        alignment = xf.alignment
        horizontal = _XLS_H_ALIGN.get(int(alignment.hor_align))
        if horizontal:
            style.h_align = horizontal
            general_align = False
        vertical = _XLS_V_ALIGN.get(int(alignment.vert_align))
        if vertical:
            style.v_align = vertical
        style.wrap = bool(alignment.text_wrapped)
    except (IndexError, TypeError, AttributeError):
        pass

    try:
        number_format = book.format_map.get(xf.format_key)
        if number_format is not None and number_format.format_str:
            style.number_format = number_format.format_str
    except (IndexError, TypeError, AttributeError):
        pass
    return style, general_align


def _xls_error_text(code: Any) -> str:
    try:
        import xlrd

        text = xlrd.error_text_from_code.get(int(code))
        if text:
            return text
    except (ImportError, TypeError, ValueError):
        pass
    return ERROR_TEXT_FALLBACK


def _load_xls(path: Path) -> Workbook:
    import xlrd

    try:
        book = xlrd.open_workbook(str(path), formatting_info=True, on_demand=False)
    except Exception as exc:
        raise SpreadsheetLoadError(f"无法读取 Excel 文件“{path.name}”：{exc}") from exc

    workbook = Workbook(path=str(path.resolve()), fmt="xls", title=path.stem)
    workbook.warnings.append(
        "XLS 格式不支持读取公式表达式，xlrd 只能读取缓存值；"
        "公式单元格按缓存值比较（formula_mode=formula 时同样只能比较缓存值）。"
    )

    for sh in book.sheets():
        sheet = Sheet(name=sh.name)
        rows, cols = int(sh.nrows or 0), int(sh.ncols or 0)
        merged_ranges: list[tuple[int, int, int, int]] = []
        for rlo, rhi, clo, chi in sh.merged_cells:
            rows = max(rows, int(rhi))
            cols = max(cols, int(chi))
            merged_ranges.append((int(rlo), int(clo), int(rhi) - int(rlo), int(chi) - int(clo)))
        rows, cols = _clamp_bounds(rows, cols, workbook.warnings, sh.name)
        sheet.nrows, sheet.ncols = rows, cols
        if rows == 0 or cols == 0:
            workbook.sheets.append(sheet)
            continue

        data: list[list[Cell]] = [[Cell() for _ in range(cols)] for _ in range(rows)]
        for row in range(min(int(sh.nrows), rows)):
            for col in range(min(int(sh.ncols), cols)):
                try:
                    raw_cell = sh.cell(row, col)
                except (IndexError, ValueError):
                    continue
                ctype = raw_cell.ctype
                style, general_align = _xls_style(book, raw_cell)
                number_format = style.number_format
                if ctype == xlrd.XL_CELL_EMPTY or ctype == xlrd.XL_CELL_BLANK:
                    cell = Cell(style=style)
                elif ctype == xlrd.XL_CELL_TEXT:
                    value = raw_cell.value
                    cell_type = CellType.TEXT
                    if general_align:
                        style.h_align = _align_for_general(cell_type)
                    cell = Cell(
                        display=cell_display(value, cell_type, number_format),
                        type=cell_type,
                        value=value,
                        style=style,
                    )
                elif ctype == xlrd.XL_CELL_NUMBER:
                    value = raw_cell.value
                    cell_type = CellType.NUMBER
                    if general_align:
                        style.h_align = _align_for_general(cell_type)
                    cell = Cell(
                        display=cell_display(value, cell_type, number_format),
                        type=cell_type,
                        value=value,
                        style=style,
                    )
                elif ctype == xlrd.XL_CELL_DATE:
                    try:
                        value = xlrd.xldate_as_datetime(float(raw_cell.value), book.datemode)
                    except (ValueError, OverflowError, TypeError) as exc:
                        workbook.warnings.append(
                            f"工作表“{sh.name}”单元格 {column_letter(col)}{row + 1} 的日期无法解析：{exc}"
                        )
                        value = raw_cell.value
                        cell_type = CellType.NUMBER
                    else:
                        cell_type = CellType.DATE
                    if general_align:
                        style.h_align = _align_for_general(cell_type)
                    cell = Cell(
                        display=cell_display(value, cell_type, number_format),
                        type=cell_type,
                        value=value,
                        style=style,
                    )
                elif ctype == xlrd.XL_CELL_BOOLEAN:
                    value = bool(raw_cell.value)
                    cell_type = CellType.BOOL
                    if general_align:
                        style.h_align = _align_for_general(cell_type)
                    cell = Cell(
                        display=cell_display(value, cell_type, number_format),
                        type=cell_type,
                        value=value,
                        style=style,
                    )
                elif ctype == xlrd.XL_CELL_ERROR:
                    text = _xls_error_text(raw_cell.value)
                    cell_type = CellType.ERROR
                    if general_align:
                        style.h_align = _align_for_general(cell_type)
                    cell = Cell(display=text, type=cell_type, value=text, style=style)
                else:  # pragma: no cover - 未知类型按文本处理
                    value = raw_cell.value
                    cell_type = classify_value(value)
                    cell = Cell(
                        display=cell_display(value, cell_type, number_format),
                        type=cell_type,
                        value=value,
                        style=style,
                    )
                data[row][col] = cell

        for rlo, clo, rspan, cspan in merged_ranges:
            if rlo >= rows or clo >= cols:
                continue
            rspan = min(rspan, rows - rlo)
            cspan = min(cspan, cols - clo)
            if rspan <= 0 or cspan <= 0:
                continue
            sheet.merged.append((rlo, clo, rspan, cspan))
            data[rlo][clo].span = (rspan, cspan)
            for rr in range(rlo, rlo + rspan):
                for cc in range(clo, clo + cspan):
                    if (rr, cc) != (rlo, clo):
                        data[rr][cc].merged_anchor = (rlo, clo)
                        data[rr][cc].display = ""
                        data[rr][cc].value = None
                        data[rr][cc].type = CellType.BLANK
                        data[rr][cc].style = data[rlo][clo].style
        sheet.rows = data

        for col, info in getattr(sh, "colinfo_map", {}).items():
            if not (0 <= int(col) < cols):
                continue
            if getattr(info, "hidden", False):
                sheet.hidden_cols.add(int(col))
            width = getattr(info, "width", 0)
            if width:
                sheet.col_widths[int(col)] = float(_excel_col_px(float(width) / 256.0))
        for row, info in getattr(sh, "rowinfo_map", {}).items():
            if not (0 <= int(row) < rows):
                continue
            if getattr(info, "hidden", False):
                sheet.hidden_rows.add(int(row))
            height = getattr(info, "height", 0)
            if height:
                sheet.row_heights[int(row)] = float(_excel_row_px(float(height) / 20.0))
        default_height = getattr(sh, "default_row_height", None)
        if default_height:
            sheet.default_row_height = float(_excel_row_px(float(default_height) / 20.0))
        workbook.sheets.append(sheet)

    return workbook


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------


def load_workbook(path: str | Path) -> Workbook:
    """读取 .xlsx / .xls 工作簿。

    失败抛出 :class:`SpreadsheetLoadError`（``ValueError`` 子类），消息可直接展示。
    """
    p = Path(path)
    if not p.exists():
        raise SpreadsheetLoadError(f"文件不存在：{p}")
    if not p.is_file():
        raise SpreadsheetLoadError(f"不是文件：{p}")
    ext = p.suffix.lower()
    if ext not in _SUPPORTED_EXTS:
        raise SpreadsheetLoadError(
            f"无法读取“{p.name}”：EngineerDiff 仅支持 .xlsx / .xls（也兼容 .xlsm）。"
        )
    try:
        if ext == ".xls":
            return _load_xls(p)
        return _load_xlsx(p)
    except SpreadsheetLoadError:
        raise
    except PermissionError as exc:
        raise SpreadsheetLoadError(f"没有权限读取文件“{p.name}”：{exc}") from exc
    except MemoryError as exc:
        raise SpreadsheetLoadError(f"文件“{p.name}”过大，内存不足，无法读取。") from exc
    except Exception as exc:
        raise SpreadsheetLoadError(f"无法读取 Excel 文件“{p.name}”：{exc}") from exc
