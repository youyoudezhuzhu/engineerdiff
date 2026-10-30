from __future__ import annotations

from pathlib import Path

import pytest

from engineerdiff.models import CompareMode, DiffKind, LineStatus, TextCompareOptions
from engineerdiff.file_loader import determine_mode
from engineerdiff.textdiff.engine import (
    compare_text_files,
    compare_texts,
    decode_text,
    split_physical_lines,
)


def changed_texts(cmp):
    return [
        (ln.text, [ln.text[s:e] for s, e in [(sp.start, sp.end) for sp in ln.spans]])
        for ln in cmp.left.lines
        if ln.spans
    ]


def test_identical_text_has_no_diff():
    cmp = compare_texts("alpha\nbeta\n", "alpha\nbeta\n")
    assert cmp.diffs == []
    assert len(cmp.left.lines) == 2
    assert all(ln.status == LineStatus.EQUAL for ln in cmp.left.lines)


def test_single_character_diff_marks_only_last_character():
    cmp = compare_texts("Software Version V1.2.3", "Software Version V1.2.4")
    assert len(cmp.diffs) == 1
    assert cmp.diffs[0].kind == DiffKind.MODIFIED
    left_spans = cmp.left.lines[0].spans
    assert [(s.start, s.end) for s in left_spans] == [(22, 23)]
    assert cmp.left.lines[0].text[22:23] == "3"
    assert cmp.right.lines[0].text[22:23] == "4"
    assert cmp.left.lines[0].status == LineStatus.MODIFIED
    assert cmp.right.lines[0].status == LineStatus.MODIFIED
    # 不应整行标红
    assert sum(sp.end - sp.start for sp in left_spans) == 1


def test_chinese_character_level_diff():
    cmp = compare_texts("保护定值：1.50A", "保护定值：1.80A")
    assert len(cmp.diffs) == 1
    left = cmp.left.lines[0]
    highlighted = "".join(left.text[s:e] for s, e in [(x.start, x.end) for x in left.spans])
    assert highlighted == "5"


def test_inserted_line_aligns_with_placeholder():
    cmp = compare_texts("a\nb\nc\n", "a\nx\nb\nc\n")
    assert len(cmp.diffs) == 1
    d = cmp.diffs[0]
    assert d.kind == DiffKind.ADDED
    assert len(cmp.left.lines) == len(cmp.right.lines) == 4
    assert cmp.left.lines[1].status == LineStatus.PLACEHOLDER
    assert cmp.right.lines[1].status == LineStatus.ADDED
    assert cmp.right.lines[1].text == "x"
    assert cmp.left.lines[2].line_no == 2
    assert cmp.right.lines[2].line_no == 3


def test_deleted_line_aligns_with_placeholder():
    cmp = compare_texts("a\nx\nb\n", "a\nb\n")
    assert len(cmp.diffs) == 1
    assert cmp.diffs[0].kind == DiffKind.REMOVED
    assert cmp.right.lines[1].status == LineStatus.PLACEHOLDER
    assert cmp.left.lines[1].text == "x"


def test_repeated_line_insert_detected():
    cmp = compare_texts("A\nB\nA\nB\n", "A\nB\nA\nX\nB\n")
    assert len(cmp.diffs) == 1
    assert cmp.diffs[0].kind == DiffKind.ADDED
    assert cmp.right.lines[3].text == "X"


