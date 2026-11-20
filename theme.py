"""视觉规范：色板、字体、应用图标。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)

# ---------------------------------------------------------------- 配色主题

THEMES: dict[str, dict[str, str]] = {
    # 深海：跟着角色的深蓝头发走，整块像块深海玻璃
    "deep": {
        "bg": "#0B1428",
        "raised": "#14203A",
        "input": "#111C33",
        "text_hi": "#EAF1FF",
        "text_mid": "#93A6C9",
        "text_low": "#5C6E90",
        "accent": "#5B8DFF",
        "accent_deep": "#3D6BE0",
        "warn": "#FF9F5A",
        "warn_deep": "#FF7A3D",
        "mint": "#6FD8C8",
        "line": "rgba(130, 170, 255, 26)",
    },
    # 雾蓝：低饱和灰蓝，最不抢眼的一版
    "mist": {
        "bg": "#232E48",
        "raised": "#2C3958",
        "input": "#28334F",
        "text_hi": "#E6EDF9",
        "text_mid": "#97A6C2",
        "text_low": "#65759A",
        "accent": "#7FA9FF",
        "accent_deep": "#5C86E0",
        "warn": "#FFAE6B",
        "warn_deep": "#FF8A45",
        "mint": "#78D6C6",
        "line": "rgba(150, 180, 230, 24)",
    },
    # 奶油：接近她围裙的白，浅色系在深色桌面上最跳
    "cream": {
        "bg": "#E7EEF9",
        "raised": "#DAE5F5",
        "input": "#DCE8F6",
        "text_hi": "#1E2B4A",
        "text_mid": "#5A6A8C",
        "text_low": "#93A1BC",
        "accent": "#4C7DF0",
        "accent_deep": "#3564D8",
        "warn": "#F0803C",
        "warn_deep": "#DB6420",
        "mint": "#2FB59B",
        "line": "rgba(40, 70, 130, 26)",
    },
    # 晴空：淡蓝底，介于白与蓝之间
    "sky": {
        "bg": "#DDEAFA",
        "raised": "#CFE1F6",
        "input": "#D3E4F8",
        "text_hi": "#18253F",
        "text_mid": "#4E5F80",
        "text_low": "#8798B5",
        "accent": "#3F6FE0",
        "accent_deep": "#2A57C4",
        "warn": "#E87A36",
        "warn_deep": "#D25F1D",
        "mint": "#2AA88F",
        "line": "rgba(30, 60, 120, 28)",
    },
}

ACTIVE_THEME = os.environ.get("DESK_THEME", "mist")
_T = THEMES.get(ACTIVE_THEME, THEMES["mist"])

BG = _T["bg"]
BG_RAISED = _T["raised"]
BG_INPUT = _T["input"]
TEXT_HI = _T["text_hi"]
TEXT_MID = _T["text_mid"]
TEXT_LOW = _T["text_low"]
ACCENT = _T["accent"]
ACCENT_DEEP = _T["accent_deep"]
ORANGE = _T["warn"]
ORANGE_DEEP = _T["warn_deep"]
MINT = _T["mint"]
BLUE = _T["accent"]
LINE = _T["line"]

# 卡片本体：底色 + 描边 + 是否浅色主题
CARD_BG = QColor(BG)
CARD_BG.setAlpha(252)
IS_LIGHT = QColor(BG).lightness() > 140
CARD_BORDER_ALPHA = 70 if IS_LIGHT else 24
CARD_BORDER_ALPHA_HOVER = 110 if IS_LIGHT else 46


def card_border(hover: bool = False) -> QColor:
    alpha = CARD_BORDER_ALPHA_HOVER if hover else CARD_BORDER_ALPHA
    base = QColor(28, 52, 100) if IS_LIGHT else QColor(255, 255, 255)
    base.setAlpha(alpha)
    return base

UI_FAMILY = "Microsoft YaHei UI"

_PIXEL_FAMILY: str | None = None


def pixel_family() -> str:
    """像素字体（Ark Pixel 12px，OFL 协议），随包一起分发。"""
    global _PIXEL_FAMILY
    if _PIXEL_FAMILY is not None:
        return _PIXEL_FAMILY
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    path = root / "assets" / "fonts" / "ark-pixel-12px.ttf"
    _PIXEL_FAMILY = ""
    try:
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        if families:
            _PIXEL_FAMILY = families[0]
    except Exception:
        _PIXEL_FAMILY = ""
    return _PIXEL_FAMILY


_LATIN_FAMILY: str | None = None


def digit_family() -> str:
    """像素字体的拉丁子集：中文那套里没有数字，倒计时要用这个。"""
    global _LATIN_FAMILY
    if _LATIN_FAMILY is not None:
        return _LATIN_FAMILY
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    path = root / "assets" / "fonts" / "ark-pixel-12px-latin.ttf"
    _LATIN_FAMILY = ""
    try:
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        if families:
            _LATIN_FAMILY = families[0]
    except Exception:
        _LATIN_FAMILY = ""
    return _LATIN_FAMILY


_DSEG_FAMILY: str | None = None


def dseg_family() -> str:
    """七段数码管字体（DSEG7 Classic，SIL OFL），只用来显示倒计时数字。"""
    global _DSEG_FAMILY
    if _DSEG_FAMILY is not None:
        return _DSEG_FAMILY
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    path = root / "assets" / "fonts" / "dseg7-classic.ttf"
    _DSEG_FAMILY = ""
    try:
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        if families:
            _DSEG_FAMILY = families[0]
    except Exception:
        _DSEG_FAMILY = ""
    return _DSEG_FAMILY


def segment_font(px: int) -> QFont:
    """倒计时用的数码管字体；拿不到就退回等宽字体。"""
    font = QFont(dseg_family() or mono_family())
    font.setPixelSize(px)
    font.setWeight(QFont.Weight.Normal)
    return font


# 像素字体是按 12px 网格设计的，只有 12 的整数倍才不糊
_PIXEL_SIZES = {11: 12, 12: 12, 13: 12, 14: 12, 26: 24, 30: 36, 32: 36}


def pixel_text_font(px: int) -> QFont:
    """像素字体，但按指定像素字号（不吸附到 12 的倍数），给需要中间字号的场合。"""
    font = QFont(pixel_family() or UI_FAMILY)
    font.setPixelSize(px)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    return font


def _style_pixel() -> bool:
    try:
        import style as style_mod
        return style_mod.current().pixel_font
    except Exception:
        return False


def _pixel_size(px: int) -> int:
    return _PIXEL_SIZES.get(px, px)

_mono: str | None = None


def mono_family() -> str:
    global _mono
    if _mono is None:
        try:
            families = set(QFontDatabase.families())
        except Exception:
            families = set()
        for name in ("JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New"):
            if name in families:
                _mono = name
                break
        else:
            _mono = "Consolas"
    return _mono


def ui_font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    family = UI_FAMILY
    if _style_pixel():
        family = pixel_family() or UI_FAMILY
        px = _pixel_size(px)
    font = QFont(family)
    if family != UI_FAMILY:
        # 中文走中文子集，数字/符号缺字时由拉丁子集补，
        # 最后再用系统字体兜底，避免出现方块
        latin = digit_family()
        family_list = [family] + ([latin] if latin and latin != family else []) + [UI_FAMILY]
        font.setFamilies(family_list)
    font.setPixelSize(px)
    font.setWeight(weight)
    if family != UI_FAMILY:
        # 像素字体一开抗锯齿就糊，直接关掉
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    return font


def mono_font(px: int, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    if _style_pixel():
        family = pixel_family() or mono_family()
        font = QFont(family)
        font.setPixelSize(_pixel_size(px))
        font.setWeight(weight)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        return font
    font = QFont(mono_family())
    font.setPixelSize(px)
    font.setWeight(weight)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


# ---------------------------------------------------------------- 图标


def _icon_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    margin = size * 0.04
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor(ORANGE))
    grad.setColorAt(1.0, QColor(ORANGE_DEEP))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawRoundedRect(rect, size * 0.27, size * 0.27)

    center = QPointF(size / 2, size / 2)
    radius = size * 0.205
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(
        QPen(
            QColor(255, 255, 255, 245),
            max(1.0, size * 0.068),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
    )
    painter.drawEllipse(center, radius, radius)
    painter.drawLine(center, QPointF(center.x(), center.y() - radius * 0.56))
    painter.drawLine(center, QPointF(center.x() + radius * 0.44, center.y() + radius * 0.3))
    painter.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_icon_pixmap(size))
    return icon


# ---------------------------------------------------------------- 样式表

BASE_QSS = f"""
QWidget {{
    color: {TEXT_HI};
    font-family: "{UI_FAMILY}";
}}
QLabel {{ background: transparent; }}
QToolTip {{
    background: {BG_RAISED};
    color: {TEXT_HI};
    border: 1px solid rgba(255, 255, 255, 22);
    padding: 5px 8px;
}}
"""

SETTINGS_QSS = f"""
QDialog {{ background: {BG}; }}
QLabel#section {{
    color: {TEXT_LOW};
    font-size: 11px;
    letter-spacing: 1px;
    padding-top: 6px;
}}
QLabel#hint {{ color: {TEXT_LOW}; font-size: 12px; }}
QLabel#field {{ color: {TEXT_MID}; font-size: 13px; }}
QPushButton#chip {{
    background: {BG_INPUT};
    color: {TEXT_MID};
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 8px;
    padding: 7px 0;
    font-size: 13px;
}}
QPushButton#chip:hover {{ border: 1px solid rgba(255, 255, 255, 50); }}
QPushButton#chip:checked {{
    background: {ORANGE};
    color: #1B1D21;
    border: 1px solid {ORANGE};
    font-weight: 600;
}}
QPushButton#primary {{
    background: {ORANGE};
    color: #1B1D21;
    border: none;
    border-radius: 9px;
    padding: 9px 22px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: #FF9A63; }}
