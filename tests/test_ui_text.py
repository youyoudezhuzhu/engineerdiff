from __future__ import annotations

import time
from pathlib import Path

import pytest

from engineerdiff.models import TextCompareOptions
from engineerdiff.textdiff.engine import compare_texts
from engineerdiff.ui.text_view import TextView


def _wait_until(app, predicate, timeout=20.0):
    start = time.time()
    while time.time() - start < timeout:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_text_view_only_diffs_visible_rows(qapp):
    cmp = compare_texts("a\nb\nc\nd\ne\n", "a\nb\nX\nd\ne\n")
    view = TextView()
    view.resize(500, 300)
    view.set_side(cmp.left)
    assert view.visible_row_count() == 5
    view.set_only_diffs(True)
    # 差异在第 3 行，附带前后各一行上下文
    assert view.visible_row_count() == 3
    view.show()


def test_text_view_reveal_and_scroll(qapp):
    left = "\n".join(f"line {i}" for i in range(500))
    right = left.replace("line 400", "line 400 changed")
    cmp = compare_texts(left, right)
    view = TextView()
    view.resize(500, 300)
    view.set_side(cmp.left)
    view.show()
    qapp.processEvents()
    view.reveal(cmp.diffs[0], "left")
    qapp.processEvents()
    assert view.verticalScrollBar().value() > 0


def test_main_window_text_compare(qapp, tmp_path: Path):
    from engineerdiff.ui.main_window import MainWindow

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("软件版本 V1.2.3\n保护定值 1.50\n", encoding="utf-8")
    b.write_text("软件版本 V1.2.4\n保护定值 1.50\n", encoding="utf-8")
    window = MainWindow()
    window.show()
    window._set_file("left", str(a))
    window._set_file("right", str(b))
    window._start_compare()
    assert _wait_until(qapp, lambda: not window._busy)
    qapp.processEvents()
    assert window._result is not None
    assert len(window._diffs) == 1
    assert window.lbl_index.text() == "1 / 1"
    assert window._text_views["left"].side().lines[0].spans[0].start == 10
    window.close()


def test_main_window_incompatible_files_message(qapp, tmp_path: Path, monkeypatch):
    from engineerdiff.ui import main_window as mw

    a = tmp_path / "a.xlsx"
    a.write_bytes(b"not really xlsx")
    b = tmp_path / "b.txt"
    b.write_text("x", encoding="utf-8")
    window = mw.MainWindow()
    messages = []
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *args, **kwargs: messages.append(args[2]))
    window._set_file("left", str(a))
    window._set_file("right", str(b))
    window._start_compare()
    qapp.processEvents()
    assert messages and "不能比较" in messages[0]
    window.close()


def test_settings_dialog_roundtrip(qapp):
    from engineerdiff.models import AppSettings
    from engineerdiff.ui.settings_dialog import SettingsDialog

    s = AppSettings()
    s.text.ignore_case = True
    dlg = SettingsDialog(s)
    assert dlg.cb_case.isChecked()
    dlg.cb_line_endings.setChecked(True)
    dlg.cb_all_space.setChecked(True)
    dlg.spin_tolerance.setValue(0.001)
    dlg.cb_sync_sheets.setChecked(False)
    out = dlg.result_settings()
    assert out.text.ignore_line_endings is True
    assert out.text.ignore_all_space is True
    assert out.spreadsheet.numeric_tolerance == pytest.approx(0.001)
    assert out.sync_sheets is False
    dlg.close()
