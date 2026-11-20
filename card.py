"""桌面悬浮卡片：常驻右下角，显示下班倒计时与久坐计时。"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QSpacerItem,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import APP_TITLE
from engine import OFF, PRE, REST, WORK, Snapshot, fmt_hms
import char_theme
from cup import DrinkCup
from fish import FishState
import style as style_mod
from weather import WeatherBadge, WeatherService
UPDATE_RED = "#FF5A5F"

from theme import (
    BASE_QSS,
    CARD_BG,
    MINT,
    ORANGE,
    TEXT_HI,
    TEXT_LOW,
    TEXT_MID,
    card_border,
    digit_family,
    pixel_text_font,
    mono_family,
    mono_font,
    pixel_family,
    segment_font,
    ui_font,
)

WEEKDAY_CN = "一二三四五六日"


_HEARTS: dict[str, QPixmap] = {}


def _heart_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "assets" / "heart"
    return Path(__file__).resolve().parent / "assets" / "heart"


_CORNERS: dict[str, QPixmap] = {}


def _ornament_pix() -> QPixmap:
    global _ORNAMENT
    if _ORNAMENT is not None and not _ORNAMENT.isNull():
        return _ORNAMENT
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    _ORNAMENT = QPixmap(str(root / "assets" / "frame" / "pixel_ornament_52x52.png"))
    return _ORNAMENT


_ORNAMENT: QPixmap | None = None


def _corner_pix(name: str) -> QPixmap:
    pix = _CORNERS.get(name)
    if pix is None or pix.isNull():
        base = getattr(sys, "_MEIPASS", None)
        root = Path(base) if base else Path(__file__).resolve().parent
        pix = QPixmap(str(root / "assets" / "frame" / f"{name}_26px.png"))
        if not pix.isNull():
            _CORNERS[name] = pix
    return pix


def _heart_pix(name: str) -> QPixmap:
    if name not in _HEARTS:
        _HEARTS[name] = QPixmap(str(_heart_dir() / f"{name}.png"))
    return _HEARTS[name]


def S() -> style_mod.Style:
    """当前卡片风格（切风格后重新取一次即可换色）。"""
    return style_mod.current()

# 窗口 = 上方鱼的活动区 + 下方卡片。鱼先画，卡片后画，自然把鱼的下半身挡住。
CARD_TOP = 156
CARD_HEIGHT = 166
FISH_CX = 152
FISH_CY = 96

SIT_REASON_TEXT = {
    "before": "还没上班 · 不计时",
    "after": "已下班 · 不计时",
    "off": "久坐提醒已关闭",
    "paused": "提醒已暂停",
    "lunch": "午休中 · 暂停计时",
    "rest": "休息日 · 不计时",
}


class Dot(QWidget):
    """状态小圆点，带呼吸光晕。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(9, 9)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._color = QColor(MINT)
        self._pulse = 1.0

    def set_state(self, color: str, pulse: float = 1.0) -> None:
        self._color = QColor(color)
        self._pulse = pulse
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        if S().pixel_font:
            # 像素风：实心小方块，带一圈暗边
            core = QColor(self._color)
            painter.setBrush(core)
            painter.drawRect(QRectF(1, 1, 7, 7))
            glow = QColor(self._color)
            glow.setAlphaF(0.28 * self._pulse)
            painter.setBrush(glow)
            painter.drawRect(QRectF(0, 0, 9, 9))
            return

        glow = QColor(self._color)
        glow.setAlphaF(0.16 * self._pulse)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(0, 0, 9, 9))

        core = QColor(self._color)
        core.setAlphaF(min(1.0, 0.55 + 0.45 * self._pulse))
        painter.setBrush(core)
        painter.drawEllipse(QRectF(1.6, 1.6, 5.8, 5.8))


class MiniBar(QWidget):
    """细进度条。"""

    def __init__(self, color: str, height: int = 4, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._height = height
        self._value = 0.0
        self._color = QColor(color)
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        if abs(value - self._value) > 0.004:
            self._value = value
            self.update()

    def set_color(self, color: str) -> None:
        new = QColor(color)
        if new != self._color:
            self._color = new
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        st = S()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, not st.segmented)
        painter.setPen(Qt.PenStyle.NoPen)
        height = self._height
        track = QColor(st.track)
        if not track.isValid():
            track = QColor(255, 255, 255, 26)

        if st.segmented:
            # 像素风：切成小段，已过的填色，剩下的留暗槽
            cells = 14
            gap = 2
            width = self.width()
            cell = max(1.0, (width - gap * (cells - 1)) / cells)
            filled = int(round(self._value * cells))
            painter.setBrush(QColor(st.bg))
            painter.drawRect(QRectF(0, 0, width, height))
            for i in range(cells):
                x = i * (cell + gap)
                painter.setBrush(self._color if i < filled else track)
                painter.drawRect(QRectF(x, 0, cell, height))
            return

        radius = height / 2
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0, 0, self.width(), height), radius, radius)

        width = self.width() * self._value
        if width > 0.5:
            painter.setBrush(self._color)
            painter.drawRoundedRect(
                QRectF(0, 0, max(width, height), height), radius, radius
            )


