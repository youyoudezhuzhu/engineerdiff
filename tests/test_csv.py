"""CSV 解析 / CSV 表格比较测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(TESTS_DIR))

from fixtures.generate_spreadsheet_fixtures import ensure_fixtures  # noqa: E402

FIXTURES = ensure_fixtures(TESTS_DIR / "fixtures")

from engineerdiff.models import CellType, SheetStatus  # noqa: E402
from engineerdiff.spreadsheet import (  # noqa: E402
    CSV_SHEET_NAME,
    compare_csv_files,
    csv_to_workbook,
    parse_csv,
)


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def test_parse_csv_quotes_commas_and_newlines() -> None:
    sheet, delimiter, warnings = parse_csv(FIXTURES / "sample_left.csv")

    assert sheet.name == CSV_SHEET_NAME == "CSV"
    assert delimiter == ","
    assert sheet.nrows == 5
    assert sheet.ncols == 4
    # 行 1：引号内逗号、引号内换行
    assert sheet.cell(1, 0).display == "主变,一号"
    assert sheet.cell(1, 0).type == CellType.TEXT
    assert sheet.cell(1, 2).display == "第一行\n第二行"
    assert sheet.cell(1, 3).display == "1.50"
    assert sheet.cell(1, 3).type == CellType.TEXT  # CSV 不做隐式数值化
    # 行 4：转义双引号
    assert sheet.cell(4, 1).display == '他说"你好"'
    # 空行 → 整行空白单元格
    assert all(cell.type == CellType.BLANK for cell in sheet.rows[3])
    assert sheet.cell(3, 0).display == ""
    # 矩形
    assert all(len(row) == sheet.ncols for row in sheet.rows)
    # 列宽按内容估算，限制在契约范围
    assert set(sheet.col_widths) == {0, 1, 2, 3}
    assert all(60 <= width <= 360 for width in sheet.col_widths.values())
    assert sheet.default_row_height == 20.0
    # 引号内换行：单元格标记自动换行，行高按行数抬高，列宽加宽
    assert sheet.cell(1, 2).style.wrap is True
    assert sheet.row_heights[1] >= 40
    assert sheet.col_widths[2] >= 180
    assert 2 not in sheet.row_heights  # 普通行不额外写行高
    assert warnings == []


def test_parse_csv_sniffs_semicolon_delimiter() -> None:
    sheet, delimiter, _warnings = parse_csv(FIXTURES / "sample_semicolon.csv")
    assert delimiter == ";"
    assert sheet.nrows == 3
    assert sheet.ncols == 3
    assert sheet.cell(1, 0).display == "主变"
    assert sheet.cell(1, 2).display == "含分号;的字段"


def test_parse_csv_gbk_encoding() -> None:
    sheet, delimiter, warnings = parse_csv(FIXTURES / "sample_gbk.csv")
    assert delimiter == ","
    assert sheet.cell(0, 0).display == "设备"
    assert sheet.cell(1, 0).display == "主变"
    assert sheet.cell(1, 2).display == "中文编码测试"
    assert any("GB18030" in warning for warning in warnings)


def test_parse_csv_ragged_rows_padded_with_warning() -> None:
    sheet, _delimiter, warnings = parse_csv(FIXTURES / "sample_ragged.csv")
    assert sheet.ncols == 4
    assert sheet.nrows == 3
    assert all(len(row) == 4 for row in sheet.rows)
    assert sheet.cell(1, 2).type == CellType.BLANK
    assert sheet.cell(1, 3).type == CellType.BLANK
    assert any("字段数" in warning for warning in warnings)


def test_parse_csv_supports_bom_and_utf16(tmp_path: Path) -> None:
    utf8_sig = tmp_path / "bom.csv"
    utf8_sig.write_bytes("\ufeff名称,版本\n主变,V1\n".encode("utf-8"))
    sheet, delimiter, _warnings = parse_csv(utf8_sig)
    assert delimiter == ","
    assert sheet.cell(0, 0).display == "名称"

    utf16 = tmp_path / "utf16.csv"
    utf16.write_bytes("名称,版本\n线路,V2\n".encode("utf-16"))
    sheet, delimiter, _warnings = parse_csv(utf16)
    assert delimiter == ","
    assert sheet.cell(1, 0).display == "线路"


def test_parse_csv_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    sheet, delimiter, warnings = parse_csv(empty)
    assert sheet.name == CSV_SHEET_NAME
    assert sheet.nrows == 0
    assert sheet.ncols == 0
    assert delimiter == ","
    assert any("为空" in warning for warning in warnings)


def test_parse_csv_missing_file_raises() -> None:
    with pytest.raises(ValueError):
        parse_csv(FIXTURES / "不存在.csv")


def test_csv_to_workbook() -> None:
    sheet, _delimiter, warnings = parse_csv(FIXTURES / "sample_left.csv")
    workbook = csv_to_workbook(sheet, FIXTURES / "sample_left.csv", warnings)
    assert workbook.fmt == "csv"
    assert workbook.title == "sample_left"
    assert workbook.sheet("CSV") is sheet
    assert workbook.warnings == warnings


# ---------------------------------------------------------------------------
# 比较
# ---------------------------------------------------------------------------


def test_compare_csv_files_reports_cell_diffs() -> None:
    comparison, delimiter, warnings = compare_csv_files(
        FIXTURES / "sample_left.csv", FIXTURES / "sample_right.csv"
    )
    assert delimiter == ","
    assert warnings == []
    assert len(comparison.sheets) == 1
    sheet_comparison = comparison.sheets[0]
    assert sheet_comparison.name == "CSV"
    assert sheet_comparison.status == SheetStatus.DIFFERENT
    ids = [diff.id for diff in comparison.diffs]
    assert ids == ["cell:CSV:1:1", "cell:CSV:1:2", "cell:CSV:4:3"]
    version_diff = comparison.diffs[0]
    assert version_diff.left is not None and version_diff.right is not None
    assert version_diff.left.text == "V1.0.0"
    assert version_diff.right.text == "V1.0.1"
    assert "文本不同" in version_diff.detail
    newline_diff = comparison.diffs[1]
    assert "\n" in newline_diff.right.text


def test_compare_csv_identical_is_equal(tmp_path: Path) -> None:
    source = FIXTURES / "sample_left.csv"
    copy = tmp_path / "copy.csv"
    copy.write_bytes(source.read_bytes())
    comparison, _delimiter, warnings = compare_csv_files(source, copy)
    assert warnings == []
    assert comparison.sheets[0].status == SheetStatus.EQUAL
    assert comparison.diffs == []


def test_csv_numbers_stay_text_and_differ(tmp_path: Path) -> None:
    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
    left.write_text("编码,值\nA,001\n", encoding="utf-8")
    right.write_text("编码,值\nA,1\n", encoding="utf-8")
    left_sheet, _d, _w = parse_csv(left)
    right_sheet, _d2, _w2 = parse_csv(right)
    assert left_sheet.cell(1, 1).type == CellType.TEXT
    comparison, _delimiter, _warnings = compare_csv_files(left, right)
    assert len(comparison.diffs) == 1
    assert comparison.diffs[0].id == "cell:CSV:1:1"
    assert comparison.diffs[0].kind.value == "modified"


def test_csv_crlf_inside_quoted_field_normalized(tmp_path) -> None:
    path = tmp_path / "crlf.csv"
    path.write_bytes(b'name,note\r\nA,"line1\r\nline2"\r\n')
    sheet, delimiter, warnings = parse_csv(path)
    assert delimiter == ","
    assert sheet.cell(1, 1).display == "line1\nline2"
    assert sheet.cell(1, 1).style.wrap is True
    assert sheet.row_heights[1] >= 40
