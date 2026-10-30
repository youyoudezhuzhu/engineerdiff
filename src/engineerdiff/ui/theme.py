"""EngineerDiff 视觉规范（浅色、Windows 工具软件风格）。"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

# 差异颜色：红=确定差异，橙=需人工复核
RED = "#C62828"
RED_BG = "#FFD9D5"
RED_BG_HOVER = "#FFC7C2"
RED_TEXT = "#A11212"
ORANGE = "#C15C00"
ORANGE_BG = "#FFE3BD"
ORANGE_TEXT = "#8A3B00"
ADDED_BG = "#FFF3F1"
REMOVED_BG = "#FFF3F1"
CURRENT_BLUE = "#2563EB"
CURRENT_BG = "#EDF3FF"
GUTTER_BG = "#F5F7FA"
GUTTER_TEXT = "#77808F"
TEXT = "#1F2328"
BORDER = "#D8DEE6"
PLACEHOLDER_BG = "#F1F3F6"
PANEL_BG = "#FFFFFF"
APP_BG = "#EEF1F5"
ACCENT = "#2563EB"

DIFF_CONFIRMED_BG = QColor(RED_BG)
DIFF_UNCERTAIN_BG = QColor(ORANGE_BG)
DIFF_CONFIRMED_BORDER = QColor(RED)
DIFF_UNCERTAIN_BORDER = QColor(ORANGE)

FONT_FAMILIES = [
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "WenQuanYi Micro Hei",
    "Segoe UI",
]

MONO_FAMILIES = [
    "Cascadia Mono",
    "Consolas",
    "Noto Sans Mono CJK SC",
    "DejaVu Sans Mono",
    "Courier New",
]


def ui_font(point_size: float = 9.5) -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPointSizeF(point_size)
    return f


def mono_font(point_size: float = 10.0) -> QFont:
    f = QFont()
    f.setFamilies(MONO_FAMILIES)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFixedPitch(True)
    f.setPointSizeF(point_size)
    return f


def install_test_font(path: str) -> str:
    """仅供开发/截图验证使用。"""
    fid = QFontDatabase.addApplicationFont(path)
    return QFontDatabase.applicationFontFamilies(fid)[0] if fid >= 0 else ""


APP_STYLESHEET = """
QMainWindow, QDialog { background: #EEF1F5; }
QWidget { color: #1F2328; }
QToolTip {
    color: #1F2328; background: #FFFFFF; border: 1px solid #C9D1DC;
    padding: 4px 6px;
}
QGroupBox {
    border: 1px solid #D8DEE6; border-radius: 6px; margin-top: 10px;
    background: #FFFFFF; padding-top: 6px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #3A4553;
}
QPushButton {
    background: #FFFFFF; border: 1px solid #C8D0DA; border-radius: 5px;
    padding: 5px 12px; min-height: 18px; color: #1F2328;
}
QPushButton:hover { background: #F3F6FB; border-color: #9AA7B8; }
QPushButton:pressed { background: #E5EBF3; }
QPushButton:disabled { color: #97A0AC; background: #F4F6F8; border-color: #DEE3E9; }
QPushButton#primary {
    background: #2563EB; color: white; border: 1px solid #1D4ED8; font-weight: 600;
    padding: 6px 18px;
}
QPushButton#primary:hover { background: #1D4ED8; }
QPushButton#primary:disabled { background: #9DB8EF; border-color: #9DB8EF; color: #F4F7FF; }
QPushButton#tool {
    padding: 4px 9px; min-height: 16px; background: transparent; border-color: transparent;
}
QPushButton#tool:hover { background: #E9EEF6; border-color: #D2DAE5; }
QLineEdit {
    background: #FFFFFF; border: 1px solid #C8D0DA; border-radius: 5px;
    padding: 5px 8px; selection-background-color: #BFD3FA;
}
QLineEdit:focus { border-color: #2563EB; }
QCheckBox { spacing: 5px; }
QComboBox {
    background: #FFFFFF; border: 1px solid #C8D0DA; border-radius: 5px; padding: 4px 8px;
}
QSpinBox, QDoubleSpinBox {
    background: #FFFFFF; border: 1px solid #C8D0DA; border-radius: 5px;
    padding: 4px 6px; min-height: 18px;
}
QStatusBar { background: #F8FAFC; border-top: 1px solid #D8DEE6; }
QStatusBar QLabel { color: #4B5563; padding: 0 6px; }
QToolBar { background: #FFFFFF; border: none; spacing: 4px; }
QSplitter::handle { background: #D8DEE6; width: 4px; }
QSplitter::handle:hover { background: #9DB8EF; }
QTabBar::tab {
    background: #E7EBF1; color: #4B5563; border: 1px solid #D3DAE3;
    border-bottom: none; padding: 5px 14px; margin-right: 2px;
    border-top-left-radius: 5px; border-top-right-radius: 5px;
}
QTabBar::tab:selected { background: #FFFFFF; color: #1F2328; border-bottom: 2px solid #FFFFFF; }
QTabBar::tab:hover { background: #F1F4F9; }
QTabWidget::pane { border: 1px solid #D8DEE6; background: #FFFFFF; }
QMenu { background: #FFFFFF; border: 1px solid #D8DEE6; padding: 4px; }
QMenu::item { padding: 5px 26px 5px 18px; border-radius: 4px; }
QMenu::item:selected { background: #E8F0FE; }
QScrollBar:vertical { background: #F5F7FA; width: 13px; margin: 0; }
QScrollBar::handle:vertical { background: #C4CCD6; min-height: 28px; border-radius: 5px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: #A7B2C0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: #F5F7FA; height: 13px; margin: 0; }
QScrollBar::handle:horizontal { background: #C4CCD6; min-width: 28px; border-radius: 5px; margin: 2px; }
QScrollBar::handle:horizontal:hover { background: #A7B2C0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QProgressBar {
    background: #E9EDF2; border: none; border-radius: 3px; height: 6px;
    text-align: center; color: transparent;
}
QProgressBar::chunk { background: #2563EB; border-radius: 3px; }
"""