QPushButton#ghost {{
    background: transparent;
    color: {TEXT_MID};
    border: 1px solid rgba(255, 255, 255, 26);
    border-radius: 9px;
    padding: 9px 18px;
    font-size: 13px;
}}
QPushButton#ghost:hover {{ color: {TEXT_HI}; border: 1px solid rgba(255, 255, 255, 60); }}
QMenu {{
    background: {BG_RAISED};
    border: 1px solid rgba(255, 255, 255, 26);
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: 6px;
    color: {TEXT_MID};
    font-size: 13px;
}}
QPushButton#mini {{
    background: transparent; color: {TEXT_MID};
    border: 1px solid rgba(255, 255, 255, 30); border-radius: 7px;
    padding: 0px; font-size: 11px;
}}
QPushButton#mini:hover {{ background: rgba(255, 255, 255, 16); color: {TEXT_HI}; }}
QPushButton#mini:disabled {{ color: {TEXT_LOW}; border-color: rgba(255,255,255,14); }}
QMenu::item:selected {{ background: rgba(255, 138, 76, 45); color: {TEXT_HI}; }}
QMenu::separator {{ height: 1px; background: rgba(255, 255, 255, 20); margin: 5px 8px; }}
"""


# ---------------------------------------------------------------- 主题编辑器

THEME_UI_QSS = f"""
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ width: 8px; background: transparent; margin: 2px 0; }}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 46); border-radius: 4px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(255, 255, 255, 78); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QWidget#slotCard {{
    background: {BG_RAISED}; border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 12px;
}}
QWidget#slotCard:hover {{ border: 1px solid rgba(255, 255, 255, 54); }}
QLabel#badge {{
    color: {ORANGE}; background: rgba(255, 159, 90, 28);
    border-radius: 7px; padding: 2px 8px;
}}
"""
