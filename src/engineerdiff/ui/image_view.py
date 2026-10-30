"""图片差异渲染控件。

``ImagePane`` 使用 ``QGraphicsView`` 显示原图，并在场景坐标（=原图像素坐标）叠加
半透明红/橙色块和边框，因此缩放/平移时覆盖层始终与文字对齐；原始图片文件不会被修改。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..models import DiffItem, ImageComparison, OcrPage

#: 覆盖层颜色
COLOR_CONFIRMED = QColor(198, 40, 40)  # 红：确定差异
COLOR_UNCERTAIN = QColor(230, 126, 34)  # 橙：不确定/需复核
COLOR_OCR_BOX = QColor(21, 101, 192)  # 蓝：OCR 文字框
COLOR_BG = QColor(243, 243, 243)
COLOR_PLACEHOLDER = QColor(240, 240, 240)
COLOR_PLACEHOLDER_TEXT = QColor(120, 120, 120)

MIN_ZOOM = 0.02
MAX_ZOOM = 8.0


class _GraphicsView(QGraphicsView):
    """内部 QGraphicsView：鼠标滚轮直接缩放，Shift+滚轮横向滚动，按住左键拖动。"""

    ctrl_wheel = Signal(float)

    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setFrameShape(QFrame.NoFrame)
        self.setBackgroundBrush(QBrush(COLOR_BG))
        self.setAlignment(Qt.AlignCenter)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        delta = event.angleDelta().y()
        if delta:
            if event.modifiers() & Qt.ShiftModifier:
                # Shift+滚轮：横向平移，保留大图查看习惯
                bar = self.horizontalScrollBar()
                bar.setValue(bar.value() - delta)
            else:
                # Fluent/常见看图软件行为：鼠标滚轮直接缩放（无需 Ctrl）。
                # 每 120 单位一格，按比例缩放；Ctrl 仍然有效，便于精细操作。
                steps = delta / 120.0
                factor = max(0.5, min(2.0, 1.0 + 0.15 * steps))
                self.ctrl_wheel.emit(factor)
            event.accept()
            return
        super().wheelEvent(event)


class ImagePane(QWidget):
    """单侧图片显示 + 差异覆盖层。

    - ``set_comparison`` 后默认适应窗口；
    - 场景坐标即原图像素坐标，可调用 ``graphics_view()`` 做像素级验证；
    - ``zoom_changed`` / ``scroll_changed`` 供 MainWindow 做同步，是否真正同步由
      MainWindow 通过 ``set_sync_zoom`` 开关决定。
    """

    zoom_changed = Signal(float)
    scroll_changed = Signal(float, float)  # 垂直比例, 水平比例

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._page: OcrPage | None = None
        self._comparison: ImageComparison | None = None
        self._side = "left"
        self._show_boxes = False
        self._pixmap: QPixmap | None = None
        self._overlay_items: list[QGraphicsRectItem | QGraphicsSimpleTextItem] = []
        self._ocr_box_items: list[QGraphicsRectItem | QGraphicsSimpleTextItem] = []
        self._suppress_scroll = False
        self._sync_zoom = False
        self._fit_pending = True
        self._image_size = QSize(0, 0)

        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(QBrush(COLOR_BG))
        self._view = _GraphicsView(self._scene, self)
        self._view.ctrl_wheel.connect(self._on_ctrl_wheel)
        self._view.horizontalScrollBar().valueChanged.connect(self._emit_scroll)
        self._view.verticalScrollBar().valueChanged.connect(self._emit_scroll)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._view)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(160, 120)
        self._render_placeholder("未加载图片")

    # ------------------------------------------------------------------ 公开接口
    def set_preview(self, image_path: str) -> None:
        """仅显示原图预览（不做 OCR）；用于拖入图片后、OCR 完成前的即时反馈。"""
        self._page = None
        self._comparison = None
        self._show_boxes = False
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self._pixmap = None
            self._image_size = QSize(0, 0)
            self._render_placeholder("无法显示图片")
            return
        self._pixmap = pixmap
        self._image_size = pixmap.size()
        self._rebuild_scene()
        self._fit_pending = True
        self.fit_to_window()
        self.setToolTip(f"{image_path}\n正在准备 OCR…")

    def set_comparison(
        self,
        page: OcrPage,
        comparison: ImageComparison,
        side: str,
        show_boxes: bool = False,
    ) -> None:
        if side not in ("left", "right"):
            raise ValueError(f"side 必须是 'left' 或 'right'，实际为 {side!r}")
        self._page = page
        self._comparison = comparison
        self._side = side
        self._show_boxes = bool(show_boxes)
        self._load_pixmap(page)
        self._rebuild_scene()
        # 控件可能尚未完成布局/显示（viewport 只有几十像素），此时不能立即 fit，
        # 否则会得到 0.07 倍的“缩略图”缩放；统一延迟到 showEvent/首次 resizeEvent。
        self._fit_pending = True
        if self.isVisible() and self._viewport_usable():
            self.fit_to_window()
        else:
            self._schedule_fit()
        warnings = []
        if page.warnings:
            warnings.extend(page.warnings)
        if comparison.warnings:
            warnings.extend(comparison.warnings)
        self.setToolTip("\n".join(warnings))

    def reveal(self, diff: DiffItem) -> bool:
        """将差异位置居中显示；本侧无对应位置时返回 False。"""
        location = diff.left if self._side == "left" else diff.right
        if location is None or location.bbox is None:
            return False
        center = location.bbox.center
        self._view.centerOn(QPointF(center[0], center[1]))
        return True

    def fit_to_window(self) -> None:
        rect = self._scene.sceneRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        if not self.isVisible() or not self._viewport_usable():
            # 布局尚未完成：保持 pending，等 showEvent/resizeEvent 再试
            self._fit_pending = True
            return
        self._view.resetTransform()
        self._view.fitInView(rect, Qt.KeepAspectRatio)
        self._fit_pending = False
        self._emit_zoom()

    def actual_size(self) -> None:
        self._view.resetTransform()
        self._fit_pending = False
        self._emit_zoom()

    def zoom_in(self) -> None:
        self.set_zoom(self.zoom() * 1.25)

    def zoom_out(self) -> None:
        self.set_zoom(self.zoom() / 1.25)

    def zoom(self) -> float:
        return float(self._view.transform().m11())

    def set_zoom(self, zoom: float) -> None:
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, float(zoom)))
        if abs(zoom - self.zoom()) < 1e-9:
            self._fit_pending = False
            return
        center = self._view.mapToScene(self._view.viewport().rect().center())
        self._view.resetTransform()
        self._view.scale(zoom, zoom)
        self._view.centerOn(center)
        self._fit_pending = False
        self._emit_zoom()

    def set_show_boxes(self, show: bool) -> None:
        show = bool(show)
        if show == self._show_boxes:
            return
        self._show_boxes = show
        if self._page is not None:
            self._rebuild_overlays()

    def set_sync_zoom(self, enabled: bool) -> None:
        self._sync_zoom = bool(enabled)

    def sync_zoom_enabled(self) -> bool:
        return self._sync_zoom

    def scroll_ratio(self) -> tuple[float, float]:
        vbar = self._view.verticalScrollBar()
        hbar = self._view.horizontalScrollBar()
        v = vbar.value() / vbar.maximum() if vbar.maximum() > 0 else 0.0
        h = hbar.value() / hbar.maximum() if hbar.maximum() > 0 else 0.0
        return float(v), float(h)

    def set_scroll_ratio(self, v: float, h: float) -> None:
        self._suppress_scroll = True
        try:
            vbar = self._view.verticalScrollBar()
            hbar = self._view.horizontalScrollBar()
            v = max(0.0, min(1.0, float(v)))
            h = max(0.0, min(1.0, float(h)))
            if vbar.maximum() > 0:
                vbar.setValue(round(v * vbar.maximum()))
            if hbar.maximum() > 0:
                hbar.setValue(round(h * hbar.maximum()))
        finally:
            self._suppress_scroll = False

    # ------------------------------------------------------------------ 扩展访问器
    def graphics_view(self) -> QGraphicsView:
        """底层 QGraphicsView（测试/同步滚动使用）。"""
        return self._view

    def scene(self) -> QGraphicsScene:
        return self._scene

    def page(self) -> OcrPage | None:
        return self._page

    def comparison(self) -> ImageComparison | None:
        return self._comparison

    def side(self) -> str:
        return self._side

    def image_size(self) -> QSize:
        return QSize(self._image_size)

    def clear(self) -> None:
        self._page = None
        self._comparison = None
        self._pixmap = None
        self._image_size = QSize(0, 0)
        self._scene.clear()
        self._overlay_items.clear()
        self._ocr_box_items.clear()
        self._render_placeholder("未加载图片")
        self._fit_pending = True

    # ------------------------------------------------------------------ 内部渲染
    def _render_placeholder(self, text: str) -> None:
        self._scene.clear()
        self._overlay_items.clear()
        self._ocr_box_items.clear()
        rect = QRectF(0, 0, 640, 400)
        self._scene.setSceneRect(rect)
        item = self._scene.addSimpleText(text)
        item.setBrush(QBrush(COLOR_PLACEHOLDER_TEXT))
        font = QFont()
        font.setPointSize(12)
        item.setFont(font)
        item.setPos(rect.center() - QPointF(item.boundingRect().width() / 2, item.boundingRect().height() / 2))
        item.setZValue(1)

    def _load_pixmap(self, page: OcrPage) -> None:
        pixmap = QPixmap()
        path = Path(page.path) if page.path else None
        if path is not None and path.is_file():
            pixmap = QPixmap(str(path))
        if pixmap.isNull():
            width = max(1, int(page.width or 640))
            height = max(1, int(page.height or 400))
            pixmap = QPixmap(width, height)
            pixmap.fill(COLOR_PLACEHOLDER)
        self._pixmap = pixmap
        self._image_size = pixmap.size()

    def _rebuild_scene(self) -> None:
        self._scene.clear()
        self._overlay_items.clear()
        self._ocr_box_items.clear()
        if self._pixmap is None:
            self._render_placeholder("未加载图片")
            return
        width = max(1, self._pixmap.width())
        height = max(1, self._pixmap.height())
        self._scene.setSceneRect(QRectF(0, 0, width, height))
        item = QGraphicsPixmapItem(self._pixmap)
        item.setTransformationMode(Qt.SmoothTransformation)
        item.setZValue(0)
        self._scene.addItem(item)
        if (
            self._page is not None
            and not self._page.boxes
            and not any("未执行 OCR" in w or "完全一致" in w for w in self._page.warnings)
        ):
            label = self._scene.addSimpleText("未识别到文字")
            label.setBrush(QBrush(QColor(120, 120, 120, 220)))
            font = QFont()
            font.setPointSize(11)
            label.setFont(font)
            rect = self._scene.sceneRect()
            label.setPos(
                rect.center()
                - QPointF(label.boundingRect().width() / 2, label.boundingRect().height() / 2)
            )
            label.setZValue(20)
        self._rebuild_overlays()

    def _clear_items(self, items: list) -> None:
        for item in items:
            try:
                self._scene.removeItem(item)
            except RuntimeError:
                pass
        items.clear()

    def _rebuild_overlays(self) -> None:
        self._clear_items(self._overlay_items)
        self._clear_items(self._ocr_box_items)
        if self._page is None:
            return
        if self._show_boxes:
            self._build_ocr_boxes()
        if self._comparison is not None:
            for diff in self._comparison.diffs:
                self._build_diff_overlay(diff)

    def _build_diff_overlay(self, diff: DiffItem) -> None:
        location = diff.left if self._side == "left" else diff.right
        if location is None or location.bbox is None:
            return
        color = COLOR_UNCERTAIN if diff.is_uncertain else COLOR_CONFIRMED
        fill = QColor(color)
        fill.setAlpha(70)
        border = QColor(color)
        border.setAlpha(210)
        pen = QPen(border, 1.6)
        pen.setCosmetic(True)
        segments = location.segment_boxes or [location.bbox]
        for box in segments:
            rect = QGraphicsRectItem(QRectF(box.x, box.y, box.w, box.h))
            rect.setBrush(QBrush(fill))
            rect.setPen(pen)
            rect.setZValue(12)
            rect.setToolTip(diff.detail or diff.title)
            self._scene.addItem(rect)
            self._overlay_items.append(rect)
        outline_pen = QPen(border, 1.4)
        outline_pen.setCosmetic(True)
        outline_pen.setStyle(Qt.SolidLine)
        outline = QGraphicsRectItem(
            QRectF(location.bbox.x, location.bbox.y, location.bbox.w, location.bbox.h)
        )
        outline.setBrush(QBrush(Qt.NoBrush))
        outline.setPen(outline_pen)
        outline.setZValue(13)
        outline.setToolTip(diff.detail or diff.title)
        self._scene.addItem(outline)
        self._overlay_items.append(outline)

    def _build_ocr_boxes(self) -> None:
        if self._page is None:
            return
        pen = QPen(QColor(COLOR_OCR_BOX.red(), COLOR_OCR_BOX.green(), COLOR_OCR_BOX.blue(), 190), 1.0)
        pen.setCosmetic(True)
        font = QFont()
        font.setPointSize(7)
        for box in self._page.boxes:
            rect = QGraphicsRectItem(QRectF(box.bbox.x, box.bbox.y, box.bbox.w, box.bbox.h))
            rect.setPen(pen)
            rect.setBrush(QBrush(Qt.NoBrush))
            rect.setZValue(11)
            rect.setToolTip(f"{box.text}（置信度 {box.confidence:.3f}）")
            self._scene.addItem(rect)
            self._ocr_box_items.append(rect)

            label = QGraphicsSimpleTextItem(f"{box.confidence:.2f}")
            label.setFont(font)
            label.setBrush(QBrush(COLOR_OCR_BOX))
            label_y = box.bbox.y - 11
            if label_y < 0:
                label_y = box.bbox.y + 1
            label.setPos(box.bbox.x, label_y)
            label.setZValue(14)
            self._scene.addItem(label)
            self._ocr_box_items.append(label)

    # ------------------------------------------------------------------ 事件/信号
    def _on_ctrl_wheel(self, factor: float) -> None:
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom() * factor))
        if abs(new_zoom - self.zoom()) < 1e-9:
            return
        # AnchorUnderMouse 让滚轮缩放围绕鼠标位置
        self._view.scale(factor, factor)
        self._fit_pending = False
        self._emit_zoom()

    def _viewport_usable(self) -> bool:
        size = self._view.viewport().size()
        return size.width() >= 40 and size.height() >= 40

    def _schedule_fit(self) -> None:
        """在事件循环中重试适应窗口（等布局/layout 完成后 viewport 才有真实尺寸）。"""
        if self._fit_pending:
            QTimer.singleShot(0, self._fit_if_pending)

    def _fit_if_pending(self) -> None:
        if self._fit_pending:
            self.fit_to_window()

    def _emit_zoom(self) -> None:
        self.zoom_changed.emit(self.zoom())

    def _emit_scroll(self, *_args) -> None:
        if self._suppress_scroll:
            return
        v, h = self.scroll_ratio()
        self.scroll_changed.emit(v, h)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._fit_pending:
            self._schedule_fit()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._fit_pending:
            self._schedule_fit()

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        super().wheelEvent(event)


__all__ = ["ImagePane", "MIN_ZOOM", "MAX_ZOOM"]
