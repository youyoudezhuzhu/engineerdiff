"""EngineerDiff 统一数据模型。

比较引擎只依赖本模块，不依赖 Qt。UI 通过本模块的统一结构渲染差异。
坐标为图像/表格/文本的原始坐标，缩放由 UI 负责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CompareMode(str, Enum):
    TEXT = "text"
    CSV = "csv"
    EXCEL = "excel"
    IMAGE = "image"


class DiffKind(str, Enum):
    MODIFIED = "modified"
    ADDED = "added"
    REMOVED = "removed"
    ONLY_LEFT = "only_left"
    ONLY_RIGHT = "only_right"
    UNCERTAIN = "uncertain"


class Severity(str, Enum):
    CONFIRMED = "confirmed"  # 红色：确定差异
    UNCERTAIN = "uncertain"  # 橙色：无法可靠确认


class LineStatus(str, Enum):
    EQUAL = "equal"
    MODIFIED = "modified"
    ADDED = "added"
    REMOVED = "removed"
    PLACEHOLDER = "placeholder"


class SheetStatus(str, Enum):
    EQUAL = "equal"
    DIFFERENT = "different"
    ONLY_LEFT = "only_left"
    ONLY_RIGHT = "only_right"


class CellType(str, Enum):
    BLANK = "blank"
    NUMBER = "number"
    TEXT = "text"
    BOOL = "boolean"
    DATE = "date"
    ERROR = "error"
    FORMULA = "formula"


@dataclass
class BBox:
    """轴对齐包围盒，单位：原图像素或表格坐标像素。"""

    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def union(self, other: "BBox") -> "BBox":
        x = min(self.x, other.x)
        y = min(self.y, other.y)
        return BBox(x, y, max(self.right, other.right) - x, max(self.bottom, other.bottom) - y)

    def intersects(self, other: "BBox", pad: float = 0.0) -> bool:
        return not (
            self.right + pad < other.x
            or other.right + pad < self.x
            or self.bottom + pad < other.y
            or other.bottom + pad < self.y
        )

    def iou(self, other: "BBox") -> float:
        inter_w = max(0.0, min(self.right, other.right) - max(self.x, other.x))
        inter_h = max(0.0, min(self.bottom, other.bottom) - max(self.y, other.y))
        inter = inter_w * inter_h
        if inter <= 0:
            return 0.0
        union = self.w * self.h + other.w * other.h - inter
        return inter / union if union else 0.0

    @classmethod
    def from_quad(cls, quad: list[tuple[float, float]]) -> "BBox":
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        return cls(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.w, self.h]


@dataclass
class DiffLocation:
    """差异在一侧的位置。不同渲染器只使用其中相关字段。"""

    kind: str  # text / cell / image / sheet
    line: int | None = None  # 1-based 原始行号
    row: int | None = None  # 0-based 表格行
    col: int | None = None  # 0-based 表格列
    bbox: BBox | None = None
    text: str = ""
    sheet: str | None = None
    spans: list[tuple[int, int]] = field(default_factory=list)  # text 中字符区间 [start,end)
    segment_boxes: list[BBox] = field(default_factory=list)  # 图像字符/片段框
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiffItem:
    """一处可导航的差异。"""

    id: str
    kind: DiffKind
    severity: Severity = Severity.CONFIRMED
    title: str = ""
    left: DiffLocation | None = None
    right: DiffLocation | None = None
    confidence: float | None = None
    needs_review: bool = False
    detail: str = ""
    group: str = ""  # text / cell / sheet / image

    @property
    def is_uncertain(self) -> bool:
        return self.severity == Severity.UNCERTAIN or self.needs_review


@dataclass
class TextSpan:
    start: int
    end: int
    severity: Severity = Severity.CONFIRMED

    def as_tuple(self) -> tuple[int, int, str]:
        return self.start, self.end, self.severity.value


@dataclass
class DisplayLine:
    """某一侧用于并排显示的一行。对侧新增/删除时用 PLACEHOLDER 占位。"""

    text: str
    line_no: int | None
    status: LineStatus = LineStatus.EQUAL
    spans: list[TextSpan] = field(default_factory=list)
    diff_id: str | None = None

    @property
    def is_changed(self) -> bool:
        return self.status in (LineStatus.MODIFIED, LineStatus.ADDED, LineStatus.REMOVED)


@dataclass
class TextSide:
    path: str
    encoding: str
    lines: list[DisplayLine] = field(default_factory=list)
    line_ending: str = ""
    trailing_newline: bool = True
    original_line_count: int = 0

    def reveal_line(self, line_no: int | None) -> int | None:
        """根据原始行号返回显示行索引。"""
        if line_no is None:
            return None
        for i, line in enumerate(self.lines):
            if line.line_no == line_no:
                return i
        return None


@dataclass
class TextComparison:
    left: TextSide
    right: TextSide
    diffs: list[DiffItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class CellStyle:
    bold: bool = False
    italic: bool = False
    font_size: float = 11.0
    font_color: str = "#1F2328"
    fill_color: str | None = None
    h_align: str = "left"  # left / center / right
    v_align: str = "center"  # top / center / bottom
    wrap: bool = False
    number_format: str | None = None


@dataclass
class Cell:
    """表格单元格。value 为规范化后的原始值，display 为展示文本。"""

    display: str = ""
    type: CellType = CellType.BLANK
    value: Any = None
    formula: str | None = None
    cached: Any = None
    style: CellStyle = field(default_factory=CellStyle)
    span: tuple[int, int] | None = None  # 合并单元格锚点的 (rowspan, colspan)
    merged_anchor: tuple[int, int] | None = None  # 非锚点指向锚点
    hidden: bool = False

    @property
    def is_blank(self) -> bool:
        return self.type == CellType.BLANK


@dataclass
class Sheet:
    name: str
    rows: list[list[Cell]] = field(default_factory=list)  # 矩形，nrows x ncols
    nrows: int = 0
    ncols: int = 0
    merged: list[tuple[int, int, int, int]] = field(default_factory=list)  # r,c,rowspan,colspan
    col_widths: dict[int, float] = field(default_factory=dict)  # 像素(96dpi)
    row_heights: dict[int, float] = field(default_factory=dict)  # 像素(96dpi)
    default_col_width: float = 72.0
    default_row_height: float = 20.0
    hidden_cols: set[int] = field(default_factory=set)
    hidden_rows: set[int] = field(default_factory=set)
    tab_color: str | None = None

    def cell(self, row: int, col: int) -> Cell:
        if 0 <= row < self.nrows and 0 <= col < self.ncols:
            return self.rows[row][col]
        return Cell()

    def bbox_exists(self, row: int, col: int) -> bool:
        return 0 <= row < self.nrows and 0 <= col < self.ncols


@dataclass
class Workbook:
    path: str
    sheets: list[Sheet] = field(default_factory=list)
    fmt: str = ""  # xlsx / xls / csv
    warnings: list[str] = field(default_factory=list)
    title: str = ""

    def sheet(self, name: str) -> Sheet | None:
        for s in self.sheets:
            if s.name == name:
                return s
        return None


@dataclass
class SheetComparison:
    name: str
    left_index: int | None = None
    right_index: int | None = None
    left: Sheet | None = None
    right: Sheet | None = None
    status: SheetStatus = SheetStatus.EQUAL
    diffs: list[DiffItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class WorkbookComparison:
    left: Workbook
    right: Workbook
    sheets: list[SheetComparison] = field(default_factory=list)
    diffs: list[DiffItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)

    def sheet_by_name(self, name: str) -> SheetComparison | None:
        for s in self.sheets:
            if s.name == name:
                return s
        return None

    @property
    def different_sheet_names(self) -> set[str]:
        return {s.name for s in self.sheets if s.status != SheetStatus.EQUAL}


@dataclass
class CsvComparison:
    left: Sheet
    right: Sheet
    table: WorkbookComparison
    text: TextComparison
    delimiter: str = ","
    warnings: list[str] = field(default_factory=list)


@dataclass
class OcrBox:
    """OCR 文字框。坐标单位：原图像素。"""

    id: int
    text: str
    confidence: float
    bbox: BBox
    quad: list[tuple[float, float]] = field(default_factory=list)
    raw_text: str = ""  # 原始 OCR 文本（手动修正前）
    overridden: bool = False

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.6


@dataclass
class OcrPage:
    path: str
    width: int
    height: int
    boxes: list[OcrBox] = field(default_factory=list)
    engine: str = "RapidOCR + ONNX Runtime"
    cached: bool = False
    elapsed: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.boxes)


@dataclass
class ImageComparison:
    left: OcrPage
    right: OcrPage
    diffs: list[DiffItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    transform: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    elapsed: float = 0.0


@dataclass
class ComparisonResult:
    mode: CompareMode
    left_path: str
    right_path: str
    text: TextComparison | None = None
    csv: CsvComparison | None = None
    workbook: WorkbookComparison | None = None
    image: ImageComparison | None = None
    warnings: list[str] = field(default_factory=list)
    elapsed: float = 0.0

    def diffs_for_view(self, view: str) -> list[DiffItem]:
        """view: text / table / image。"""
        if view == "image" and self.image is not None:
            return self.image.diffs
        if view == "table":
            if self.csv is not None:
                return self.csv.table.diffs
            if self.workbook is not None:
                return self.workbook.diffs
        if view == "text" and self.text is not None:
            return self.text.diffs
        return []


# ---------------------------------------------------------------------------
# 比较选项
# ---------------------------------------------------------------------------


@dataclass
class TextCompareOptions:
    ignore_line_endings: bool = False
    ignore_outer_space: bool = False
    ignore_all_space: bool = False
    ignore_case: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ignore_line_endings": self.ignore_line_endings,
            "ignore_outer_space": self.ignore_outer_space,
            "ignore_all_space": self.ignore_all_space,
            "ignore_case": self.ignore_case,
        }


@dataclass
class SpreadsheetOptions:
    formula_mode: str = "formula"  # formula: 优先比较公式表达式；value: 比较缓存值
    numeric_tolerance: float = 0.0
    smart_rows: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "formula_mode": self.formula_mode,
            "numeric_tolerance": self.numeric_tolerance,
            "smart_rows": self.smart_rows,
        }


@dataclass
class ImageOptions:
    confidence_threshold: float = 0.60
    match_threshold: float = 0.42
    show_boxes: bool = False
    manual_pairs: list[tuple[int, int]] = field(default_factory=list)
    # 键为 "left"/"right"，值为 {box_id: 修正文本}
    text_overrides: dict[str, dict[int, str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "confidence_threshold": self.confidence_threshold,
            "match_threshold": self.match_threshold,
            "show_boxes": self.show_boxes,
            "manual_pairs": [list(p) for p in self.manual_pairs],
            "text_overrides": {k: dict(v) for k, v in self.text_overrides.items()},
        }


@dataclass
class AppSettings:
    text: TextCompareOptions = field(default_factory=TextCompareOptions)
    spreadsheet: SpreadsheetOptions = field(default_factory=SpreadsheetOptions)
    image: ImageOptions = field(default_factory=ImageOptions)
    sync_scroll: bool = True
    sync_sheets: bool = True
    only_diffs: bool = False
    ocr_cache: bool = True
    theme: str = "system"  # system / light / dark
