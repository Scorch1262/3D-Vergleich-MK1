"""Farben und Stylesheet im Stil der Dashboards (dunkel, Amber/Teal-Akzente)."""
import numpy as np

BG = "#0a0e13"
BG2 = "#0f151c"
PANEL = "#121a23"
PANEL2 = "#17212c"
BORDER = "#223040"
BORDER_HI = "#2e4256"
TEXT = "#d7e0ea"
TEXT_DIM = "#7d8ea1"
AMBER = "#ffb000"
TEAL = "#19d3c5"
RED = "#ff4d5e"
BLUE = "#3d7bff"
GREEN = "#3ddc84"
GHOST = "#8a96a3"

COLOR_A = TEAL     # Referenz
COLOR_B = AMBER    # Pruefobjekt

MONO = "Consolas, 'Cascadia Mono', 'DejaVu Sans Mono', monospace"


def hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hex_rgbf(h: str):
    return tuple(c / 255.0 for c in hex_rgb(h))


# Farbskala fuer Abweichungen: -1 .. +1
CMAP_STOPS = [
    (-1.0, hex_rgb(BLUE)),
    (-0.5, hex_rgb(TEAL)),
    (0.0, hex_rgb(GREEN)),
    (0.5, hex_rgb(AMBER)),
    (1.0, hex_rgb(RED)),
]


