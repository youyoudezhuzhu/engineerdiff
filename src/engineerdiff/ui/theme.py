"""EngineerDiff 视觉规范（Windows 11 Fluent Design 风格）。"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

# 差异颜色：红=确定差异，橙=需人工复核（保持高可读性，刻意不随主题变淡）
RED = "#C62828"
RED_BG = "#FFD9D5"
RED_BG_HOVER = "#FFC7C2"
RED_TEXT = "#A11212"
ORANGE = "#C15C00"
ORANGE_BG = "#FFE3BD"
ORANGE_TEXT = "#8A3B00"
ADDED_BG = "#FFF3F1"
REMOVED_BG = "#FFF3F1"

# Fluent 中性色与强调色（Windows 11 默认蓝）
ACCENT = "#0067C0"
ACCENT_HOVER = "#1975C5"
ACCENT_PRESS = "#005A9E"
ACCENT_SOFT = "#E5F1FB"
TEXT = "#1B1B1B"
TEXT_SECONDARY = "#616161"
TEXT_TERTIARY = "#8A8A8A"
BORDER = "#E0E0E0"
BORDER_STRONG = "#C8C8C8"
PANEL_BG = "#FFFFFF"
APP_BG = "#F3F3F3"
GUTTER_BG = "#FAFAFA"
GUTTER_TEXT = "#8A8A8A"
PLACEHOLDER_BG = "#F7F7F7"
CURRENT_BLUE = ACCENT
CURRENT_BG = ACCENT_SOFT
SUCCESS = "#0F7B0F"
WARNING = "#9D5D00"

DIFF_CONFIRMED_BG = QColor(RED_BG)
DIFF_UNCERTAIN_BG = QColor(ORANGE_BG)
DIFF_CONFIRMED_BORDER = QColor(RED)
DIFF_UNCERTAIN_BORDER = QColor(ORANGE)

FONT_FAMILIES = [
    "Segoe UI Variable Text",
    "Segoe UI",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "WenQuanYi Micro Hei",
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
QMainWindow, QDialog { background: #F3F3F3; }
QWidget { color: #1B1B1B; }
QToolTip {
    color: #1B1B1B; background: #FFFFFF; border: 1px solid #D6D6D6;
    border-radius: 4px; padding: 6px 8px;
}
QGroupBox {
    border: 1px solid #E0E0E0; border-radius: 8px; margin-top: 14px;
    background: #FFFFFF; padding: 10px 12px 8px 12px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 12px; padding: 0 6px;
    color: #1B1B1B; font-weight: 600;
}
QPushButton {
    background: #FDFDFD; border: 1px solid #D1D1D1; border-radius: 4px;
    padding: 6px 14px; min-height: 20px; color: #1B1B1B;
}
QPushButton:hover { background: #F6F6F6; border-color: #C4C4C4; }
QPushButton:pressed { background: #EFEFEF; border-color: #B8B8B8; }
QPushButton:disabled { color: #9A9A9A; background: #F5F5F5; border-color: #E5E5E5; }
QPushButton#primary {
    background: #0067C0; color: white; border: 1px solid #0067C0;
    font-weight: 600; padding: 7px 20px; border-radius: 4px;
}
QPushButton#primary:hover { background: #1975C5; border-color: #1975C5; }
QPushButton#primary:pressed { background: #005A9E; border-color: #005A9E; }
QPushButton#primary:disabled { background: #B7D4EA; border-color: #B7D4EA; color: #F5F9FC; }
QPushButton#tool {
    padding: 5px 9px; min-height: 18px; background: transparent; border-color: transparent;
}
QPushButton#tool:hover { background: #EDEDED; border-color: #E0E0E0; }
QPushButton#tool:pressed { background: #E5E5E5; }
QLineEdit {
    background: #FBFBFB; border: 1px solid #D1D1D1; border-radius: 4px;
    padding: 6px 10px; selection-background-color: #0067C0; selection-color: white;
}
QLineEdit:hover { background: #FFFFFF; border-color: #B8B8B8; }
QLineEdit:focus { background: #FFFFFF; border: 1px solid #0067C0; }
QCheckBox { spacing: 7px; }
QCheckBox:disabled { color: #9A9A9A; }
QComboBox {
    background: #FBFBFB; border: 1px solid #D1D1D1; border-radius: 4px; padding: 5px 10px;
}
QComboBox:hover { background: #FFFFFF; border-color: #B8B8B8; }
QComboBox:focus { border-color: #0067C0; background: #FFFFFF; }
QComboBox QAbstractItemView {
    background: #FFFFFF; border: 1px solid #D6D6D6; border-radius: 6px;
    selection-background-color: #E5F1FB; selection-color: #1B1B1B; padding: 4px;
}
QSpinBox, QDoubleSpinBox {
    background: #FBFBFB; border: 1px solid #D1D1D1; border-radius: 4px;
    padding: 5px 7px; min-height: 20px;
}
QSpinBox:focus, QDoubleSpinBox:focus { border-color: #0067C0; background: #FFFFFF; }
QStatusBar { background: #FAFAFA; border-top: 1px solid #E0E0E0; }
QStatusBar QLabel { color: #616161; padding: 0 6px; }
QToolBar { background: #FFFFFF; border: none; spacing: 4px; }
QSplitter::handle { background: #E5E5E5; width: 4px; }
QSplitter::handle:hover { background: #0067C0; }
QTabBar::tab {
    background: #F0F0F0; color: #616161; border: 1px solid #E0E0E0;
    border-bottom: none; padding: 6px 15px; margin-right: 2px;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #FFFFFF; color: #1B1B1B; border-bottom: 2px solid #0067C0;
}
QTabBar::tab:hover { background: #F7F7F7; }
QTabWidget::pane { border: 1px solid #E0E0E0; background: #FFFFFF; border-radius: 6px; }
QMenu {
    background: #FFFFFF; border: 1px solid #E0E0E0; border-radius: 8px; padding: 5px;
}
QMenu::item { padding: 6px 28px 6px 18px; border-radius: 4px; }
QMenu::item:selected { background: #E5F1FB; }
QMenu::separator { height: 1px; background: #E5E5E5; margin: 4px 8px; }
QScrollBar:vertical { background: #F7F7F7; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #C8C8C8; min-height: 30px; border-radius: 4px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: #A6A6A6; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: #F7F7F7; height: 11px; margin: 0; }
QScrollBar::handle:horizontal { background: #C8C8C8; min-width: 30px; border-radius: 4px; margin: 2px; }
QScrollBar::handle:horizontal:hover { background: #A6A6A6; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QProgressBar {
    background: #E8E8E8; border: none; border-radius: 3px; height: 6px;
    text-align: center; color: transparent;
}
QProgressBar::chunk { background: #0067C0; border-radius: 3px; }
"""
