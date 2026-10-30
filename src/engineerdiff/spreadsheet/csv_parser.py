"""CSV 解析（表格视图 + 原始文本比较的公共入口）。

契约见 docs/ui-contracts.md 2.2：使用 Python ``csv`` 模块正确解析引号、逗号与
引号内换行；用 ``csv.Sniffer`` 识别分隔符；构造单 Sheet 供表格引擎比较。

CSV 表格中每个非空字段都是 ``CellType.TEXT``（保留原始文本，包括数字样式的
文本），空字段为 ``CellType.BLANK``——是否按数值比较由 Excel 读取器决定，
CSV 不做隐式数值化，避免掩盖 "001" 与 "1" 这类真实差异。
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from ..models import Cell, CellStyle, CellType, Sheet, Workbook

CSV_SHEET_NAME = "CSV"

_MIN_COL_WIDTH = 60.0
_MAX_COL_WIDTH = 360.0
_MULTILINE_MIN_COL_WIDTH = 180.0
_MULTILINE_ROW_BASE_HEIGHT = 20.0
_MULTILINE_ROW_PADDING = 6.0
_SNIFF_SAMPLE_SIZE = 16_384
_DELIMITERS = ",;\t|"


# ---------------------------------------------------------------------------
# 编码 / 分隔符
# ---------------------------------------------------------------------------


def decode_csv_bytes(data: bytes) -> tuple[str, str, list[str]]:
    """解码 CSV 字节，返回 (文本, 编码, 警告)。

    依次尝试 UTF-8（含 BOM）、UTF-16 BOM、GB18030，最后交给
    ``charset-normalizer`` 或 latin-1 兜底，保证不会因编码问题直接失败。
    """
    warnings: list[str] = []
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig", warnings
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), "utf-16", warnings
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8", "gb18030"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if encoding == "gb18030":
            warnings.append("CSV 不是 UTF-8 编码，已按 GB18030 解码，请确认中文显示正常。")
        return text, encoding, warnings
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            text = str(best)
            encoding = best.encoding or "unknown"
            warnings.append(f"CSV 编码无法确定为 UTF-8/GB18030，已按 {encoding} 解码，请确认内容。")
            return text, encoding, warnings
    except Exception:  # pragma: no cover - charset-normalizer 不可用时兜底
        pass
    warnings.append("CSV 编码无法识别，已按 Latin-1 解码，非 ASCII 字符可能显示异常。")
    return data.decode("latin-1"), "latin-1", warnings


def sniff_delimiter(text: str) -> tuple[str, list[str]]:
    """识别 CSV 分隔符；失败时按候选符号出现次数回退到逗号。"""
    warnings: list[str] = []
    sample = text[:_SNIFF_SAMPLE_SIZE]
    if not sample.strip():
        return ",", warnings
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=_DELIMITERS)
        delimiter = dialect.delimiter
        if delimiter:
            return delimiter, warnings
    except csv.Error:
        pass
    # 回退：取首行中候选分隔符出现次数最多者。
    first_line = sample.splitlines()[0] if sample.splitlines() else ""
    counts = {candidate: first_line.count(candidate) for candidate in _DELIMITERS}
    best = max(counts, key=lambda key: counts[key])
    if counts[best] == 0:
        warnings.append("未能识别 CSV 分隔符，已按逗号解析。")
        return ",", warnings
    warnings.append(f"未能可靠识别 CSV 分隔符，已按出现次数推断为“{best}”。")
    return best, warnings


def _display_width(text: str) -> int:
    """估算文本显示宽度（CJK 记 2 个半角）。"""
    width = 0
    for char in text:
        width += 2 if ord(char) > 0x2E80 else 1
    return width


def _estimate_col_widths(
    rows: list[list[str]],
    multiline_cols: set[int] | None = None,
) -> dict[int, float]:
    widths: dict[int, float] = {}
    multiline_cols = multiline_cols or set()
    ncols = max((len(row) for row in rows), default=0)
    for col in range(ncols):
        longest = 0
        for row in rows:
            if col < len(row):
                # 多行字段按最长的一行估算，否则换行符会把列压得很窄。
                for line in row[col].splitlines() or [""]:
                    longest = max(longest, _display_width(line))
        estimated = longest * 7.0 + 24.0
        if col in multiline_cols:
            # 含换行的字段额外留出宽度，避免每行都折成很多段。
            estimated = max(estimated, _MULTILINE_MIN_COL_WIDTH)
        widths[col] = float(min(_MAX_COL_WIDTH, max(_MIN_COL_WIDTH, round(estimated))))
    return widths


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------


def parse_csv(path: str | Path) -> tuple[Sheet, str, list[str]]:
    """解析 CSV，返回 ``(Sheet, 分隔符, 警告)``。

    ``Sheet.name`` 固定为 ``"CSV"``；每行补空到相同列数（矩形）。
    """
    p = Path(path)
    warnings: list[str] = []
    if not p.exists():
        raise ValueError(f"文件不存在：{p}")
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取 CSV 文件“{p.name}”：{exc}") from exc
    if not data:
        sheet = Sheet(name=CSV_SHEET_NAME)
        warnings.append("CSV 文件为空。")
        return sheet, ",", warnings

    text, _encoding, encoding_warnings = decode_csv_bytes(data)
    warnings.extend(encoding_warnings)
    delimiter, delimiter_warnings = sniff_delimiter(text)
    warnings.extend(delimiter_warnings)

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    raw_rows: list[list[str]] = []
    try:
        for row in reader:
            raw_rows.append(list(row))
    except csv.Error as exc:
        raise ValueError(f"CSV 文件“{p.name}”格式错误：{exc}") from exc

    # 去掉文末完全空白的行（csv.reader 不产生末尾空行，这里防御性处理）。
    while raw_rows and all(field == "" for field in raw_rows[-1]):
        raw_rows.pop()

    ncols = max((len(row) for row in raw_rows), default=0)
    nrows = len(raw_rows)
    sheet = Sheet(name=CSV_SHEET_NAME, nrows=nrows, ncols=ncols)
    if nrows == 0 or ncols == 0:
        warnings.append("CSV 文件没有可显示的数据行。")
        sheet.rows = []
        return sheet, delimiter, warnings

    ragged_rows = 0
    rows: list[list[Cell]] = []
    multiline_cols: set[int] = set()
    row_heights: dict[int, float] = {}
    for row_index, raw_row in enumerate(raw_rows):
        if len(raw_row) != ncols and any(field != "" for field in raw_row):
            ragged_rows += 1
        line_count = 1
        cells: list[Cell] = []
        for col in range(ncols):
            field = raw_row[col] if col < len(raw_row) else ""
            # 统一字段内换行为 LF：Windows 上 csv.reader 会保留 CRLF，同一份 CSV
            # 在不同平台应产生一致的显示/比较结果；原始文本视图仍由 TextDiff 处理。
            if "\r" in field:
                field = field.replace("\r\n", "\n").replace("\r", "\n")
            if field == "":
                cells.append(Cell())
                continue
            style = CellStyle()
            if "\n" in field or "\r" in field:
                # 契约要求正确处理引号内换行：标记自动换行并按行数抬高行高，
                # 否则 GridView 只按 20px 行高绘制会裁掉第二行。
                style.wrap = True
                multiline_cols.add(col)
                line_count = max(line_count, len(re.findall(r"\r\n|\r|\n", field)) + 1)
            cells.append(Cell(display=field, type=CellType.TEXT, value=field, style=style))
        rows.append(cells)
        if line_count > 1:
            row_heights[row_index] = max(
                _MULTILINE_ROW_BASE_HEIGHT,
                _MULTILINE_ROW_BASE_HEIGHT * line_count + _MULTILINE_ROW_PADDING,
            )
    sheet.rows = rows
    sheet.row_heights = row_heights
    sheet.col_widths = _estimate_col_widths(raw_rows, multiline_cols)
    sheet.default_col_width = float(_MIN_COL_WIDTH)
    sheet.default_row_height = 20.0
    if ragged_rows:
        warnings.append(f"{ragged_rows} 行字段数与最大列数不一致，缺失字段已按空白单元格处理。")
    return sheet, delimiter, warnings


def csv_to_workbook(sheet: Sheet, path: str | Path, warnings: list[str] | None = None) -> Workbook:
    """把 CSV Sheet 包装成 Workbook，便于复用 ``compare_workbooks``。"""
    p = Path(path)
    return Workbook(
        path=str(p.resolve()),
        sheets=[sheet],
        fmt="csv",
        warnings=list(warnings or []),
        title=p.stem,
    )


__all__ = [
    "CSV_SHEET_NAME",
    "csv_to_workbook",
    "decode_csv_bytes",
    "parse_csv",
    "sniff_delimiter",
]
