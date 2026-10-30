"""文件格式识别与比较模式判定。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .models import CompareMode


class FileKind(str, Enum):
    TEXT = "text"
    CSV = "csv"
    XLS = "xls"
    XLSX = "xlsx"
    IMAGE = "image"


TEXT_EXTS = {".txt"}
CSV_EXTS = {".csv"}
SPREADSHEET_EXTS = {".xls", ".xlsx"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}

SUPPORTED_EXTS = sorted(TEXT_EXTS | CSV_EXTS | SPREADSHEET_EXTS | IMAGE_EXTS)
SUPPORTED_DIALOG_FILTER = (
    "支持的文件 (*.txt *.csv *.xls *.xlsx *.png *.jpg *.jpeg *.bmp);;"
    "文本 (*.txt);;CSV (*.csv);;Excel (*.xls *.xlsx);;图片 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*)"
)
IMAGE_DIALOG_FILTER = "图片 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*)"
TEXT_DIALOG_FILTER = "文本文件 (*.txt *.csv);;所有文件 (*)"
SPREADSHEET_DIALOG_FILTER = "Excel 工作簿 (*.xls *.xlsx);;所有文件 (*)"


class IncompatibleFilesError(ValueError):
    """左右文件类型无法比较。"""


@dataclass(frozen=True)
class FileInfo:
    path: str
    name: str
    ext: str
    kind: FileKind
    size: int

    @property
    def exists(self) -> bool:
        return Path(self.path).is_file()

    @property
    def human_size(self) -> str:
        size = float(self.size)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return f"{size:.1f} GB"

    @property
    def type_label(self) -> str:
        return {
            FileKind.TEXT: "TXT 文本",
            FileKind.CSV: "CSV 表格",
            FileKind.XLS: "XLS 工作簿",
            FileKind.XLSX: "XLSX 工作簿",
            FileKind.IMAGE: "图片",
        }[self.kind]


def classify(path: str | Path) -> FileInfo:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in TEXT_EXTS:
        kind = FileKind.TEXT
    elif ext in CSV_EXTS:
        kind = FileKind.CSV
    elif ext == ".xls":
        kind = FileKind.XLS
    elif ext == ".xlsx":
        kind = FileKind.XLSX
    elif ext in IMAGE_EXTS:
        kind = FileKind.IMAGE
    else:
        raise IncompatibleFilesError(
            f"不支持的文件类型：{p.name}\n"
            f"EngineerDiff 支持：TXT、CSV、XLS、XLSX、PNG、JPG、JPEG、BMP。"
        )
    try:
        size = p.stat().st_size
    except OSError:
        size = 0
    return FileInfo(str(p.resolve()), p.name, ext, kind, size)


def determine_mode(left_path: str | Path, right_path: str | Path) -> CompareMode:
    """根据两侧文件类型返回比较模式，不兼容时抛出明确异常。"""
    a = classify(left_path)
    b = classify(right_path)
    a_spread = a.kind in (FileKind.XLS, FileKind.XLSX)
    b_spread = b.kind in (FileKind.XLS, FileKind.XLSX)
    a_image = a.kind == FileKind.IMAGE
    b_image = b.kind == FileKind.IMAGE

    if a_spread or b_spread:
        if a_spread and b_spread:
            return CompareMode.EXCEL
        other = b if a_spread else a
        raise IncompatibleFilesError(
            f"不能比较 {a.type_label} 与 {other.type_label}。\n"
            "Excel 比较需要左右两侧都是 XLS/XLSX 工作簿。"
        )
    if a_image or b_image:
        if a_image and b_image:
            return CompareMode.IMAGE
        other = b if a_image else a
        raise IncompatibleFilesError(
            f"不能比较 {a.type_label} 与 {other.type_label}。\n"
            "图片比较需要左右两侧都是 PNG/JPG/JPEG/BMP 截图。"
        )
    if a.kind == FileKind.CSV and b.kind == FileKind.CSV:
        return CompareMode.CSV
    return CompareMode.TEXT


def mode_label(mode: CompareMode) -> str:
    return {
        CompareMode.TEXT: "文本比较",
        CompareMode.CSV: "CSV 比较",
        CompareMode.EXCEL: "Excel 工作簿比较",
        CompareMode.IMAGE: "图片 OCR 比较",
    }[mode]


def is_supported(path: str | Path) -> bool:
    try:
        classify(path)
        return True
    except IncompatibleFilesError:
        return False