class HeartBar(QWidget):
    """爱心血量条：工时往前涨，久坐往回掉。"""

    TOTAL = 5

    def __init__(
        self, invert: bool = False, size: int = 15, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._invert = invert
        self._size = size
        self._value = 0.0
        gap = 5
        self.setFixedHeight(size)
        self.setFixedWidth(int(round(size * 1.2)) * self.TOTAL + gap * (self.TOTAL - 1))
        self._gap = gap
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_value(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        if abs(value - self._value) > 0.002:
            self._value = value
            self.update()

    def set_invert(self, invert: bool) -> None:
        self._invert = invert
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # 半颗一档：5 颗心 = 10 档，快下班时不会一下子全满
        # 用向下取整：只有真的走完这 10%，那一格才点亮；
        # 否则四舍五入会让最后一颗在 17:30 左右就满了，到点反而没有"全满"的变化
        steps = int(self._value * self.TOTAL * 2)
        if self._invert:
            steps = self.TOTAL * 2 - steps
        width = int(round(self._size * 1.2))
        step = width + self._gap
        full = _heart_pix("full")
        half = _heart_pix("half")
        empty = _heart_pix("empty")
        for i in range(self.TOTAL):
            if steps >= (i + 1) * 2:
                pix = full
            elif steps == i * 2 + 1:
                pix = half
            else:
                pix = empty
            if pix.isNull():
                lit = steps > i * 2
                painter.setBrush(QColor(S().accent if lit else S().track))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(i * step, 0, width, self._size)
                continue
            painter.drawPixmap(
                i * step, 0, width, self._size, pix
            )


class UpdateBadge(QWidget):
    """日期和天气之间的小提示：红色的「更新」+ NEW 标签，点一下去更新。"""

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("发现新版本，点这里查看")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        label = QLabel("更新")
        label.setFont(ui_font(11, QFont.Weight.DemiBold))
        label.setStyleSheet(f"color: {UPDATE_RED}; padding: 0;")

        self.tag = QLabel("NEW")
        self.tag.setFont(ui_font(8, QFont.Weight.Bold))
        self.tag.setStyleSheet(
            "color: #FFFFFF; background: %s; border-radius: 5px;"
            " padding: 1px 4px; letter-spacing: 0.5px;" % UPDATE_RED
        )

        layout.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.tag, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hide()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        event.ignore()


class DotsButton(QWidget):
    """右上角「···」按钮，手绘，避免字体缺字。"""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(26, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        st = S()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(st.text_hi if self._hover else st.text_low))
        center_y = self.height() / 2
        if S().pixel_font:
            for offset in (-6.0, 0.0, 6.0):
                painter.drawRect(
                    QRectF(self.width() / 2 + offset - 1.5, center_y - 1.5, 3, 3)
                )
            return
        for offset in (-5.0, 0.0, 5.0):
            painter.drawEllipse(
                QPointF(self.width() / 2 + offset, center_y), 1.7, 1.7
            )


class MiniBar(QWidget):
    """细进度条。"""

    def __init__(self, color: str, height: int = 4, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._height = height
        self._value = 0.0
        self._color = QColor(color)
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        if abs(value - self._value) > 0.004:
            self._value = value
            self.update()

    def set_color(self, color: str) -> None:
        new = QColor(color)
        if new != self._color:
            self._color = new
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        st = S()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, not st.segmented)
        painter.setPen(Qt.PenStyle.NoPen)
        height = self._height
        track = QColor(st.track)
        if not track.isValid():
            track = QColor(255, 255, 255, 26)

        if st.segmented:
            # 像素风：切成小段，已过的填色，剩下的留暗槽
            cells = 14
            gap = 2
            width = self.width()
            cell = max(1.0, (width - gap * (cells - 1)) / cells)
            filled = int(round(self._value * cells))
            painter.setBrush(QColor(st.bg))
            painter.drawRect(QRectF(0, 0, width, height))
            for i in range(cells):
                x = i * (cell + gap)
                painter.setBrush(self._color if i < filled else track)
                painter.drawRect(QRectF(x, 0, cell, height))
            return

        radius = height / 2
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0, 0, self.width(), height), radius, radius)

        width = self.width() * self._value
        if width > 0.5:
            painter.setBrush(self._color)
            painter.drawRoundedRect(
                QRectF(0, 0, max(width, height), height), radius, radius
            )


