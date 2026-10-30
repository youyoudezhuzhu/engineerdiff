"""左右两侧容器：文件头、内容占位、拖拽导入。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..file_loader import FileInfo, SUPPORTED_EXTS
from . import theme


class SidePane(QFrame):
    file_dropped = Signal(str)
    clicked = Signal(str)

    def __init__(self, side: str, parent=None):
        super().__init__(parent)
        self.side = side
        self._content: QWidget | None = None
        self.setObjectName("sidePane")
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            "QFrame#sidePane { background:#FFFFFF; border:1px solid #D8DEE6; border-radius:6px; }"
            "QFrame#sidePane[dragActive=\"true\"] { border:2px solid #2563EB; }"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("sideHeader")
        header.setStyleSheet(
            "QWidget#sideHeader { background:#F8FAFC; border-bottom:1px solid #D8DEE6;"
            "border-top-left-radius:6px; border-top-right-radius:6px; }"
        )
        h = QHBoxLayout(header)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(8)
        self.badge = QLabel(side.upper())
        self.badge.setFixedSize(22, 22)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setStyleSheet(
            "background:#2563EB;color:white;border-radius:4px;font-weight:600;font-size:10pt;"
            if side == "left"
            else "background:#6B7280;color:white;border-radius:4px;font-weight:600;font-size:10pt;"
        )
        self.name_label = QLabel("未选择文件")
        self.name_label.setStyleSheet("font-weight:600;color:#1F2328;")
        self.name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet("color:#6B7280;font-size:9pt;")
        self.meta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self.badge)
        h.addWidget(self.name_label, 1)
        h.addWidget(self.meta_label)
        self._layout.addWidget(header)

        self._stack = QStackedWidget()
        self._empty = QLabel()
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setStyleSheet("color:#7B8494;background:#FFFFFF;padding:24px;")
        self._empty.setText(
            "<div style='font-size:14pt;color:#4B5563;margin-bottom:8px;'>拖入文件到此处</div>"
            "<div style='font-size:9.5pt;line-height:1.6;'>或点击上方“选择文件”<br>"
            "支持 TXT / CSV / XLS / XLSX / PNG / JPG / JPEG / BMP<br>"
            "图片可直接 Ctrl+V 粘贴截图</div>"
        )
        self._stack.addWidget(self._empty)
        self._layout.addWidget(self._stack, 1)
        self._info: FileInfo | None = None

    # ------------------------------------------------------------------
    def set_file(self, info: FileInfo | None) -> None:
        self._info = info
        if info is None:
            self.name_label.setText("未选择文件")
            self.meta_label.setText("")
            self.setToolTip("")
            return
        self.name_label.setText(info.name)
        self.name_label.setToolTip(info.path)
        self.meta_label.setText(f"{info.type_label} · {info.human_size}")
        self.setToolTip(info.path)

    def set_meta(self, text: str) -> None:
        self.meta_label.setText(text)

    def set_content(self, widget: QWidget | None, empty_text: str | None = None) -> None:
        if self._content is not None:
            self._stack.removeWidget(self._content)
            self._content.deleteLater()
            self._content = None
        if widget is None:
            if empty_text is not None:
                self.set_empty_text(empty_text)
            self._stack.setCurrentWidget(self._empty)
            return
        self._content = widget
        self._stack.addWidget(widget)
        self._stack.setCurrentWidget(widget)

    def set_empty_text(self, text: str) -> None:
        self._empty.setText(
            f"<div style='font-size:11pt;color:#4B5563;line-height:1.7;'>{text}</div>"
        )

    def content(self) -> QWidget | None:
        return self._content

    def show_placeholder(self, text: str) -> None:
        self.set_content(None, text)

    # ------------------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        self.clicked.emit(self.side)
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent):  # noqa: N802
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    ext = Path(url.toLocalFile()).suffix.lower()
                    if ext in SUPPORTED_EXTS:
                        event.acceptProposedAction()
                        self._set_drag_active(True)
                        return
        event.ignore()

    def dragLeaveEvent(self, event):  # noqa: N802
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):  # noqa: N802
        self._set_drag_active(False)
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    if Path(path).suffix.lower() in SUPPORTED_EXTS:
                        self.file_dropped.emit(path)
                        event.acceptProposedAction()
                        return
        event.ignore()

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
