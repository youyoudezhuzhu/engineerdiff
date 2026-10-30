"""OCR 校正对话框。

功能：
- 查看左右两侧 OCR 结果（文本、置信度、原图坐标）；
- 直接编辑识别文本，重新比较时作为 ``ImageOptions.text_overrides`` 生效；
- 建立/解除人工左右对应，作为 ``ImageOptions.manual_pairs`` 生效；
- “重新比较”返回修正后的 ``ImageOptions``，由 MainWindow 重新运行比较。

校正只影响当前比较，不修改原文件。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import ImageComparison, ImageOptions, OcrPage

_LOW_CONF_BG = QColor(255, 226, 184)
_EDITED_BG = QColor(255, 249, 196)


def _options_from_comparison(comparison: ImageComparison | None) -> ImageOptions:
    """从当前比较结果的 settings 还原 ImageOptions。"""
    if comparison is None:
        return ImageOptions()
    settings: dict[str, Any] = comparison.settings or {}
    options = ImageOptions()
    try:
        options.confidence_threshold = float(settings.get("confidence_threshold", options.confidence_threshold))
        options.match_threshold = float(settings.get("match_threshold", options.match_threshold))
        options.show_boxes = bool(settings.get("show_boxes", options.show_boxes))
    except (TypeError, ValueError):
        pass
    manual = settings.get("manual_pairs") or []
    pairs: list[tuple[int, int]] = []
    for pair in manual:
        try:
            if len(pair) >= 2:
                pairs.append((int(pair[0]), int(pair[1])))
        except (TypeError, ValueError):
            continue
    options.manual_pairs = pairs
    overrides: dict[str, dict[int, str]] = {"left": {}, "right": {}}
    raw_overrides = settings.get("text_overrides") or {}
    if isinstance(raw_overrides, dict):
        for side in ("left", "right"):
            side_data = raw_overrides.get(side) or {}
            if isinstance(side_data, dict):
                for box_id, text in side_data.items():
                    try:
                        overrides[side][int(box_id)] = str(text)
                    except (TypeError, ValueError):
                        continue
    options.text_overrides = overrides
    return options


def _clone_options(options: ImageOptions) -> ImageOptions:
    return ImageOptions(
        confidence_threshold=options.confidence_threshold,
        match_threshold=options.match_threshold,
        show_boxes=options.show_boxes,
        manual_pairs=[(int(a), int(b)) for a, b in options.manual_pairs],
        text_overrides={side: dict(values) for side, values in options.text_overrides.items()},
    )


class OcrCorrectionDialog(QDialog):
    """左右 OCR 文本查看/编辑 + 人工对应 + 重新比较。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        comparison: ImageComparison | None = None,
        ocr_service: Any = None,
        options: ImageOptions | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("OCR 结果校正 - EngineerDiff")
        self.setModal(True)
        self.resize(1120, 700)
        self._comparison = comparison
        self._ocr_service = ocr_service
        self._base_options = _clone_options(options) if options is not None else _options_from_comparison(comparison)
        self._manual_pairs: list[tuple[int, int]] = [
            (int(a), int(b)) for a, b in self._base_options.manual_pairs
        ]
        self._current_texts: dict[str, dict[int, str]] = {"left": {}, "right": {}}
        self._raw_texts: dict[str, dict[int, str]] = {"left": {}, "right": {}}
        self._box_order: dict[str, list[int]] = {"left": [], "right": []}
        self._populating = False

        self.left_table = QTableWidget(0, 4)
        self.right_table = QTableWidget(0, 4)
        self.pair_table = QTableWidget(0, 4)
        self._tables = {"left": self.left_table, "right": self.right_table}

        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QLabel("OCR 校正：可修改识别文本、建立/解除左右对应，然后重新比较")
        font = title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        title.setFont(font)
        root.addWidget(title)

        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet("color:#37474F;")
        root.addWidget(self._summary_label)

        self._engine_label = QLabel("")
        self._engine_label.setWordWrap(True)
        self._engine_label.setStyleSheet("color:#546E7A; font-size:11px;")
        root.addWidget(self._engine_label)

        tables_row = QHBoxLayout()
        tables_row.setSpacing(8)
        for side, label in (("left", "左侧 OCR 结果"), ("right", "右侧 OCR 结果")):
            group = QGroupBox(label)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(6, 6, 6, 6)
            table = self._tables[side]
            self._setup_box_table(table)
            group_layout.addWidget(table)
            tables_row.addWidget(group, 1)
        root.addLayout(tables_row, 1)

        pairs_group = QGroupBox("人工对应（覆盖自动匹配，一对一）")
        pairs_layout = QGridLayout(pairs_group)
        pairs_layout.setContentsMargins(6, 6, 6, 6)
        self._setup_pair_table(self.pair_table)
        pairs_layout.addWidget(self.pair_table, 0, 0, 1, 4)
        self._add_button = QPushButton("建立对应（选中左、右各一行）")
        self._add_button.clicked.connect(self.add_manual_pair)
        self._remove_button = QPushButton("解除选中对应")
        self._remove_button.clicked.connect(self.remove_manual_pair)
        self._clear_button = QPushButton("清空人工对应")
        self._clear_button.clicked.connect(self.clear_manual_pairs)
        pairs_layout.addWidget(self._add_button, 1, 0)
        pairs_layout.addWidget(self._remove_button, 1, 1)
        pairs_layout.addWidget(self._clear_button, 1, 2)
        self._hint_label = QLabel("")
        self._hint_label.setStyleSheet("color:#C62828;")
        pairs_layout.addWidget(self._hint_label, 1, 3)
        root.addWidget(pairs_group, 0)

        buttons = QDialogButtonBox()
        self._recompare_button = buttons.addButton("重新比较", QDialogButtonBox.AcceptRole)
        self._cancel_button = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        self._recompare_button.setDefault(True)
        self._recompare_button.clicked.connect(self.accept)
        self._cancel_button.clicked.connect(self.reject)
        root.addWidget(buttons)

    def _setup_box_table(self, table: QTableWidget) -> None:
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["ID", "文本（可编辑）", "置信度", "坐标（原图像素）"])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked
        )
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

    def _setup_pair_table(self, table: QTableWidget) -> None:
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["左 ID", "左文本", "右 ID", "右文本"])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        table.setMaximumHeight(150)

    # ------------------------------------------------------------------ 数据填充
    def _populate(self) -> None:
        self._populating = True
        try:
            if self._comparison is not None:
                self._fill_box_table("left", self._comparison.left)
                self._fill_box_table("right", self._comparison.right)
            self._refresh_pairs_table()
            self._refresh_labels()
        finally:
            self._populating = False

    def _fill_box_table(self, side: str, page: OcrPage | None) -> None:
        table = self._tables[side]
        table.setRowCount(0)
        self._current_texts[side] = {}
        self._raw_texts[side] = {}
        self._box_order[side] = []
        if page is None:
            return
        threshold = float(self._base_options.confidence_threshold)
        for box in page.boxes:
            row = table.rowCount()
            table.insertRow(row)
            self._box_order[side].append(box.id)
            current = box.text
            raw = box.raw_text if box.overridden and box.raw_text is not None else box.text
            self._current_texts[side][box.id] = current
            self._raw_texts[side][box.id] = raw

            id_item = QTableWidgetItem(str(box.id))
            id_item.setData(Qt.UserRole, box.id)
            id_item.setFlags(id_item.flags() & ~Qt.ItemIsEditable)
            id_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 0, id_item)

            text_item = QTableWidgetItem(current)
            text_item.setData(Qt.UserRole, box.id)
            table.setItem(row, 1, text_item)

            conf_item = QTableWidgetItem(f"{box.confidence:.3f}")
            conf_item.setFlags(conf_item.flags() & ~Qt.ItemIsEditable)
            conf_item.setTextAlignment(Qt.AlignCenter)
            if box.confidence < threshold:
                conf_item.setBackground(QBrush(_LOW_CONF_BG))
                conf_item.setToolTip(f"低于阈值 {threshold:.2f}：匹配结果将标记为橙色待复核")
            table.setItem(row, 2, conf_item)

            bbox = box.bbox
            coord_item = QTableWidgetItem(
                f"x={bbox.x:.0f}, y={bbox.y:.0f}, {bbox.w:.0f}×{bbox.h:.0f}"
            )
            coord_item.setFlags(coord_item.flags() & ~Qt.ItemIsEditable)
            bbox_text = f"原始 OCR 文本：{raw}" if box.overridden else ""
            coord_item.setToolTip(bbox_text)
            table.setItem(row, 3, coord_item)
            if box.overridden:
                text_item.setToolTip(f"当前为人工作业修正；原始 OCR：{raw}")
                text_item.setBackground(QBrush(_EDITED_BG))

    def _refresh_labels(self) -> None:
        if self._comparison is not None:
            transform = self._comparison.transform or {}
            auto = int(transform.get("auto_matched_count", 0) or 0)
            only_left = len(transform.get("only_left") or [])
            only_right = len(transform.get("only_right") or [])
            summary = (
                f"差异 {len(self._comparison.diffs)} 处；自动配对 {auto} 对；"
                f"仅左侧文字框 {only_left} 个；仅右侧文字框 {only_right} 个；"
                f"人工对应 {len(self._manual_pairs)} 对。"
            )
            if self._comparison.warnings:
                summary += " 警告：" + "；".join(self._comparison.warnings[:3])
        else:
            summary = "没有可校正的比较结果。"
        self._summary_label.setText(summary)
        self._engine_label.setText(self._engine_info_text())

    def _engine_info_text(self) -> str:
        if self._ocr_service is None:
            return "OCR 服务：未提供"
        try:
            info = self._ocr_service.model_info()
        except Exception:
            return "OCR 服务：信息不可用"
        if not isinstance(info, dict):
            return "OCR 服务：信息格式异常"
        models = info.get("models") or []
        return (
            f"OCR 引擎：{info.get('engine', 'RapidOCR')} {info.get('engine_version', '')} · "
            f"{info.get('backend', '')} · {info.get('device', 'CPU')} · 离线模型 {len(models)} 个 · "
            f"缓存：{info.get('cache_dir', '')}"
        )

    def _refresh_pairs_table(self) -> None:
        self.pair_table.setRowCount(0)
        left_texts = self._box_texts(self._comparison.left if self._comparison else None)
        right_texts = self._box_texts(self._comparison.right if self._comparison else None)
        for left_id, right_id in self._manual_pairs:
            row = self.pair_table.rowCount()
            self.pair_table.insertRow(row)
            values = [
                str(left_id),
                left_texts.get(left_id, "?"),
                str(right_id),
                right_texts.get(right_id, "?"),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.pair_table.setItem(row, col, item)
        self._remove_button.setEnabled(bool(self._manual_pairs))
        self._clear_button.setEnabled(bool(self._manual_pairs))
        self._refresh_labels()

    @staticmethod
    def _box_texts(page: OcrPage | None) -> dict[int, str]:
        if page is None:
            return {}
        return {box.id: box.text for box in page.boxes}

    # ------------------------------------------------------------------ 人工对应
    def _selected_box_id(self, side: str) -> int | None:
        table = self._tables[side]
        row = table.currentRow()
        if row < 0 or row >= len(self._box_order[side]):
            return None
        return self._box_order[side][row]

    def add_manual_pair(self) -> bool:
        left_id = self._selected_box_id("left")
        right_id = self._selected_box_id("right")
        if left_id is None or right_id is None:
            self._hint_label.setText("请先在左右表格各选中一行文字框")
            return False
        self._manual_pairs = [
            (a, b) for a, b in self._manual_pairs if a != left_id and b != right_id
        ]
        self._manual_pairs.append((int(left_id), int(right_id)))
        self._hint_label.setText(f"已建立对应：左 {left_id} ↔ 右 {right_id}")
        self._refresh_pairs_table()
        return True

    def remove_manual_pair(self) -> bool:
        row = self.pair_table.currentRow()
        if row < 0 or row >= len(self._manual_pairs):
            self._hint_label.setText("请先选中一条人工对应")
            return False
        left_id, right_id = self._manual_pairs.pop(row)
        self._hint_label.setText(f"已解除对应：左 {left_id} ↔ 右 {right_id}")
        self._refresh_pairs_table()
        return True

    def clear_manual_pairs(self) -> None:
        self._manual_pairs.clear()
        self._hint_label.setText("已清空人工对应")
        self._refresh_pairs_table()

    # ------------------------------------------------------------------ 结果
    def manual_pairs(self) -> list[tuple[int, int]]:
        return list(self._manual_pairs)

    def corrected_options(self) -> ImageOptions:
        """返回修正后的 ``ImageOptions``（文本修正 + 人工对应）。"""
        base = _clone_options(self._base_options)
        overrides: dict[str, dict[int, str]] = {
            "left": dict(base.text_overrides.get("left", {})),
            "right": dict(base.text_overrides.get("right", {})),
        }
        for side in ("left", "right"):
            table = self._tables[side]
            for row in range(table.rowCount()):
                item = table.item(row, 1)
                id_item = table.item(row, 0)
                if item is None or id_item is None:
                    continue
                try:
                    box_id = int(id_item.data(Qt.UserRole))
                except (TypeError, ValueError):
                    continue
                edited = item.text()
                current = self._current_texts[side].get(box_id, edited)
                raw = self._raw_texts[side].get(box_id, current)
                if edited == current:
                    continue
                if edited == raw:
                    overrides[side].pop(box_id, None)
                else:
                    overrides[side][box_id] = edited
        base.text_overrides = overrides
        base.manual_pairs = [(int(a), int(b)) for a, b in self._manual_pairs]
        return base

    # 兼容命名
    def result_options(self) -> ImageOptions:
        return self.corrected_options()

    def comparison(self) -> ImageComparison | None:
        return self._comparison


__all__ = ["OcrCorrectionDialog"]