class HeartBar(QWidget):
    """爱心血量条：工时往前涨，久坐往回掉。"""

    TOTAL = 5

    def __init__(
        self, invert: bool = False, size: int = 15, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._invert = invert
        self._size = size
        self._value = 0.0
        gap = 5
        self.setFixedHeight(size)
        self.setFixedWidth(int(round(size * 1.2)) * self.TOTAL + gap * (self.TOTAL - 1))
        self._gap = gap
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_value(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        if abs(value - self._value) > 0.002:
            self._value = value
            self.update()

    def set_invert(self, invert: bool) -> None:
        self._invert = invert
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # 半颗一档：5 颗心 = 10 档，快下班时不会一下子全满
        # 用向下取整：只有真的走完这 10%，那一格才点亮；
        # 否则四舍五入会让最后一颗在 17:30 左右就满了，到点反而没有"全满"的变化
        steps = int(self._value * self.TOTAL * 2)
        if self._invert:
            steps = self.TOTAL * 2 - steps
        width = int(round(self._size * 1.2))
        step = width + self._gap
        full = _heart_pix("full")
        half = _heart_pix("half")
        empty = _heart_pix("empty")
        for i in range(self.TOTAL):
            if steps >= (i + 1) * 2:
                pix = full
            elif steps == i * 2 + 1:
                pix = half
            else:
                pix = empty
            if pix.isNull():
                lit = steps > i * 2
                painter.setBrush(QColor(S().accent if lit else S().track))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(i * step, 0, width, self._size)
                continue
            painter.drawPixmap(
                i * step, 0, width, self._size, pix
            )


class UpdateBadge(QWidget):
    """日期和天气之间的小提示：红色的「更新」+ NEW 标签，点一下去更新。"""

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("发现新版本，点这里查看")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        label = QLabel("更新")
        label.setFont(ui_font(11, QFont.Weight.DemiBold))
        label.setStyleSheet(f"color: {UPDATE_RED}; padding: 0;")

        self.tag = QLabel("NEW")
        self.tag.setFont(ui_font(8, QFont.Weight.Bold))
        self.tag.setStyleSheet(
            "color: #FFFFFF; background: %s; border-radius: 5px;"
            " padding: 1px 4px; letter-spacing: 0.5px;" % UPDATE_RED
        )

        layout.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.tag, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hide()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        event.ignore()


class DotsButton(QWidget):
    """右上角「···」按钮，手绘，避免字体缺字。"""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(26, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        st = S()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(st.text_hi if self._hover else st.text_low))
        center_y = self.height() / 2
        if S().pixel_font:
            for offset in (-6.0, 0.0, 6.0):
                painter.drawRect(
                    QRectF(self.width() / 2 + offset - 1.5, center_y - 1.5, 3, 3)
                )
            return
        for offset in (-5.0, 0.0, 5.0):
            painter.drawEllipse(
                QPointF(self.width() / 2 + offset, center_y), 1.7, 1.7
            )


class MainCard(QWidget):
    request_settings = Signal()
    request_menu = Signal(QPoint)
    request_hide = Signal()
    request_update = Signal()
    request_drink = Signal()
    moved = Signal()

    def __init__(self, cfg, engine) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.cfg = cfg
        self.engine = engine
        self.setWindowTitle(APP_TITLE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._apply_size()
        self.setStyleSheet(BASE_QSS)
        self.setMouseTracking(True)
        self._drag_offset: QPoint | None = None
        self._dragged = False
        self._hover = False
        self._show_char = bool(cfg["show_character"])
        self._hovering = False
        # 长按角色 3 秒：被拎起来
        self._press_at = 0.0
        self._lifting = False
        self._long_timer = QTimer(self)
        self._long_timer.setSingleShot(True)
        self._long_timer.setInterval(3000)
        self._long_timer.timeout.connect(self._on_long_press)
        self._char_top = CARD_TOP if self._show_char else 0
        self.fish = FishState()
        self._build()
        self.adjustSize()

        self.cup = DrinkCup()
        self._place_cup()

        self.weather_service = WeatherService(cfg, self)
        self.weather_service.updated.connect(self.weather.set_weather)

        self._align_head(S().pixel_font)

        # 小肥鱼的独立节奏，比卡片刷新快
        self._fish_timer = QTimer(self)
        self._fish_timer.setInterval(33)
        self._fish_timer.timeout.connect(self._on_fish_tick)
        self._fish_timer.start()

    # ------------------------------------------------------------ 构建

    def _align_head(self, pixel: bool) -> None:
        """像素风藏掉日期前的小圆点，让「周几」和下面几行同一个左边缘。"""
        if getattr(self, "dot", None) is not None:
            self.dot.setVisible(not pixel)
        if getattr(self, "_head", None) is not None:
            self._head.setSpacing(0 if pixel else 7)
        if getattr(self, "_head_gap", None) is not None:
            self._head_gap.changeSize(
                0 if pixel else 1,
                0,
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Minimum,
            )

    def _caption_font(self) -> QFont:
        return pixel_text_font(14) if S().pixel_font else ui_font(12)

    def _big_height(self) -> int:
        """时间这行的高度：像素字大一号，得留够。"""
        return 38

    def _style_big(self, color: str | None = None) -> None:
        """时间标签走样式表定字体：QSS 一旦介入，setFont 会被级联覆盖。"""
        st = S()
        if st.pixel_font:
            fam, size = digit_family() or pixel_family(), 36
        else:
            fam, size = mono_family(), 30
        # 父级 QSS 会重算子控件字体，所以字体必须写在样式表里，setFont 会被吃掉
        self.big.setStyleSheet(
            f"color: {color or st.text_hi}; padding: 0; "
            f"font-family: '{fam}'; font-size: {size}px;"
        )
        self.big.setFont(self._time_font(30))

    def _time_font(self, px: int) -> QFont:
        """倒计时字体：像素风用像素字体的拉丁子集（中文字形里没有数字）。"""
        if S().pixel_font:
            font = QFont(digit_family() or pixel_family() or "Consolas")
            font.setPixelSize(36)
            font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
            return font
        return mono_font(px, QFont.Weight.DemiBold)

    def _card_height(self) -> int:
        return CARD_HEIGHT + S().card_extra

    def _frame_margin(self) -> int:
        """像素风要在边框外面画包角和底饰，四周留 12px 余量；玻璃风不留。"""
        return 12 if S().frame else 0

    def _top(self) -> int:
        """卡片上沿的 y：有角色时让出角色区，没角色时留一圈外边距给包角。"""
        top = getattr(self, "_char_top", CARD_TOP)
        return top if top else self._frame_margin()

    def _content_left(self, m: int | None = None) -> int:
        """内容区左边距：像素风的金属边框更厚，文字再往右让 8px 才不显贴边。"""
        if m is None:
            m = self._frame_margin()
        return 18 + m + (8 if S().pixel_font else 0)

    def _apply_size(self) -> None:
        m = self._frame_margin()
        top = self._top()
        self.setFixedSize(304 + 2 * m, top + self._card_height() + m)
        root = getattr(self, "_root", None)
        if root is not None:
            root.setContentsMargins(self._content_left(m), top + 13, 14 + m, 15 + m)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        m = self._frame_margin()
        root.setContentsMargins(self._content_left(m), self._top() + 13, 14 + m, 15 + m)
        self._root = root
        root.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(7)
        self._head = head
        self.dot = Dot(self)
        self.date_label = QLabel("—")
        self.date_label.setFont(ui_font(12))
        self.date_label.setStyleSheet(f"color: {S().text_mid}; padding: 0;")
        self.more_btn = DotsButton(self)
        self.more_btn.clicked.connect(self._emit_menu)
        head.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self._head_gap = QSpacerItem(
            1, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum
        )
        head.addItem(self._head_gap)
        head.addWidget(self.date_label, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        self.update_badge = UpdateBadge(self)
        self.update_badge.clicked.connect(self.request_update.emit)
        head.addWidget(self.update_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addSpacing(6)
        self.weather = WeatherBadge(self)
        head.addWidget(self.weather, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addSpacing(8)
        head.addWidget(self.more_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(head)

        pixel = S().pixel_font
        # 说明文字夹在日期行和时间之间，上下间距对称，靠固定行高把它居中
        self._gap_head = root.addSpacing(6 if pixel else 8)

        self.caption = QLabel("距离下班")
        self.caption.setFont(self._caption_font())
        self.caption.setStyleSheet(f"color: {S().text_low}; padding: 0;")
        if pixel:
            self.caption.setFixedHeight(22)
        root.addWidget(self.caption)

        self._gap_top = root.addSpacing(6 if pixel else 2)

        self.big = QLabel("--:--:--")
        self.big.setFont(self._time_font(30))
        self._style_big()
        self.big.setFixedHeight(self._big_height())
        root.addWidget(self.big)

        self._gap_bottom = root.addSpacing(8)

        self.day_bar = MiniBar(S().accent, 4, self)
        self.day_bar.setFixedWidth(136)
        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(0)
        bar_row.addWidget(self.day_bar)
        self.day_hearts = HeartBar(invert=False, parent=self)
        self.day_hearts.hide()
        bar_row.addWidget(self.day_hearts)
        bar_row.addStretch(1)
        root.addLayout(bar_row)

        root.addSpacing(7)

        sit_row = QHBoxLayout()
        sit_row.setContentsMargins(0, 0, 0, 0)
        sit_row.setSpacing(10)
        self.sit_label = QLabel("久坐")
        self.sit_label.setFont(ui_font(12))
        self.sit_label.setMinimumWidth(28)
        self.sit_label.setStyleSheet(f"color: {S().text_mid}; padding: 0;")
        self.sit_bar = MiniBar(S().accent_2, 3, self)
        self.sit_bar.setFixedWidth(96)
        self.sit_bar.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        sit_row.addWidget(self.sit_label, 0, Qt.AlignmentFlag.AlignVCenter)
        sit_row.addSpacing(8)
        sit_row.addWidget(self.sit_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.sit_hearts = HeartBar(invert=True, parent=self)
        self.sit_hearts.hide()
        sit_row.addWidget(self.sit_hearts, 0, Qt.AlignmentFlag.AlignVCenter)
        sit_row.addStretch(1)
        root.addLayout(sit_row)

        # 按当前风格决定用细条还是爱心
        hearts = S().hearts
        self.day_bar.setVisible(not hearts)
        self.sit_bar.setVisible(not hearts)
        self.day_hearts.setVisible(hearts)
        self.sit_hearts.setVisible(hearts)

    # ------------------------------------------------------------ 刷新

    def _place_cup(self) -> None:
        """杯子放在「距离下班」到久坐进度条之间的右侧，按素材比例竖着居中。"""
        if not hasattr(self, "cup"):
            return
        zone_top = self.caption.mapTo(self, QPoint(0, 0)).y()
        # 「久坐」这行文字两种风格里高度一样，用它当基准最稳；
        # 别用进度条/爱心，它们高度差 12px，会把杯子撑大
        zone_bottom = (
            self.sit_label.mapTo(self, QPoint(0, 0)).y() + self.sit_label.height()
        )
        width = 72
        height = max(40, int(round(width * self.cup.frame_aspect())))
        # 区域装不下就缩，别让杯子戳出卡片
        room = max(40, zone_bottom - zone_top)
        if height > room:
            height = room
            width = max(40, int(round(height / self.cup.frame_aspect())))
        top = zone_top + max(0, (room - height) // 2)
        left = self.width() - 16 - self._frame_margin() - width
        self.cup.set_rect(QRect(left, top, width, height))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_cup()

    def set_character_visible(self, visible: bool) -> None:
        """菜单里的「显示角色」：关掉就收起角色区，只留卡片。"""
        visible = bool(visible)
        if visible == self._show_char:
            return
        self._show_char = visible
        self._char_top = CARD_TOP if visible else 0
        self.setCursor(Qt.CursorShape.ArrowCursor)
        bottom = self.y() + self.height()
        self._apply_size()
        if self.layout() is not None:
            self.layout().activate()  # 先让布局算完，杯子位置才准
        self.move(self.x(), bottom - self.height())
        self._clamp_to_screen()
        self._place_cup()
        self.update()

    def apply_theme(self, theme_id: str) -> None:
        """运行中换主题：重载帧集 + 立刻按当前时段校正待机/吃饭表情。"""
        self.fish.use_theme(theme_id)
        self.refresh(self.engine.snapshot, 1.0)
        self.update()

    def refresh(self, snap: Snapshot, pulse: float = 1.0) -> None:
        self.fish.set_meal(self.engine.in_lunch(snap.now))
        now = snap.now
        weekday = WEEKDAY_CN[now.weekday()]
        self.date_label.setText(f"周{weekday} · {now.month}月{now.day}日")

        if snap.phase == REST:
            self.caption.setText("今天不用打卡")
            self.big.setFont(ui_font(26, QFont.Weight.DemiBold))
            self._style_big()
            self.big.setText("休息日")
            self.day_bar.set_value(0.0)
            self.day_hearts.set_value(0.0)
            self.dot.set_state(S().accent_2, 1.0)
        elif snap.phase == OFF:
            overtime = max(0, -snap.seconds_left)
            hours = overtime // 3600
            if hours >= 2:
                caption = "这么晚了 · 该回家了"
            elif overtime >= 30 * 60:
                caption = "还不走吗"
            else:
                caption = "今天已下班"
            self.caption.setText(caption)
            self.big.setFont(self._time_font(30))
            self._style_big(S().accent)
            self.big.setText(fmt_hms(overtime))
            self.day_bar.set_value(1.0)
            self.day_hearts.set_value(1.0)
            self.dot.set_state(S().accent, 1.0)
        else:
            self.caption.setText(S().work_label if snap.phase == WORK else "快下班了")
            self.big.setFont(self._time_font(30))
            self._style_big()
            self.big.setText(fmt_hms(snap.seconds_left))
            self.day_bar.set_value(snap.day_progress)
            self.day_hearts.set_value(snap.day_progress)
            if snap.phase == PRE:
                self.dot.set_state(S().accent, pulse)
            else:
                self.dot.set_state(S().accent_2, 0.72 + 0.28 * pulse)

        self.cup.set_state(snap.drink_ratio, snap.drink_cups, snap.drink_left,
                           snap.drink_state == "full")
        self._place_cup()
        # 久坐一行
        if not snap.sit_active:
            self.sit_label.setText(SIT_REASON_TEXT.get(snap.sit_reason, "计时暂停"))
            self.sit_label.setMinimumWidth(28)
            self.sit_label.setStyleSheet(f"color: {S().text_low}; padding: 0;")
            self.sit_bar.set_value(0.0)
            self.sit_hearts.set_value(0.0)
            self.sit_bar.setToolTip(SIT_REASON_TEXT.get(snap.sit_reason, "计时暂停"))
        else:
            minutes = int(snap.sit_minutes)
            target = max(5, snap.sit_target)
            ratio = snap.sit_minutes / target
            self.sit_label.setText("久坐")
            self.sit_label.setMinimumWidth(28)
            self.sit_bar.setToolTip(f"已坐 {minutes} 分钟 · 目标 {target} 分钟")
            if ratio >= 0.8:
                self.sit_label.setStyleSheet(f"color: {S().accent}; padding: 0;")
                self.sit_bar.set_color(S().accent)
            else:
                self.sit_label.setStyleSheet(f"color: {S().text_mid}; padding: 0;")
                self.sit_bar.set_color(S().accent_2)
            self.sit_bar.set_value(ratio)
            self.sit_hearts.set_value(ratio)

        # 水杯是直接画在卡片上的，不是独立控件：素材帧（0/25/50/75/100）一变，
        # 只改状态不整卡重画，杯子上就会留着上一档水位的旧像素，看起来像水分了层。
        # 这里统一整卡重画一次，一秒一次，开销可以忽略。
        self.update()

    # ------------------------------------------------------------ 定位

    def ensure_position(self) -> None:
        pos = self.cfg["pos"]
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            self.move(int(pos[0]), int(pos[1]))
            self._clamp_to_screen()
            return
        screen = self.screen() or self.parent()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.right() - self.width() - 22,
            area.bottom() - self.height() - 14,
        )

    def _clamp_to_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = min(max(self.x(), area.left() - 60), area.right() - self.width() + 60)
        y = min(max(self.y(), area.top() - self._top() + 30), area.bottom() - self.height() + 40)
        self.move(x, y)

    def remember_position(self) -> None:
        self.cfg["pos"] = [self.x(), self.y()]
        self.cfg.save()

    def apply_style(self) -> None:
        """切换风格后重新上色：底、文字、进度条、圆角都跟着变。"""
        st = S()
        self.setStyleSheet(style_mod.base_qss())
        self.date_label.setStyleSheet(f"color: {st.text_mid}; padding: 0;")
        self.caption.setStyleSheet(f"color: {st.text_low}; padding: 0;")
        self.caption.setFont(self._caption_font())
        self.caption.setFixedHeight(22 if st.pixel_font else 0)
        self._style_big()
        self.sit_label.setStyleSheet(f"color: {st.text_mid}; padding: 0;")
        self.day_bar.set_color(st.accent)
        self.sit_bar.set_color(st.accent_2)
        self.day_bar.setVisible(not st.hearts)
        self.sit_bar.setVisible(not st.hearts)
        self.day_hearts.setVisible(st.hearts)
        self.sit_hearts.setVisible(st.hearts)
        self.day_bar.update()
        self.sit_bar.update()
        target_h = self._top() + self._card_height() + self._frame_margin()
        target_w = 304 + 2 * self._frame_margin()
        if self.height() != target_h or self.width() != target_w:
            # 以底边为锚点改高度：卡片一般贴在屏幕右下角，往下长会顶出屏幕
            bottom = self.y() + self.height()
            self._apply_size()
            if self.layout() is not None:
                self.layout().activate()
            self.move(self.x(), bottom - target_h)
            self._clamp_to_screen()
            self._place_cup()
        self.update()

    # ------------------------------------------------------------ 绘制

    # 银灰渐变 + 圆角金属边框
    def _silver(self, rect: QRectF, flip_x: bool = False, flip_y: bool = False):
        a = QPointF(
            rect.right() if flip_x else rect.left(),
            rect.bottom() if flip_y else rect.top(),
        )
        b = QPointF(
            rect.left() if flip_x else rect.right(),
            rect.top() if flip_y else rect.bottom(),
        )
        grad = QLinearGradient(a, b)
        grad.setColorAt(0.0, QColor("#FFFFFF"))
        grad.setColorAt(0.26, QColor("#D2DAEC"))
        grad.setColorAt(0.52, QColor("#7E89A8"))
        grad.setColorAt(0.74, QColor("#DCE3F3"))
        grad.setColorAt(1.0, QColor("#F5F8FF"))
        return grad

    def _paint_pixel_frame(self, painter, rect: QRectF) -> None:
        st = S()
        outline = QColor("#20263F")
        inner = QColor("#151A2E")
        pane = QColor(st.bg)

        painter.save()
        # 像素金属：关掉抗锯齿，圆角自然变成阶梯边
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)

        outline = QColor("#1B2340")
        band = QColor("#C2CEE8")
        hi = QColor("#E9EFFC")
        shade = QColor("#8B96B8")
        inner = QColor("#161B30")
        pane = QColor(st.bg)

        painter.setBrush(outline)
        painter.drawRoundedRect(rect, 10, 10)
        painter.setBrush(band)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 9, 9)

        # 2px 倒角：上/左高光，下/右投影
        painter.setBrush(hi)
        painter.drawRect(QRectF(rect.left() + 2, rect.top() + 2, rect.width() - 4, 2))
        painter.drawRect(QRectF(rect.left() + 2, rect.top() + 2, 2, rect.height() - 4))
        painter.setBrush(shade)
        painter.drawRect(
            QRectF(rect.left() + 2, rect.bottom() - 4, rect.width() - 4, 2)
        )
        painter.drawRect(
            QRectF(rect.right() - 4, rect.top() + 2, 2, rect.height() - 4)
        )

        # 内暗线 + 面板
        painter.setBrush(inner)
        painter.drawRoundedRect(rect.adjusted(7, 7, -7, -7), 6, 6)
        inner_rect = rect.adjusted(9, 9, -9, -9)
        if st.dither or st.scanlines:
            painter.setBrush(pane)
            painter.drawRoundedRect(inner_rect, 5, 5)
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(inner_rect, 5, 5)
            painter.setClipPath(clip)
            if st.dither:
                tile = QPixmap(2, 2)
                tile.fill(pane)
                tp = QPainter(tile)
                light = pane.lighter(142)
                tp.fillRect(0, 0, 1, 1, light)
                tp.fillRect(1, 1, 1, 1, light)
                tp.end()
                painter.setBrush(QBrush(tile))
                painter.drawRect(inner_rect)
            if st.scanlines:
                painter.setPen(QPen(QColor(0, 0, 0, 22), 1))
                y = int(inner_rect.top())
                while y < inner_rect.bottom():
                    painter.drawLine(
                        QPointF(inner_rect.left(), y), QPointF(inner_rect.right(), y)
                    )
                    y += 4
            painter.restore()
        else:
            painter.setBrush(pane)
            painter.drawRoundedRect(inner_rect, 5, 5)

        out = 4
        cap = 26
        # 文件名就是角落位置，直接按名字放
        spots = (
            ("top_left", rect.left() - out, rect.top() - out),
            ("top_right", rect.right() - (cap - out), rect.top() - out),
            ("bottom_left", rect.left() - out, rect.bottom() - (cap - out)),
            ("bottom_right", rect.right() - (cap - out), rect.bottom() - (cap - out)),
        )
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        for name, x, y in spots:
            pix = _corner_pix(name)
            if pix.isNull():
                continue
            painter.drawPixmap(QPointF(x, y), pix)

        # 底部中央装饰：直接用素材，1:1 不缩放，压在底边上
        mid = rect.center().x()
        base = rect.bottom() - 4
        orn = _ornament_pix()
        if not orn.isNull():
            painter.drawPixmap(
                QPointF(mid - orn.width() / 2, base - orn.height() / 2), orn
            )

        painter.restore()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 1. 先画小肥鱼（她会被下面的卡片挡住下半身）
        if getattr(self, "_show_char", True):
            self.fish.draw(painter, self.width() / 2, 0)

        # 2. 再画卡片，盖住鱼的下半身
        st = S()
        m = self._frame_margin()
        rect = QRectF(
            m + 0.5, self._top() + 0.5, self.width() - 2 * m - 1, self._card_height() - 1
        )
        painter.setBrush(QColor(st.bg))
        if st.frame:
            self._paint_pixel_frame(painter, rect)
        else:
            painter.setPen(QPen(card_border(self._hover), 1))
            painter.drawRoundedRect(rect, st.radius, st.radius)

        # 3. 最后画水杯（和背景同一趟绘制，不会被盖出残影）
        self.cup.paint(painter)

    def _on_fish_tick(self) -> None:
        if not getattr(self, "_show_char", True):
            return
        self.fish.tick(0.033)
        cursor = self.mapFromGlobal(QCursor.pos())
        self.fish.set_look(
            (cursor.x() - self.width() / 2) / 90.0, (cursor.y() - FISH_CY) / 90.0
        )
        hovering = self._in_fish(cursor)
        if hovering and not self._hovering:
            self.fish.hover_start()  # 光标刚到角色身上：亮一下表情 17
        self._hovering = hovering
        if hovering:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        self.cup.tick(0.033)
        area = QRect(0, 0, self.width(), self._top())
        if self.cup.bobbing():
            # 满水时杯子上下浮动，绘制会超出 rect 几个像素，重绘区域留点余量
            area = area.united(self.cup.rect().adjusted(-2, -4, 2, 4))
        self.update(area)

    def _in_fish(self, pos: QPoint) -> bool:
        if not getattr(self, "_show_char", True):
            return False
        if pos.y() > self._top() - 4:
            return False
        dx = (pos.x() - self.width() / 2) / 86.0
        dy = (pos.y() - FISH_CY) / 86.0
        return dx * dx + dy * dy <= 1.0

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    # ------------------------------------------------------------ 交互

    def set_update_available(self, available: bool) -> None:
        """有新版本时在日期和天气之间亮起红色提示。"""
        if not hasattr(self, "update_badge"):
            return
        if available:
            self.update_badge.show()
        else:
            self.update_badge.hide()

    def _emit_menu(self) -> None:
        self.request_menu.emit(self.more_btn.mapToGlobal(QPoint(0, self.more_btn.height())))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if self._in_fish(pos):
            # 角色身上按下：只做长按拎起，不拖窗口（拖动只能从卡片里拖）
            self._drag_offset = None
            self._press_at = time.monotonic()
            self._long_timer.start()
            event.accept()
            return
        self._drag_offset = (
            event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        )
        self._dragged = False
        self._last_move_t = time.monotonic()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            target = event.globalPosition().toPoint() - self._drag_offset
            dx = target.x() - self.x()
            dy = target.y() - self.y()
            if not self._dragged:
                # 抖一下不算拖动，避免「点一下就挪了位置」
                if abs(dx) + abs(dy) <= 3:
                    return
                self._dragged = True
                self.fish.begin_drag()
            self.move(target)
            now = time.monotonic()
            dt = max(0.008, now - getattr(self, "_last_move_t", now))
            self._last_move_t = now
            self.fish.drag_step(dx, dy, dt)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._long_timer.isActive():
            self._long_timer.stop()
        if getattr(self, "_lifting", False):
            self._lifting = False
            self.fish.lift_release()
        if self._drag_offset is not None:
            was_dragged = self._dragged
            self._drag_offset = None
            self._dragged = False
            if was_dragged:
                self.fish.end_drag()
                self.remember_position()
            event.accept()

    def _on_long_press(self) -> None:
        self.fish.lift()
        self._lifting = True

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        # 双击不再打开设置（统一走 ⋯ 菜单 / 托盘菜单），
        # 这里吞掉事件，避免第二次按下再走一遍点击流程
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.request_menu.emit(event.globalPos())

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self.moved.emit()
