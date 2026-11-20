"""卡片风格：一套参数同时驱动卡片、设置面板、菜单的观感。

目前两套：
  · glass —— 原来的深蓝玻璃，默认
  · pixel —— 像素 RPG：方角、双层金边、分段进度条

模块里的 `current()` 是全局当前风格，切换后调用各窗口的 `apply_style()` 重新上色。
"""

from __future__ import annotations

from dataclasses import dataclass

from theme import UI_FAMILY, pixel_family


@dataclass(frozen=True)
class Style:
    key: str
    name: str
    desc: str
    dark: bool
    bg: str              # 卡片底色
    panel: str           # 设置窗口底色
    raised: str          # 输入框/菜单底色
    input: str           # 输入控件底色
    text_hi: str
    text_mid: str
    text_low: str
    accent: str          # 主强调色（进度、按钮）
    accent_2: str        # 次强调色（久坐条）
    dot: str             # 日期前的小点
    track: str           # 进度条空槽
    radius: int          # 卡片圆角
    frame: bool          # 双层描边（像素风）
    segmented: bool      # 分段进度条
    chip_radius: int     # 按钮/输入框圆角
    work_label: str      # 时间上方的说明文字
    hearts: bool         # 进度用爱心血量表示
    pixel_font: bool     # 用像素字体
    card_extra: int      # 卡片额外高度（血量比细条高）
    border: str          # 卡片描边色
    dither: bool = False      # 面板底色用 2x2 棋盘抖动
    scanlines: bool = False   # 面板叠 CRT 扫描线


GLASS = Style(
    key="glass",
    name="深蓝玻璃",
    desc="默认样式，深蓝底 + 橙色进度",
    dark=True,
    bg="#232E48",
    panel="#232E48",
    raised="#2C3958",
    input="#28334F",
    text_hi="#E6EDF9",
    text_mid="#97A6C2",
    text_low="#65759A",
    accent="#FFAE6B",
    accent_2="#78D6C6",
    dot="#78D6C6",
    track="rgba(255, 255, 255, 26)",
    radius=16,
    frame=False,
    segmented=False,
    chip_radius=8,
    work_label="剩余工时",
    hearts=False,
    pixel_font=False,
    card_extra=0,
    border="rgba(255, 255, 255, 26)",
)

PIXEL = Style(
    key="pixel",
    name="像素 RPG",
    desc="方角、双层金边、分段进度条",
    dark=True,
    bg="#17242F",
    panel="#17242F",
    raised="#272C46",
    input="#2B3050",
    text_hi="#F5EBD8",
    text_mid="#C6CADB",
    text_low="#8C93A8",
    accent="#E7D3A0",
    accent_2="#E7D3A0",
    dot="#E7C36A",
    track="#39405E",
    radius=0,
    frame=True,
    segmented=True,
    chip_radius=0,
    work_label="距离满血",
    hearts=True,
    pixel_font=True,
    card_extra=12,
    border="#BDC8DE",
    dither=True,
    scanlines=True,
)

STYLES: dict[str, Style] = {s.key: s for s in (GLASS, PIXEL)}
DEFAULT = GLASS.key

_current: Style = GLASS


def current() -> Style:
    return _current


def get(key: str) -> Style:
    return STYLES.get(key, GLASS)


def set_current(key: str) -> Style:
    global _current
    _current = STYLES.get(key, GLASS)
    return _current


def order() -> list[Style]:
    return [STYLES[k] for k in (GLASS.key, PIXEL.key)]


def _family(s: "Style") -> str:
    if s.pixel_font:
        return pixel_family() or UI_FAMILY
    return UI_FAMILY


def base_qss() -> str:
    s = _current
    return f"""
QWidget {{
    color: {s.text_hi};
}}
QLabel {{ background: transparent; }}
QToolTip {{
    background: {s.raised};
    color: {s.text_hi};
    border: 1px solid {s.border};
    padding: 5px 8px;
}}
"""


def settings_qss() -> str:
    s = _current
    r = s.chip_radius
    # 像素字体只有 12 的倍数才清晰，字号统一吸附
    f_small = 12 if s.pixel_font else 11
    f_body = 12 if s.pixel_font else 13
    return f"""
QDialog {{ background: {s.panel}; }}
QLabel#section {{
    color: {s.text_low};
    font-size: {f_small}px;
    letter-spacing: 1px;
    padding-top: 6px;
}}
QLabel#hint {{ color: {s.text_low}; font-size: {f_body}px; }}
QLabel#field {{ color: {s.text_mid}; font-size: {f_body}px; }}
QPushButton#chip {{
    background: {s.input};
    color: {s.text_mid};
    border: 1px solid {s.border};
    border-radius: {r}px;
    padding: 7px 0;
    font-size: {f_body}px;
}}
QPushButton#chip:hover {{ border: 1px solid {s.accent}; }}
QPushButton#chip:checked {{
    background: {s.accent};
    color: {s.bg};
    border: 1px solid {s.accent};
    font-weight: 600;
}}
QPushButton#primary {{
    background: {s.accent};
    color: {s.bg};
    border: none;
    border-radius: {r + 1}px;
    padding: 9px 22px;
    font-size: {f_body}px;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {s.accent}; }}
QPushButton#ghost {{
    background: transparent;
    color: {s.text_mid};
    border: 1px solid {s.border};
    border-radius: {r + 1}px;
    padding: 9px 18px;
    font-size: {f_body}px;
}}
QPushButton#ghost:hover {{ color: {s.text_hi}; border: 1px solid {s.accent}; }}
QMenu {{
    background: {s.raised};
    border: 1px solid {s.border};
    border-radius: {r + 2}px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: {r}px;
    color: {s.text_mid};
    font-size: {f_body}px;
}}
QPushButton#styleChip {{
    background: {s.input};
    color: {s.text_mid};
    border: 1px solid {s.border};
    border-radius: {r}px;
    font-size: 12px;
}}
QPushButton#styleChip:hover {{ border: 1px solid {s.accent}; }}
QPushButton#styleChip:checked {{
    background: {s.accent};
    color: {s.bg};
    border: 1px solid {s.accent};
    font-weight: 600;
}}
QPushButton#mini {{
    background: transparent; color: {s.text_mid};
    border: 1px solid {s.border}; border-radius: {r}px;
    padding: 0px; font-size: {f_small}px;
}}
QPushButton#mini:hover {{ background: {s.input}; color: {s.text_hi}; }}
QPushButton#mini:disabled {{ color: {s.text_low}; border-color: {s.border}; }}
QMenu::item:selected {{ background: {s.accent}; color: {s.bg}; }}
QMenu::separator {{ height: 1px; background: {s.track}; margin: 5px 8px; }}
"""


def scroll_qss() -> str:
    s = _current
    return (
        "QScrollArea { background: transparent; border: none; }"
        "QScrollBar:vertical { width: 8px; background: transparent; margin: 2px 0; }"
        "QScrollBar::handle:vertical {"
        f" background: {s.track}; border-radius: 4px; min-height: 32px; }}"
        "QScrollBar::handle:vertical:hover { background: " + s.accent + "; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
    )
