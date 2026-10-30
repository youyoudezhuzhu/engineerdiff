"""批量比较对话框：一个基准 + 多个候选文件，按“任意文件不同即标红”的或语义展示。"""

from __future__ import annotations

import copy
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..batch import BatchError, BatchResult, run_batch
from ..file_loader import SUPPORTED_DIALOG_FILTER, classify
from ..models import AppSettings, CompareMode, Severity
from ..ocr.engine import OcrService
from . import theme


class _FileList(QListWidget):
    paths_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setStyleSheet(
            "QListWidget { background:#FFFFFF; border:1px solid #E0E0E0; border-radius:6px;"
            "padding:4px; } QListWidget::item { padding:5px 6px; border-radius:4px; }"
            "QListWidget::item:selected { background:#E5F1FB; color:#1B1B1B; }"
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class BatchWorker(QThread):
    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, baseline: str, candidates: list[str], settings: AppSettings,
                 ocr: OcrService | None, parent=None):
        super().__init__(parent)
        self._baseline = baseline
        self._candidates = list(candidates)
        self._settings = copy.deepcopy(settings)
        self._ocr = ocr
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:  # noqa: D401
        try:
            result = run_batch(
                self._baseline,
                self._candidates,
                self._settings,
                progress=lambda p, m: self.progress.emit(p, m),
                cancel=self._cancel.is_set,
                ocr_service=self._ocr,
            )
            if self._cancel.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)
        except Exception as exc:  # noqa: BLE001
            if self._cancel.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc))