def test_gbk_encoding_roundtrip(tmp_path: Path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_bytes("装置版本：V1.2.3\n".encode("gbk"))
    b.write_bytes("装置版本：V1.2.4\n".encode("gbk"))
    cmp = compare_text_files(a, b)
    assert "GB" in cmp.left.encoding
    assert cmp.left.lines[0].text.startswith("装置版本")
    assert len(cmp.diffs) == 1
    assert "3" in cmp.left.lines[0].text
    assert "4" in cmp.right.lines[0].text


def test_utf8_and_utf8_bom():
    assert decode_text(b"\xef\xbb\xbfhello").text == "hello"
    assert decode_text("中文".encode()).encoding == "UTF-8"


def test_crlf_lf_difference_and_ignore():
    a = "a\r\nb\r\n"
    b = "a\nb\n"
    strict = compare_texts(a, b)
    assert len(strict.diffs) == 1
    assert strict.diffs[0].title == "换行符差异"
    ignored = compare_texts(a, b, options=TextCompareOptions(ignore_line_endings=True))
    assert ignored.diffs == []


def test_trailing_newline_difference_and_ignore():
    assert len(compare_texts("a", "a\n").diffs) == 1
    assert compare_texts("a", "a\n", options=TextCompareOptions(ignore_line_endings=True)).diffs == []


def test_ignore_outer_space():
    opts = TextCompareOptions(ignore_outer_space=True)
    assert compare_texts("  alpha  ", "alpha", options=opts).diffs == []
    assert len(compare_texts("  alpha  ", "alpha").diffs) == 1
    # 中间空格不受“前后空格”影响
    assert len(compare_texts("a b", "ab", options=opts).diffs) == 1


def test_ignore_all_space():
    opts = TextCompareOptions(ignore_all_space=True)
    assert compare_texts("a b\tc", "abc", options=opts).diffs == []
    assert compare_texts("a b", "a  b", options=opts).diffs == []


def test_ignore_case():
    opts = TextCompareOptions(ignore_case=True)
    assert compare_texts("Version V1.2.3", "version v1.2.3", options=opts).diffs == []
    assert len(compare_texts("Version V1.2.3", "version v1.2.3").diffs) == 1


def test_blank_lines_and_whitespace_are_significant_by_default():
    cmp = compare_texts("a\n\nb\n", "a\nb\n")
    assert len(cmp.diffs) == 1
    cmp2 = compare_texts("a\n \nb\n", "a\n\nb\n")
    assert len(cmp2.diffs) == 1


def test_split_physical_lines():
    lines, trailing = split_physical_lines("a\r\nb\nc")
    assert [x.text for x in lines] == ["a", "b", "c"]
    assert [x.ending for x in lines] == ["\r\n", "\n", ""]
    assert trailing is False
    assert split_physical_lines("")[0] == []
    assert len(split_physical_lines("a\n")[0]) == 1


def test_line_alignment_does_not_pair_unrelated_lines_when_counts_differ():
    # 删除一行、新增一行内容完全不同：应分别产生删除/新增，不能硬配成改行
    cmp = compare_texts("header\nSAY HELLO\nfooter\n", "header\nTOTALLY OTHER\nfooter\n")
    kinds = {d.kind for d in cmp.diffs}
    assert kinds <= {DiffKind.MODIFIED, DiffKind.ADDED, DiffKind.REMOVED}
    assert len(cmp.left.lines) == len(cmp.right.lines)


def test_mode_detection(tmp_path: Path):
    for name in ["a.txt", "a.csv", "a.xlsx", "a.xls", "a.png", "a.JPG"]:
        (tmp_path / name).write_bytes(b"x")
    assert determine_mode(tmp_path / "a.txt", tmp_path / "a.csv") == CompareMode.TEXT
    assert determine_mode(tmp_path / "a.csv", tmp_path / "a.csv") == CompareMode.CSV
    assert determine_mode(tmp_path / "a.xlsx", tmp_path / "a.xls") == CompareMode.EXCEL
    assert determine_mode(tmp_path / "a.png", tmp_path / "a.JPG") == CompareMode.IMAGE
    with pytest.raises(ValueError):
        determine_mode(tmp_path / "a.xlsx", tmp_path / "a.txt")
    with pytest.raises(ValueError):
        determine_mode(tmp_path / "a.png", tmp_path / "a.csv")


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(Exception):
        compare_text_files(tmp_path / "nope.txt", tmp_path / "nope2.txt")
