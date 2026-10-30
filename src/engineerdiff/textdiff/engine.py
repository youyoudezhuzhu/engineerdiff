"""文本差异引擎。

只依赖标准库与 models，不依赖 Qt。支持编码识别、行级对齐、字符级区间，
以及可选的空白/大小写/换行符忽略规则。默认严格比较。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from ..models import (
    DiffItem,
    DiffKind,
    DiffLocation,
    DisplayLine,
    LineStatus,
    Severity,
    TextCompareOptions,
    TextComparison,
    TextSide,
    TextSpan,
)


class TextCompareError(ValueError):
    """文本读取/比较失败。"""


@dataclass
class DecodedText:
    text: str
    encoding: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class _PhysicalLine:
    text: str
    ending: str


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u303f]")


def decode_text(data: bytes, path: str = "") -> DecodedText:
    """识别常见文本编码。优先 BOM，其次 UTF-8、GB18030，再交给 charset-normalizer。"""
    warnings: list[str] = []
    if not data:
        return DecodedText("", "utf-8", warnings)

    if data.startswith(b"\xef\xbb\xbf"):
        return DecodedText(data.decode("utf-8-sig"), "UTF-8 BOM", warnings)
    if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        try:
            return DecodedText(data.decode("utf-32"), "UTF-32", warnings)
        except UnicodeDecodeError:
            pass
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return DecodedText(data.decode("utf-16"), "UTF-16", warnings)
        except UnicodeDecodeError:
            pass

    try:
        return DecodedText(data.decode("utf-8"), "UTF-8", warnings)
    except UnicodeDecodeError:
        pass

    # 中文工程文件常见 GBK/GB18030。先严格试 GB18030，并要求结果中出现 CJK，
    # 避免把其他单字节编码误判为中文。
    try:
        gb = data.decode("gb18030")
        cjk = len(_CJK_RE.findall(gb))
        printable = sum(1 for ch in gb if ch.isprintable() or ch in "\r\n\t")
        if cjk > 0 and printable / max(1, len(gb)) > 0.85:
            warnings.append("未检测到 BOM，按 GB18030/GBK 解码。")
            return DecodedText(gb, "GB18030/GBK", warnings)
    except UnicodeDecodeError:
        pass

    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None and best.encoding:
            text = str(best)
            enc = best.encoding.upper()
            warnings.append(f"编码经自动识别为 {best.encoding}，如显示乱码请转换文件编码。")
            return DecodedText(text, enc, warnings)
    except Exception:
        pass

    try:
        text = data.decode("gb18030")
        warnings.append("编码无法可靠识别，已按 GB18030 解码，可能存在乱码。")
        return DecodedText(text, "GB18030（回退）", warnings)
    except UnicodeDecodeError:
        text = data.decode("latin-1")
        warnings.append("编码无法识别，已按 Latin-1 回退显示，请人工核对。")
        return DecodedText(text, "Latin-1（回退）", warnings)


def read_text(path: str | Path) -> DecodedText:
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise TextCompareError(f"无法读取文件：{p}\n{exc}") from exc
    decoded = decode_text(data, str(p))
    return decoded


def split_physical_lines(text: str) -> tuple[list[_PhysicalLine], bool]:
    """保留每行内容与换行符。返回 (行列表, 是否以换行结尾)。"""
    if text == "":
        return [], False
    parts = re.split(r"(\r\n|\n|\r)", text)
    lines: list[_PhysicalLine] = []
    i = 0
    while i + 1 < len(parts):
        lines.append(_PhysicalLine(parts[i], parts[i + 1]))
        i += 2
    if i < len(parts) and parts[i] != "":
        lines.append(_PhysicalLine(parts[i], ""))
    trailing = text.endswith(("\n", "\r"))
    return lines, trailing


def line_ending_signature(lines: Iterable[_PhysicalLine]) -> str:
    endings = {ln.ending for ln in lines if ln.ending}
    return "".join(sorted(endings))


def _normalize_line(text: str, opts: TextCompareOptions) -> tuple[str, list[int]]:
    """返回 (归一化文本, 归一化字符到原字符的索引映射)。"""
    n = len(text)
    start, end = 0, n
    if opts.ignore_outer_space:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
    indices: list[int] = []
    chars: list[str] = []
    for i in range(start, end):
        ch = text[i]
        if opts.ignore_all_space and ch.isspace():
            continue
        if opts.ignore_case:
            low = ch.lower()
            for c in low:
                chars.append(c)
                indices.append(i)
        else:
            chars.append(ch)
            indices.append(i)
    return "".join(chars), indices


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ranges.sort()
    merged = [ranges[0]]
    for s, e in ranges[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


def _char_spans(
    left_text: str, right_text: str, opts: TextCompareOptions
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    na, ma = _normalize_line(left_text, opts)
    nb, mb = _normalize_line(right_text, opts)
    if na == nb:
        return [], []
    spans_l: list[tuple[int, int]] = []
    spans_r: list[tuple[int, int]] = []
    sm = SequenceMatcher(None, na, nb, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if i1 < i2 and ma:
            spans_l.append((ma[i1], ma[i2 - 1] + 1))
        if j1 < j2 and mb:
            spans_r.append((mb[j1], mb[j2 - 1] + 1))
    return _merge_ranges(spans_l), _merge_ranges(spans_r)


def _ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if min(len(a), len(b)) * 4 < max(len(a), len(b)):
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=True).quick_ratio()


def _align_replace_block(
    left: list[_PhysicalLine], right: list[_PhysicalLine], opts: TextCompareOptions
) -> list[tuple[str, int | None, int | None]]:
    """用动态规划在替换块内对齐相似行，避免把无关行硬配对。

    返回操作序列: ("pair", i, j) / ("del", i, None) / ("ins", None, j)。
    """
    n, m = len(left), len(right)
    if n == 1 and m == 1:
        return [("pair", 0, 0)]
    ln = [_normalize_line(x.text, opts)[0] for x in left]
    rn = [_normalize_line(x.text, opts)[0] for x in right]
    sim = [[_ratio(ln[i], rn[j]) for j in range(m)] for i in range(n)]
    gap = 0.0
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    bt = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + gap
        bt[i][0] = "del"
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + gap
        bt[0][j] = "ins"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            pair_score = dp[i - 1][j - 1] + max(0.0, sim[i - 1][j - 1] - 0.30)
            del_score = dp[i - 1][j]
            ins_score = dp[i][j - 1]
            best = max(pair_score, del_score, ins_score)
            dp[i][j] = best
            if best == pair_score and (sim[i - 1][j - 1] > 0.0 or n == m):
                bt[i][j] = "pair"
            elif best == del_score:
                bt[i][j] = "del"
            else:
                bt[i][j] = "ins"
    ops: list[tuple[str, int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        op = bt[i][j]
        if op == "pair":
            ops.append(("pair", i - 1, j - 1))
            i -= 1
            j -= 1
        elif op == "del" or j == 0:
            ops.append(("del", i - 1, None))
            i -= 1
        else:
            ops.append(("ins", None, j - 1))
            j -= 1
    ops.reverse()
    return ops


def compare_texts(
    left_text: str,
    right_text: str,
    left_path: str = "",
    right_path: str = "",
    left_encoding: str = "UTF-8",
    right_encoding: str = "UTF-8",
    options: TextCompareOptions | None = None,
    left_warnings: list[str] | None = None,
    right_warnings: list[str] | None = None,
) -> TextComparison:
    opts = options or TextCompareOptions()
    llines, ltrail = split_physical_lines(left_text)
    rlines, rtrail = split_physical_lines(right_text)

    left_lines: list[DisplayLine] = []
    right_lines: list[DisplayLine] = []
    diffs: list[DiffItem] = []
    warnings: list[str] = []
    for w in left_warnings or []:
        warnings.append(f"左侧：{w}")
    for w in right_warnings or []:
        warnings.append(f"右侧：{w}")

    lkeys = [_normalize_line(x.text, opts)[0] for x in llines]
    rkeys = [_normalize_line(x.text, opts)[0] for x in rlines]
    autojunk = len(lkeys) + len(rkeys) > 60000
    if autojunk:
        warnings.append("文件行数较多，已启用快速行匹配；差异定位仍以字符比较为准。")
    sm = SequenceMatcher(None, lkeys, rkeys, autojunk=autojunk)

    counter = 0

    def new_diff(
        kind: DiffKind,
        title: str,
        left_line: _PhysicalLine | None,
        right_line: _PhysicalLine | None,
        left_no: int | None,
        right_no: int | None,
        left_spans: list[tuple[int, int]],
        right_spans: list[tuple[int, int]],
        display_row: int,
        severity: Severity = Severity.CONFIRMED,
        detail: str = "",
    ) -> DiffItem:
        nonlocal counter
        counter += 1
        item = DiffItem(
            id=f"text:{counter}",
            kind=kind,
            severity=severity,
            title=title,
            left=DiffLocation(
                kind="text",
                line=left_no,
                text=left_line.text if left_line else "",
                spans=left_spans,
                extra={"display_row": display_row, "placeholder": left_line is None},
            ),
            right=DiffLocation(
                kind="text",
                line=right_no,
                text=right_line.text if right_line else "",
                spans=right_spans,
                extra={"display_row": display_row, "placeholder": right_line is None},
            ),
            detail=detail,
            group="text",
        )
        return item

    def add_row(
        left_line: _PhysicalLine | None,
        right_line: _PhysicalLine | None,
        left_no: int | None,
        right_no: int | None,
        kind: DiffKind,
        left_spans: list[tuple[int, int]],
        right_spans: list[tuple[int, int]],
        title: str,
    ) -> None:
        row_idx = len(left_lines)
        diff_id: str | None = None
        if kind != DiffKind.MODIFIED:
            item = new_diff(
                kind, title, left_line, right_line, left_no, right_no,
                left_spans, right_spans, row_idx,
            )
            diffs.append(item)
            diff_id = item.id
        elif left_spans or right_spans:
            item = new_diff(
                kind, title, left_line, right_line, left_no, right_no,
                left_spans, right_spans, row_idx,
            )
            diffs.append(item)
            diff_id = item.id

        if left_line is None:
            left_lines.append(
                DisplayLine(text="", line_no=None, status=LineStatus.PLACEHOLDER, diff_id=diff_id)
            )
        else:
            status = (
                LineStatus.EQUAL
                if not (left_spans or right_spans) and kind == DiffKind.MODIFIED
                else (LineStatus.MODIFIED if kind == DiffKind.MODIFIED else LineStatus.REMOVED)
            )
            if kind == DiffKind.ADDED:
                status = LineStatus.EQUAL
            left_lines.append(
                DisplayLine(
                    text=left_line.text,
                    line_no=left_no,
                    status=status,
                    spans=[TextSpan(s, e) for s, e in left_spans],
                    diff_id=diff_id,
                )
            )
        if right_line is None:
            right_lines.append(
                DisplayLine(text="", line_no=None, status=LineStatus.PLACEHOLDER, diff_id=diff_id)
            )
        else:
            status = (
                LineStatus.EQUAL
                if not (left_spans or right_spans) and kind == DiffKind.MODIFIED
                else (LineStatus.MODIFIED if kind == DiffKind.MODIFIED else LineStatus.ADDED)
            )
            if kind == DiffKind.REMOVED:
                status = LineStatus.EQUAL
            right_lines.append(
                DisplayLine(
                    text=right_line.text,
                    line_no=right_no,
                    status=status,
                    spans=[TextSpan(s, e) for s, e in right_spans],
                    diff_id=diff_id,
                )
            )

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                li, rj = i1 + k, j1 + k
                add_row(
                    llines[li], rlines[rj], li + 1, rj + 1,
                    DiffKind.MODIFIED, [], [], "相同",
                )
        elif tag == "delete":
            for li in range(i1, i2):
                add_row(
                    llines[li], None, li + 1, None,
                    DiffKind.REMOVED, [(0, len(llines[li].text))], [],
                    f"第 {li + 1} 行仅左侧存在",
                )
        elif tag == "insert":
            for rj in range(j1, j2):
                add_row(
                    None, rlines[rj], None, rj + 1,
                    DiffKind.ADDED, [], [(0, len(rlines[rj].text))],
                    f"第 {rj + 1} 行仅右侧存在",
                )
        else:  # replace
            ops = _align_replace_block(llines[i1:i2], rlines[j1:j2], opts)
            for op, ii, jj in ops:
                li = i1 + ii if ii is not None else None
                rj = j1 + jj if jj is not None else None
                if op == "pair":
                    assert li is not None and rj is not None
                    lp, rp = llines[li], rlines[rj]
                    left_spans, right_spans = _char_spans(lp.text, rp.text, opts)
                    add_row(
                        lp, rp, li + 1, rj + 1, DiffKind.MODIFIED,
                        left_spans, right_spans,
                        f"第 {li + 1} 行 / 第 {rj + 1} 行内容不同",
                    )
                elif op == "del":
                    assert li is not None
                    add_row(
                        llines[li], None, li + 1, None,
                        DiffKind.REMOVED, [(0, len(llines[li].text))], [],
                        f"第 {li + 1} 行仅左侧存在",
                    )
                else:
                    assert rj is not None
                    add_row(
                        None, rlines[rj], None, rj + 1,
                        DiffKind.ADDED, [], [(0, len(rlines[rj].text))],
                        f"第 {rj + 1} 行仅右侧存在",
                    )

    # 换行符差异单独作为一条差异，避免每行重复计数。
    if not opts.ignore_line_endings:
        lsig = line_ending_signature(llines)
        rsig = line_ending_signature(rlines)
        if lsig != rsig or ltrail != rtrail:
            counter += 1
            details = []
            if lsig != rsig:
                details.append(f"换行符类型不同：左侧 {lsig!r}，右侧 {rsig!r}")
            if ltrail != rtrail:
                details.append(
                    f"文件末尾换行不同：左侧{'有' if ltrail else '无'}，右侧{'有' if rtrail else '无'}"
                )
            first_left = next((x for x in llines if x.text), None)
            first_right = next((x for x in rlines if x.text), None)
            diffs.append(
                DiffItem(
                    id=f"text:{counter}",
                    kind=DiffKind.MODIFIED,
                    severity=Severity.CONFIRMED,
                    title="换行符差异",
                    left=DiffLocation(
                        kind="text", line=1 if first_left else None,
                        text=first_left.text if first_left else "",
                        extra={"display_row": 0},
                    ),
                    right=DiffLocation(
                        kind="text", line=1 if first_right else None,
                        text=first_right.text if first_right else "",
                        extra={"display_row": 0},
                    ),
                    detail="；".join(details),
                    group="text",
                )
            )

    left_side = TextSide(
        path=left_path,
        encoding=left_encoding,
        lines=left_lines,
        line_ending=line_ending_signature(llines),
        trailing_newline=ltrail,
        original_line_count=len(llines),
    )
    right_side = TextSide(
        path=right_path,
        encoding=right_encoding,
        lines=right_lines,
        line_ending=line_ending_signature(rlines),
        trailing_newline=rtrail,
        original_line_count=len(rlines),
    )
    comparison = TextComparison(
        left=left_side,
        right=right_side,
        diffs=diffs,
        warnings=warnings,
        settings=opts.as_dict(),
    )
    return comparison


def compare_text_files(
    left_path: str | Path,
    right_path: str | Path,
    options: TextCompareOptions | None = None,
) -> TextComparison:
    left = read_text(left_path)
    right = read_text(right_path)
    return compare_texts(
        left.text,
        right.text,
        str(left_path),
        str(right_path),
        left.encoding,
        right.encoding,
        options,
        left.warnings,
        right.warnings,
    )
