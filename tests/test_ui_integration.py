"""Lead 负责的主窗口集成测试：CSV、Excel、图片 OCR 与交互。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest


def _wait(app, predicate, timeout=30.0):
    start = time.time()
    while time.time() - start < timeout:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _make_xlsx(path: Path, version: str, reverse: bool, only_left: bool) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "软件版本"
    ws["A1"] = "装置"
    ws["B1"] = "版本"
    ws["A2"] = "装置一"
    ws["B2"] = version
    ws2 = wb.create_sheet("保护定值")
    ws2["A1"] = "定值项"
    ws2["B1"] = "值"
    ws2["A2"] = "过流 I 段"
    ws2["B2"] = 1.50
    ws2["A3"] = "过流 II 段"
    ws2["B3"] = 2.00
    if only_left:
        ws2["B3"] = 2.50
        wb.create_sheet("仅左侧")["A1"] = "left only"
    if reverse:
        wb.move_sheet("保护定值", offset=-1)
    wb.save(path)


@pytest.mark.gui
def test_csv_table_text_toggle(qapp, tmp_path: Path):
    from engineerdiff.ui.main_window import MainWindow

    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text('设备,数值,备注\n"装置,一",1.50,"含,逗号"\n装置二,2.00,"多行\n字段"\n', encoding="utf-8")
    b.write_text('设备,数值,备注\n"装置,一",1.80,"含,逗号"\n装置二,2.00,"多行\n字段"\n', encoding="utf-8")
    window = MainWindow()
    window.show()
    window._set_file("left", str(a))
    window._set_file("right", str(b))
    window._start_compare()
    assert _wait(qapp, lambda: not window._busy)
    qapp.processEvents()
    assert window._mode.value == "csv"
    assert window._view == "table"
    assert len(window._diffs) == 1
    assert window._sheet_sides["left"].grid().sheet().cell(2, 2).display == "多行\n字段"
    assert window._result.csv.left.row_heights[2] >= 40
    window.combo_view.setCurrentIndex(1)  # 文本视图
    qapp.processEvents()
    assert window._view == "text"
    assert window._diffs and window._diffs[0].id.startswith("text:")
    window.combo_view.setCurrentIndex(0)
    qapp.processEvents()
    assert window._diffs[0].group == "cell"
    window.close()


@pytest.mark.gui
def test_excel_sheet_sync_and_placeholder(qapp, tmp_path: Path):
    from engineerdiff.ui.main_window import MainWindow

    a = tmp_path / "a.xlsx"
    b = tmp_path / "b.xlsx"
    _make_xlsx(a, "V1.2.3", False, True)
    _make_xlsx(b, "V1.2.4", True, False)
    window = MainWindow()
    window.show()
    window._set_file("left", str(a))
    window._set_file("right", str(b))
    window._start_compare()
    assert _wait(qapp, lambda: not window._busy)
    qapp.processEvents()
    assert window._mode.value == "excel"
    # Sheet 顺序不同但按名称配对；内容相同的工作表不标红
    assert window._result.workbook.sheet_by_name("保护定值").status.value == "different"
    assert window._result.workbook.sheet_by_name("软件版本").status.value == "different"
    # 关闭 Sheet 同步后，切换一侧不应带动另一侧
    assert window.cb_sheet_sync.isVisible()
    window.cb_sheet_sync.setChecked(False)
    window._sheet_sides["left"].show_sheet("参数表")
    window._sheet_sides["right"].show_sheet("软件版本")
    window._on_sheet_selected("right", "软件版本")
    qapp.processEvents()
    assert window._sheet_sides["left"].current_sheet() == "参数表"
    # 打开同步，点击右侧“保护定值”，左侧同步
    window.cb_sheet_sync.setChecked(True)
    window._on_sheet_selected("right", "保护定值")
    qapp.processEvents()
    assert window._sheet_sides["left"].current_sheet() == "保护定值"
    # 表格缩放控件（Excel 必须支持缩放）
    assert window.sheet_tools.isVisible()
    before = window._sheet_sides["left"].grid().zoom()
    window._sheet_zoom_action(1)
    qapp.processEvents()
    assert window._sheet_sides["left"].grid().zoom() > before
    assert window._sheet_sides["right"].grid().zoom() == pytest.approx(
        window._sheet_sides["left"].grid().zoom(), rel=1e-6
    )
    window._sheet_zoom_action(0)
    qapp.processEvents()
    assert window._sheet_sides["left"].grid().zoom() == pytest.approx(1.0)
    # 导航到仅左侧存在的 Sheet，右侧显示占位
    for i, diff in enumerate(window._diffs):
        if diff.kind.value == "only_left":
            window._show_diff(i)
            qapp.processEvents()
            assert window._sheet_sides["right"].is_placeholder_visible()
            assert window._sheet_sides["right"].placeholder_text() == "无对应工作表"
            break
    else:
        pytest.fail("未检出仅左侧工作表差异")
    window.close()


@pytest.mark.gui
@pytest.mark.ocr
def test_image_ocr_main_window(qapp, tmp_path: Path):
    from engineerdiff.self_test import _make_ocr_images
    from engineerdiff.ui.main_window import MainWindow

    a, b = _make_ocr_images(tmp_path)
    window = MainWindow()
    window.resize(1280, 820)
    window.show()
    window._set_file("left", str(a))
    window._set_file("right", str(b))
    window._start_compare()
    assert _wait(qapp, lambda: not window._busy, timeout=120)
    qapp.processEvents()
    assert window._mode.value == "image"
    assert len(window._diffs) >= 1
    left = window._image_panes["left"]
    right = window._image_panes["right"]
    # 适应窗口不能显示成缩略图
    assert left.zoom() > 0.2, f"左侧 zoom={left.zoom()}，可能退化为缩略图"
    assert right.zoom() > 0.2
    # 初次显示先让两侧各自“适应窗口”，之后才启用同步缩放
    assert _wait(qapp, lambda: window._image_sync_ready, timeout=3)
    before = left.zoom()
    left.zoom_in()
    qapp.processEvents()
    # 同步缩放开启时另一侧应跟随到与操作侧相同比例
    assert left.zoom() > before
    assert right.zoom() == pytest.approx(left.zoom(), rel=1e-3)
    # 差异高亮坐标在原图范围内
    d = window._diffs[0]
    for loc, page in ((d.left, left.page()), (d.right, right.page())):
        if loc is not None and loc.bbox is not None:
            assert 0 <= loc.bbox.x < page.width
            assert 0 <= loc.bbox.y < page.height
    window.close()


@pytest.mark.gui
def test_drag_drop_text_auto_compares(qapp, tmp_path: Path):
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication

    from engineerdiff.ui.main_window import MainWindow

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("软件版本 V1.2.3\n", encoding="utf-8")
    b.write_text("软件版本 V1.2.4\n", encoding="utf-8")
    window = MainWindow()
    window.resize(1100, 700)
    window.show()
    window._set_file("left", str(a), auto_compare=True)
    qapp.processEvents()
    assert not window._busy
    # 拖 B 到右侧空区域，松手后自动比较
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(b))])
    enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(window.right_pane, enter)
    assert enter.isAccepted()
    drop = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(window.right_pane, drop)
    qapp.processEvents()
    assert window._right_path == str(b)
    assert window._busy
    assert _wait(qapp, lambda: not window._busy)
    assert window._result is not None and len(window._diffs) == 1
    window.close()


@pytest.mark.gui
def test_drop_on_image_content_and_preview(qapp, tmp_path: Path, monkeypatch):
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication

    from engineerdiff.self_test import _make_ocr_images
    from engineerdiff.ui.main_window import MainWindow

    a, b = _make_ocr_images(tmp_path)
    window = MainWindow()
    window.resize(1100, 700)
    window.show()
    window._set_file("left", str(a), auto_compare=True)
    qapp.processEvents()
    # 单张图片也应立即显示预览，而不是空白
    assert "left" in window._preview_panes
    assert window._preview_panes["left"].image_size().width() > 0
    window._set_file("right", str(a), auto_compare=False)
    qapp.processEvents()
    assert "right" in window._preview_panes
    started = []
    monkeypatch.setattr(window, "_start_compare", lambda: started.append(True))
    target = window._preview_panes["left"].graphics_view().viewport()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(b))])
    enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(target, enter)
    assert enter.isAccepted(), "图片视图没有把拖拽事件转发给侧栏"
    drop = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(target, drop)
    qapp.processEvents()
    assert window._left_path == str(b)
    assert started == [True], "图片内容上的拖拽没有触发自动比较"
    window.close()


@pytest.mark.gui
def test_image_mouse_wheel_zooms_directly(qapp, tmp_path: Path):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from engineerdiff.self_test import _make_ocr_images
    from engineerdiff.ui.image_view import ImagePane

    a, _b = _make_ocr_images(tmp_path)
    pane = ImagePane()
    pane.resize(700, 500)
    pane.set_preview(str(a))
    pane.show()
    qapp.processEvents()
    before = pane.zoom()
    wheel = QWheelEvent(
        QPointF(200, 200), QPointF(200, 200), QPoint(0, 0), QPoint(0, 120),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )
    QApplication.sendEvent(pane.graphics_view().viewport(), wheel)
    qapp.processEvents()
    assert pane.zoom() > before * 1.05
    pane.close()