class BatchCompareDialog(QDialog):
    """批量差异表：基准为列表第一项；任意候选不同即标红。"""

    def __init__(self, parent=None, settings: AppSettings | None = None,
                 initial_left: str = "", initial_right: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("EngineerDiff - 批量比较")
        self.resize(1320, 820)
        self.setMinimumSize(980, 620)
        self._settings = copy.deepcopy(settings or AppSettings())
        self._worker: BatchWorker | None = None
        self._result: BatchResult | None = None
        self._ocr: OcrService | None = None
        self._build_ui()
        for path in (initial_left, initial_right):
            if path:
                self._add_paths([path])

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(8)

        title = QLabel("批量比较")
        title.setStyleSheet("font-size:17pt;font-weight:600;color:#1B1B1B;")
        root.addWidget(title)
        hint = QLabel(
            "第一个文件作为基准 A；其余文件依次与基准比较。"
            "同一位置只要有任意一个文件不同，整行标红（或关系）。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#616161;")
        root.addWidget(hint)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        # 文件面板
        file_panel = QFrame()
        file_panel.setObjectName("filePanel")
        file_panel.setStyleSheet(
            "QFrame#filePanel { background:#FFFFFF; border:1px solid #E0E0E0; border-radius:8px; }"
        )
        fp = QVBoxLayout(file_panel)
        fp.setContentsMargins(10, 8, 10, 8)
        fp.setSpacing(6)
        fph = QHBoxLayout()
        self.lbl_baseline = QLabel("基准：未选择")
        self.lbl_baseline.setStyleSheet("font-weight:600;color:#1B1B1B;")
        fph.addWidget(self.lbl_baseline, 1)
        self.lbl_count = QLabel("共 0 个文件")
        self.lbl_count.setStyleSheet("color:#616161;")
        fph.addWidget(self.lbl_count)
        fp.addLayout(fph)

        self.file_list = _FileList()
        self.file_list.setMaximumHeight(150)
        self.file_list.paths_dropped.connect(self._add_paths)
        fp.addWidget(self.file_list, 1)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("添加文件…")
        self.btn_add.setObjectName("tool")
        self.btn_remove = QPushButton("移除选中")
        self.btn_remove.setObjectName("tool")
        self.btn_clear = QPushButton("清空")
        self.btn_clear.setObjectName("tool")
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_remove)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch(1)
        self.btn_start = QPushButton("开始批量比较")
        self.btn_start.setObjectName("primary")
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("tool")
        self.btn_cancel.setVisible(False)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_cancel)
        fp.addLayout(btn_row)
        splitter.addWidget(file_panel)

        # 结果面板
        result_panel = QFrame()
        result_panel.setStyleSheet("QFrame { background:#FFFFFF; border:1px solid #E0E0E0; border-radius:8px; }")
        rp = QVBoxLayout(result_panel)
        rp.setContentsMargins(10, 8, 10, 8)
        rp.setSpacing(6)
        result_head = QHBoxLayout()
        self.lbl_summary = QLabel("尚未开始比较")
        self.lbl_summary.setStyleSheet("font-weight:600;color:#1B1B1B;")
        result_head.addWidget(self.lbl_summary, 1)
        legend = QLabel("红 = 确定差异 · 橙 = 需人工复核")
        legend.setStyleSheet("color:#616161;")
        result_head.addWidget(legend)
        self.btn_copy = QPushButton("复制差异表")
        self.btn_copy.setObjectName("tool")
        self.btn_copy.setEnabled(False)
        result_head.addWidget(self.btn_copy)
        rp.addLayout(result_head)

        self.table = QTableWidget(0, 2)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.setStyleSheet(
            "QTableWidget { background:#FFFFFF; border:1px solid #E0E0E0; gridline-color:#EEEEEE; }"
            "QHeaderView::section { background:#FAFAFA; border:none; border-bottom:1px solid #E0E0E0;"
            "border-right:1px solid #EEEEEE; padding:6px 8px; color:#424242; font-weight:600; }"
            "QTableWidget::item { padding:4px 6px; }"
            "QTableWidget::item:selected { background:#E5F1FB; color:#1B1B1B; }"
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        rp.addWidget(self.table, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#616161;")
        rp.addWidget(self.lbl_status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        rp.addWidget(self.progress)
        splitter.addWidget(result_panel)
        splitter.setSizes([210, 520])
        root.addWidget(splitter, 1)

        self.btn_close = QPushButton("关闭")
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(self.btn_close)
        root.addLayout(close_row)

        self.btn_add.clicked.connect(self._choose_files)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear.clicked.connect(self.file_list.clear)
        self.btn_start.clicked.connect(self._start)
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_copy.clicked.connect(self._copy_table)
        self.btn_close.clicked.connect(self.reject)
        self.file_list.model().rowsInserted.connect(self._refresh_file_count)
        self.file_list.model().rowsRemoved.connect(self._refresh_file_count)
        self._refresh_file_count()

    # ------------------------------------------------------------------ files
    def _add_paths(self, paths: list[str]) -> None:
        existing = {
            self.file_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.file_list.count())
        }
        for path in paths:
            try:
                info = classify(path)
            except Exception:
                continue
            if not info.exists or info.path in existing:
                continue
            item = QListWidgetItem()
            label = f"{info.name}    {info.type_label} · {info.human_size}"
            item.setText(label)
            item.setData(Qt.ItemDataRole.UserRole, info.path)
            item.setToolTip(info.path)
            self.file_list.addItem(item)
            existing.add(info.path)

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "添加批量比较文件（第一个默认为基准）", "", SUPPORTED_DIALOG_FILTER
        )
        if paths:
            self._add_paths(paths)

    def _remove_selected(self) -> None:
        rows = sorted({self.file_list.row(item) for item in self.file_list.selectedItems()}, reverse=True)
        for row in rows:
            self.file_list.takeItem(row)

    def _paths(self) -> list[str]:
        return [
            self.file_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.file_list.count())
        ]

    def _refresh_file_count(self, *_args) -> None:
        paths = self._paths()
        self.lbl_count.setText(f"共 {len(paths)} 个文件")
        self.lbl_baseline.setText(
            f"基准：{Path(paths[0]).name}" if paths else "基准：未选择（列表第一个文件为基准）"
        )

    # ------------------------------------------------------------------ run
    def _start(self) -> None:
        paths = self._paths()
        if len(paths) < 2:
            QMessageBox.information(self, "批量比较", "请至少添加 2 个文件（第一个为基准）。")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self.table.clearContents()
        self.table.setRowCount(0)
        self.lbl_summary.setText("正在比较…")
        self.lbl_status.setText("")
        self._set_running(True)
        # 图片批量比较才需要 OCR 服务；复用默认缓存目录，模型进程内共享。
        ocr = None
        try:
            if all(classify(p).kind.value == "image" for p in paths):
                ocr = OcrService()
        except Exception:
            ocr = None
        self._ocr = ocr
        self._worker = BatchWorker(paths[0], paths[1:], self._settings, ocr, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.lbl_status.setText("正在取消…")
            self.btn_cancel.setEnabled(False)

    def _on_progress(self, percent: int, message: str) -> None:
        self.progress.setValue(max(0, min(100, percent)))
        self.lbl_status.setText(message)

    def _on_succeeded(self, result: BatchResult) -> None:
        self._result = result
        self._populate(result)
        self._set_running(False)
        self.progress.setVisible(False)
        self.lbl_summary.setText(
            f"共 {result.file_count} 个文件 · {result.different_count} 处位置存在差异"
            f"（任意文件不同即标红）· {result.elapsed:.1f}s"
        )
        if result.warnings:
            self.lbl_status.setText("；".join(result.warnings[:3]))
            self.lbl_status.setToolTip("\n".join(result.warnings))
        else:
            self.lbl_status.setText("完成")
        self.btn_copy.setEnabled(bool(result.rows))

    def _on_failed(self, message: str) -> None:
        self._set_running(False)
        self.progress.setVisible(False)
        self.lbl_summary.setText("批量比较失败")
        QMessageBox.critical(self, "批量比较失败", message)

    def _on_cancelled(self) -> None:
        self._set_running(False)
        self.progress.setVisible(False)
        self.lbl_summary.setText("批量比较已取消")

    def _on_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _set_running(self, running: bool) -> None:
        self.progress.setVisible(running)
        self.btn_start.setEnabled(not running)
        self.btn_add.setEnabled(not running)
        self.btn_remove.setEnabled(not running)
        self.btn_clear.setEnabled(not running)
        self.file_list.setEnabled(not running)
        self.btn_cancel.setVisible(running)
        self.btn_cancel.setEnabled(running)

    # ------------------------------------------------------------------ table
    @staticmethod
    def _short(text: str, limit: int = 220) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ⏎ ")
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _populate(self, result: BatchResult) -> None:
        candidates = result.candidates
        n = len(candidates)
        self.table.setColumnCount(2 + n)
        headers = ["位置", f"基准：{Path(result.baseline).name}"]
        for cand in candidates:
            suffix = f"（{cand.diff_count} 处）" if not cand.error else "（失败）"
            headers.append(f"{cand.name}{suffix}")
        self.table.setHorizontalHeaderLabels(headers)
        for col, header in enumerate(headers):
            item = self.table.horizontalHeaderItem(col)
            if item is not None:
                if col == 0:
                    item.setToolTip("差异所在位置")
                elif col == 1:
                    item.setToolTip(result.baseline)
                else:
                    item.setToolTip(candidates[col - 2].path)
        self.table.setRowCount(len(result.rows))
        for r, row in enumerate(result.rows):
            uncertain = row.severity == Severity.UNCERTAIN
            strong = "#FFF4CE" if uncertain else "#FFD7D5"
            soft = "#FFFBF0" if uncertain else "#FFF5F5"
            base = QTableWidgetItem(self._short(row.location))
            base.setToolTip(row.location)
            base.setBackground(QColor(soft))
            self.table.setItem(r, 0, base)
            b = QTableWidgetItem(self._short(row.baseline))
            b.setToolTip(row.baseline)
            b.setBackground(QColor(strong))
            self.table.setItem(r, 1, b)
            for c in range(n):
                value = row.values[c] if c < len(row.values) else "—"
                it = QTableWidgetItem(self._short(value))
                it.setToolTip(value)
                if row.differs[c]:
                    it.setBackground(QColor(strong))
                    it.setForeground(QBrush(QColor("#A11212" if not uncertain else "#8A3B00")))
                self.table.setItem(r, 2 + c, it)
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if item is not None:
                    item.setToolTip(item.toolTip() or item.text())
        self._size_columns()

    def _size_columns(self) -> None:
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        available = max(600, self.table.viewport().width())
        n = max(1, self.table.columnCount() - 1)
        location_width = 150
        candidate_width = max(190, int((available - location_width - 20) / n))
        self.table.setColumnWidth(0, location_width)
        for c in range(1, self.table.columnCount()):
            self.table.setColumnWidth(c, candidate_width)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.table.columnCount() > 1:
            self._size_columns()

    def _copy_table(self) -> None:
        if self.table.rowCount() == 0:
            return
        # 表头 + 每行 TSV
        header = "\t".join(
            (self.table.horizontalHeaderItem(c).text() if self.table.horizontalHeaderItem(c) else "")
            for c in range(self.table.columnCount())
        )
        out = [header]
        for r in range(self.table.rowCount()):
            out.append("\t".join(
                (self.table.item(r, c).text() if self.table.item(r, c) else "")
                for c in range(self.table.columnCount())
            ))
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText("\n".join(out))
        self.lbl_status.setText("差异表已复制到剪贴板（TSV）")

    # ------------------------------------------------------------------ close
    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(8000)
            if self._worker.isRunning():
                self._worker.wait()
        super().closeEvent(event)