def colormap(values: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    """Werte -> RGB uint8 (N,3) mit der Dashboard-Skala."""
    if vmax <= vmin:
        vmax = vmin + 1e-9
    t = (np.clip(values, vmin, vmax) - vmin) / (vmax - vmin) * 2.0 - 1.0
    xs = np.array([s[0] for s in CMAP_STOPS])
    out = np.empty((len(values), 3), np.uint8)
    for c in range(3):
        ys = np.array([s[1][c] for s in CMAP_STOPS], float)
        out[:, c] = np.interp(t, xs, ys).astype(np.uint8)
    return out


STYLESHEET = f"""
* {{
    font-family: 'Segoe UI', 'Inter', 'DejaVu Sans', sans-serif;
    font-size: 12px;
    color: {TEXT};
}}
QMainWindow, QWidget#Root {{ background: {BG}; }}
QWidget {{ background: transparent; }}
QToolTip {{ background: {PANEL2}; color: {TEXT}; border: 1px solid {BORDER_HI}; padding: 4px; }}

QFrame#Header {{
    background: {BG2};
    border-bottom: 1px solid {BORDER};
}}
QLabel#Title {{ color: {AMBER}; font-size: 16px; font-weight: 700; letter-spacing: 3px; }}
QLabel#TitleSub {{ color: {TEXT_DIM}; font-size: 12px; letter-spacing: 2px; font-family: {MONO}; }}
QLabel#Chip {{
    border: 1px solid {BORDER_HI}; border-radius: 2px; padding: 2px 8px;
    font-family: {MONO}; font-size: 11px; color: {TEXT_DIM}; letter-spacing: 1px;
}}
QLabel#ChipLive {{
    border: 1px solid {TEAL}; border-radius: 2px; padding: 2px 8px;
    font-family: {MONO}; font-size: 11px; color: {TEAL}; letter-spacing: 1px;
}}
QLabel#ChipBusy {{
    border: 1px solid {AMBER}; border-radius: 2px; padding: 2px 8px;
    font-family: {MONO}; font-size: 11px; color: {AMBER}; letter-spacing: 1px;
}}

QFrame#Panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 3px; }}
QFrame#SideBar, QFrame#RightBar {{ background: {BG2}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QPushButton#SectionHeader {{
    background: {PANEL2}; border: none; border-left: 2px solid {AMBER}; border-radius: 0;
    color: {TEXT}; font-weight: 600; letter-spacing: 2px; font-size: 11px;
    padding: 7px 8px; text-align: left;
}}
QPushButton#SectionHeader:hover {{ background: #1c2835; color: {TEXT}; }}
QPushButton#SectionHeader:checked {{ background: {PANEL2}; }}
QFrame#SectionBody {{ background: {PANEL}; border: 1px solid {BORDER}; border-top: none; }}

QLabel#Caption {{ color: {TEXT_DIM}; font-size: 10px; letter-spacing: 1.5px; font-weight: 600; }}
QLabel#Mono {{ font-family: {MONO}; font-size: 11px; color: {TEXT}; }}
QLabel#MonoDim {{ font-family: {MONO}; font-size: 11px; color: {TEXT_DIM}; }}
QLabel#SlotA {{ color: {TEAL}; font-weight: 700; font-family: {MONO}; letter-spacing: 1px; }}
QLabel#SlotB {{ color: {AMBER}; font-weight: 700; font-family: {MONO}; letter-spacing: 1px; }}
QLabel#KpiValue {{ font-family: {MONO}; font-size: 38px; font-weight: 700; color: {TEAL}; }}
QLabel#KpiSmall {{ font-family: {MONO}; font-size: 15px; font-weight: 600; color: {TEXT}; }}
QLabel#Hint {{ color: {TEXT_DIM}; font-size: 11px; }}

QPushButton {{
    background: {PANEL2}; border: 1px solid {BORDER_HI}; border-radius: 2px;
    padding: 6px 10px; color: {TEXT};
}}
QPushButton:hover {{ border-color: {TEAL}; color: #ffffff; }}
QPushButton:pressed {{ background: #0e1620; }}
QPushButton:disabled {{ color: #4b5866; border-color: {BORDER}; }}
QPushButton#Primary {{
    background: {AMBER}; color: #111; border: 1px solid {AMBER};
    font-weight: 700; letter-spacing: 2px; padding: 9px;
}}
QPushButton#Primary:hover {{ background: #ffc233; color: #000; }}
QPushButton#Primary:disabled {{ background: #3a3220; color: #7a6a40; border-color: #3a3220; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid {BORDER}; }}

QToolButton#Tool {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 2px;
    padding: 5px 7px; color: {TEXT}; font-size: 11px; letter-spacing: 0.5px;
}}
QToolButton#Tool:hover {{ border-color: {TEAL}; }}
QToolButton#Tool:checked {{ border-color: {AMBER}; color: {AMBER}; background: #221b0c; }}
QToolButton#Tool::menu-indicator {{ image: none; width: 0; }}

QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {{
    background: {BG}; border: 1px solid {BORDER_HI}; border-radius: 2px;
    padding: 4px 6px; color: {TEXT}; font-family: {MONO};
    selection-background-color: {TEAL}; selection-color: #000;
}}
QComboBox:hover, QDoubleSpinBox:hover, QSpinBox:hover {{ border-color: {TEAL}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    image: none; width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_DIM}; margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {PANEL}; border: 1px solid {BORDER_HI}; outline: 0; padding: 0;
    selection-background-color: #1d3a3a; selection-color: {TEAL};
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button {{ width: 14px; border: none; background: {PANEL2}; }}
QDoubleSpinBox::up-arrow, QSpinBox::up-arrow {{
    width: 0; height: 0; border-left: 3px solid transparent; border-right: 3px solid transparent;
    border-bottom: 4px solid {TEXT_DIM};
}}
QDoubleSpinBox::down-arrow, QSpinBox::down-arrow {{
    width: 0; height: 0; border-left: 3px solid transparent; border-right: 3px solid transparent;
    border-top: 4px solid {TEXT_DIM};
}}

QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid {BORDER_HI}; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {TEAL}; border-color: {TEAL}; }}
QCheckBox::indicator:hover {{ border-color: {TEAL}; }}

QSlider::groove:horizontal {{ height: 3px; background: {BORDER_HI}; }}
QSlider::sub-page:horizontal {{ background: {TEAL}; }}
QSlider::handle:horizontal {{
    width: 10px; height: 14px; margin: -6px 0; background: {TEXT}; border-radius: 1px;
}}
QSlider::handle:horizontal:hover {{ background: {AMBER}; }}

QProgressBar {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 1px; height: 8px;
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {AMBER}; }}

QTreeWidget, QListWidget {{
    background: {BG}; border: 1px solid {BORDER}; font-family: {MONO}; font-size: 11px;
    alternate-background-color: #0d131a; outline: 0;
}}
QTreeWidget::item {{ padding: 3px 2px; }}
QTreeWidget::item:selected {{ background: #1d3a3a; color: {TEAL}; }}
QHeaderView::section {{
    background: {PANEL2}; color: {TEXT_DIM}; border: none; border-bottom: 1px solid {BORDER};
    padding: 4px; font-size: 10px; letter-spacing: 1px;
}}

QStatusBar {{ background: {BG2}; border-top: 1px solid {BORDER}; color: {TEXT_DIM}; }}
QStatusBar QLabel {{ color: {TEXT_DIM}; font-family: {MONO}; font-size: 11px; }}

QScrollBar:vertical {{ background: {BG}; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER_HI}; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEAL}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: {BG}; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {BORDER_HI}; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}

QMessageBox, QDialog {{ background: {PANEL}; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER_HI}; padding: 0; }}
QMenu::item {{ padding: 6px 18px; }}
QMenu::item:selected {{ background: #1d3a3a; color: {TEAL}; }}
"""
