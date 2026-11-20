"""角色的内置帧集：槽位定义 + 从 assets/char 读图。

自定义角色主题功能已移除，角色固定使用内置形象「大肥鱼」。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QPixmap

BUILTIN_ID = "builtin"
BUILTIN_NAME = "大肥鱼"

# ---------------------------------------------------------------- 槽位

@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    group: str
    usage: str = ""


SLOTS: tuple[Slot, ...] = (
    # 待机：按时间递进
    Slot("14_cheek", "托腮", "idle", "默认待机"),
    Slot("18_lean", "倚靠", "idle", "5 分钟没人理"),
    Slot("16_nap", "打盹", "idle", "20 分钟没人理"),
    Slot("17_wow", "惊叹", "idle", "光标移到角色身上，停 5 秒"),
    # 久坐提醒：按次数升级
    Slot("05_wave", "招手", "action", "第 1 次久坐提醒"),
    Slot("01_angry", "生气", "action", "第 2 次久坐提醒"),
    Slot("02_confused", "困惑", "action", "第 3 次及以后"),
    # 下班
    Slot("06_laugh", "大笑", "action", "下班到点蹦一下"),
    # 拖动：按拖动时长顺序切
    Slot("07_stumble", "小碎步", "drag", "拖动 0 ~ 1.4 秒"),
    Slot("08_tumble", "踉跄", "drag", "拖动 1.4 ~ 2.8 秒"),
    Slot("09_faceplant", "拖飞", "drag", "拖动 2.8 秒后"),
    # 午休吃饭
    Slot("31_cook", "开锅", "meal", "午休刚开始"),
    Slot("32_scoop", "盛饭", "meal", "午休 +1.6 秒"),
    Slot("33_serve", "捧碗", "meal", "午休 +3.2 秒"),
    Slot("34_feast", "猛吃", "meal", "午休满 2 分钟"),
    Slot("35_eat", "扒饭", "meal", "午休满 2 分钟 +1.3 秒"),
    Slot("36_full", "吃撑", "meal", "午休满 2 分钟 +2.6 秒"),
    # 喝水
    Slot("37_hold_cup", "端杯", "drink", "点「喝了」第 1 帧"),
    Slot("38_raise", "举杯", "drink", "第 2 帧"),
    Slot("39_sip", "抿一口", "drink", "第 3 帧"),
    Slot("40_gulp", "猛喝", "drink", "第 4 帧"),
    Slot("41_ahh", "缓口气", "drink", "第 5 帧"),
    Slot("42_done", "喝完", "drink", "第 6 帧"),
)


# ---------------------------------------------------------------- 读图


def builtin_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "assets" / "char"
    return Path(__file__).resolve().parent / "assets" / "char"


_BUILTIN_CACHE: dict[str, QPixmap] = {}


def _builtin_pixmap(key: str) -> QPixmap | None:
    if key not in _BUILTIN_CACHE:
        path = builtin_dir() / f"{key}.png"
        _BUILTIN_CACHE[key] = QPixmap(str(path)) if path.exists() else QPixmap()
    pix = _BUILTIN_CACHE[key]
    return None if pix.isNull() else pix


def resolve(theme_id: object = "") -> str:
    """兼容旧调用：现在一律内置。"""
    return BUILTIN_ID


def load_frames(theme_id: str = BUILTIN_ID) -> dict[str, QPixmap]:
    """读内置帧集；顺带把目录里未声明的图也带上，防止拼写落空。"""
    frames: dict[str, QPixmap] = {}
    for slot in SLOTS:
        pix = _builtin_pixmap(slot.key)
        if pix is not None:
            frames[slot.key] = pix
    for path in sorted(builtin_dir().glob("*.png")):
        if path.stem in frames:
            continue
        pix = _builtin_pixmap(path.stem)
        if pix is not None:
            frames[path.stem] = pix
    return frames
