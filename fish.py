"""DeepSeek「蓝色大肥鱼」Q 版形象（图片驱动版）。

素材位于 assets/char/，由两张精灵表切分并抠去白底：
- 01~06 站立表情差分
- 07~12 拖拽时的摔倒序列

角色不是独立窗口——由 MainCard 在自绘时先画角色、再画卡片，
于是角色的下半身被卡片自然挡住，形成「从窗口后面抱住窗口」的效果。
"""

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap

import char_theme

# ---------------------------------------------------------------- 资源

CHAR_BOX = 188.0          # 角色绘制方框边长（素材是正方形）
CHAR_TOP = 2.0            # 方框在窗口里的顶部 y

IDLE_EXPR = "14_cheek"      # 平常就趴在窗口上托腮

# 长按拎起：按住 3 秒，随机给一张「被拎起来」的表情
LIFT_FRAMES = (
    "19_shock",
    "20_struggle",
    "21_blank",
    "22_dizzy",
    "23_angry",
    "24_cry",
)
LIFT_HOLD = 3.0

# 久坐提醒：第 1/2/3+ 次分别用不同表情，每次都停 3 秒
SIT_EXPRS = ("05_wave", "01_angry", "02_confused")
SIT_HOLD = 3.0

# 待机表情：随时间递进，鼠标移上来打断一次
IDLE_SOFT_EXPR = "18_lean"     # 5 分钟没人理
IDLE_LONG_EXPR = "16_nap"      # 20 分钟没人理
HOVER_EXPR = "17_wow"          # 鼠标移到角色身上
IDLE_SOFT_AFTER = 300.0        # 5 分钟
IDLE_LONG_AFTER = 1200.0       # 20 分钟
HOVER_HOLD = 5.0               # 鼠标停留时显示 5 秒，然后重新开始

MEAL_EARLY = ("31_cook", "32_scoop", "33_serve")     # 开锅 → 盛饭 → 捧碗
MEAL_LATE = ("34_feast", "35_eat", "36_full")        # 猛吃 → 扒饭 → 吃撑
MEAL_EARLY_STEP = 1.6      # 前段每张停这么久
MEAL_LATE_STEP = 1.3       # 后段吃得更快
MEAL_SWITCH = 120.0        # 午休开始 2 分钟后切换

DRINK_FRAMES = (
    "37_hold_cup",
    "38_raise",
    "39_sip",
    "40_gulp",
    "41_ahh",
    "42_done",
)
DRINK_STEP = 0.34      # 每帧停留，六帧约 2 秒

DURATION = {
    "hop": 0.78,
    "wave": 2.6,
    "lift": LIFT_HOLD,
    "drink": DRINK_STEP * len(DRINK_FRAMES),
}

# 个别帧需要整体偏移，免得关键部位被卡片切掉
EXPR_OFFSET = {
    "09_faceplant": -20.0,   # 趴地时把脸抬出来
    "08_tumble": -6.0,
}

# 拖动时按时间顺序切帧：小碎步 → 踉跄 → 拖飞
DRAG_FRAMES = ("07_stumble", "08_tumble", "09_faceplant")
DRAG_STAGE_STEP = 1.4      # 每张停 1.4 秒
DRAG_HOLD = 5.0            # 停在拖飞帧 5 秒后，窗口不再动就回待机


def _heart_path(size: float) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(0, size * 0.42)
    path.cubicTo(-size * 0.62, -size * 0.1, -size * 0.34, -size * 0.62, 0, -size * 0.22)
    path.cubicTo(size * 0.34, -size * 0.62, size * 0.62, -size * 0.1, 0, size * 0.42)
    return path


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    total: float
    kind: str
    size: float
    spin: float = 0.0


class FishState:
    """小肥鱼状态机：表情、动作变换、拖拽反应、粒子。"""

    def __init__(self, theme_id: str = char_theme.BUILTIN_ID) -> None:
        self.theme_id = char_theme.BUILTIN_ID
        self.frames: dict[str, QPixmap] = {}
        self.idle_expr = IDLE_EXPR
        self.expr = IDLE_EXPR
        self.t = 0.0
        self.action: str | None = None
        self.action_start = 0.0
        self.action_duration = 1.0
        self.particles: list[Particle] = []
        self.happy = 0.0

        self.meal = False
        self.meal_start = 0.0
        self.dragging = False
        self.drag_t = 0.0
        self._idle_since = 0.0        # 这轮待机从什么时候开始算
        self._hover_until = 0.0       # 鼠标停留表情到期时间
        self._drag_hold_until = 0.0   # 拖飞帧的 5 秒停留到期时间
        self._lifting = False         # 被拎在手里（松手才放下来）
        self.use_theme(theme_id)

    def use_theme(self, theme_id: str) -> None:
        """切换角色主题。帧集换了，正在播放的动作作废。"""
        frames = char_theme.load_frames(theme_id)
        if not frames:                 # 素材全丢时保留旧图，别黑屏
            return
        self.theme_id = char_theme.resolve(theme_id)
        self.frames = frames

        self.action = None             # 播到一半的动作作废，避免帧映射错位
        self.happy = 0.0
        self.particles.clear()
        # dragging 不动：卡片那边 _drag_offset 还在，擅自复位会状态错步

        if self.idle_expr not in frames:
            self.idle_expr = IDLE_EXPR if IDLE_EXPR in frames else next(iter(frames), "")
        if not self.dragging:
            self.expr = self._meal_frame() if self.meal else self.idle_expr

    # ------------------------------------------------------------ 驱动

    def tick(self, dt: float) -> None:
        self.t += dt

        if self.action == "drink":
            elapsed = self.t - self.action_start
            index = int(elapsed / DRINK_STEP)
            self.expr = DRINK_FRAMES[min(len(DRINK_FRAMES) - 1, index)]

        if self.action and self.t - self.action_start >= self.action_duration:
            self.action = None

        if self.happy > 0:
            self.happy = max(0.0, self.happy - dt * 1.2)

        # 鼠标停留：显示 5 秒，到点后重新开始一轮待机
        if self._hover_until:
            if self.t < self._hover_until:
                if not self.action and not self.dragging:
                    self.expr = HOVER_EXPR
            else:
                self._hover_until = 0.0
                self._idle_since = self.t

        # 拖飞帧：窗口停下 5 秒后回待机
        if self._drag_hold_until and not self.dragging and self.t >= self._drag_hold_until:
            self._drag_hold_until = 0.0
            self._idle_since = self.t

        if not self.action and not self.dragging and not self._hover_until and not self._lifting:
            if self._drag_hold_until:
                self.expr = DRAG_FRAMES[-1]
            else:
                self.expr = self._meal_frame() if self.meal else self._idle_frame()

        alive: list[Particle] = []
        for p in self.particles:
            p.life -= dt
            if p.life <= 0:
                continue
            if p.kind == "drop":
                p.vy += 210 * dt
                p.vx *= 0.985
            elif p.kind == "heart":
                p.vx *= 0.97
                p.vy *= 0.985
            p.x += p.vx * dt
            p.y += p.vy * dt
            alive.append(p)
        self.particles = alive

    def _idle_frame(self) -> str:
        """待机表情随时间递进：14 → 18（5 分钟）→ 16（20 分钟）。"""
        waited = self.t - self._idle_since
        if waited >= IDLE_LONG_AFTER:
            return IDLE_LONG_EXPR
        if waited >= IDLE_SOFT_AFTER:
            return IDLE_SOFT_EXPR
        return IDLE_EXPR

    def hover_start(self) -> None:
        """光标刚移到角色身上：亮一下表情 17，停留 5 秒。"""
        if self.dragging or self._lifting:
            return
        self._hover_until = self.t + HOVER_HOLD
        self._drag_hold_until = 0.0
        self.expr = HOVER_EXPR

    def set_look(self, dx: float, dy: float) -> None:
        """素材表情固定，保留接口但不再使用。"""

    # ------------------------------------------------------------ 拖拽

    def begin_drag(self) -> None:
        self.dragging = True
        self.drag_t = 0.0
        self.action = None
        self._hover_until = 0.0
        self._drag_hold_until = 0.0
        self.expr = DRAG_FRAMES[0]

    def drag_step(self, dx: float, dy: float, dt: float) -> None:
        if not self.dragging:
            return
        # 按拖动时长顺序切帧：小碎步 → 踉跄 → 拖飞，跟手速无关
        self.drag_t += dt
        stage = min(len(DRAG_FRAMES) - 1, int(self.drag_t / DRAG_STAGE_STEP))
        self.expr = DRAG_FRAMES[stage]

    def end_drag(self) -> None:
        if not self.dragging:
            return
        self.meal = False
        self.meal_start = 0.0
        self.dragging = False
        # 停在拖飞帧：5 秒内窗口不再动就回待机（拖得短就直接回去）
        if self.expr == DRAG_FRAMES[-1]:
            self._drag_hold_until = self.t + DRAG_HOLD
        else:
            self._idle_since = self.t

    def set_meal(self, active: bool) -> None:
        """午休时段：开始吃饭。"""
        if active and not self.meal:
            self.meal_start = self.t
        self.meal = active

    def _meal_frame(self) -> str:
        elapsed = self.t - self.meal_start
        if elapsed < MEAL_SWITCH:
            return MEAL_EARLY[int(elapsed / MEAL_EARLY_STEP) % len(MEAL_EARLY)]
        idx = int((elapsed - MEAL_SWITCH) / MEAL_LATE_STEP) % len(MEAL_LATE)
        return MEAL_LATE[idx]

    def lift(self) -> None:
        """长按 3 秒：随机亮一张被拎起来的表情，一直举着，松手才放下。"""
        if self.dragging:
            return
        self.action = None
        self._lifting = True
        self._hover_until = 0.0
        self.expr = random.choice(LIFT_FRAMES)

    def lift_release(self) -> None:
        """松手：放下来，回到待机（重新计时）。"""
        if not self._lifting:
            return
        self._lifting = False
        self._idle_since = self.t
        self.expr = self._meal_frame() if self.meal else IDLE_EXPR

    def sit_remind(self, count: int = 1) -> None:
        """久坐提醒：第 1 次招手，第 2 次生气，第 3 次之后一脸懵。"""
        index = max(0, min(len(SIT_EXPRS) - 1, int(count) - 1))
        self.action = "wave"
        self.action_start = self.t
        self.action_duration = SIT_HOLD
        self.expr = SIT_EXPRS[index]

    def react(self, kind: str) -> None:
        """外部事件让角色做个反应：sit=起身提醒，off=下班。"""
        if kind == "sit":
            self.action = "wave"
            self.action_start = self.t
            self.action_duration = DURATION["wave"]
            self.expr = "05_wave"
        elif kind == "drink":
            self.action = "drink"
            self.action_start = self.t
            self.action_duration = DURATION["drink"]
            self.expr = DRINK_FRAMES[0]
        elif kind == "off":
            self.action = "hop"
            self.action_start = self.t
            self.action_duration = DURATION["hop"] * 1.6
            self.expr = "06_laugh"

    def _progress(self) -> float:
        if not self.action:
            return 0.0
        return max(0.0, min(1.0, (self.t - self.action_start) / self.action_duration))

    # ------------------------------------------------------------ 粒子

    def _spawn_hearts(self) -> None:
        for _ in range(7):
            self.particles.append(
                Particle(
                    x=random.uniform(-42, 42),
                    y=random.uniform(-56, -20),
                    vx=random.uniform(-16, 16),
                    vy=random.uniform(-50, -28),
                    life=1.1,
                    total=1.1,
                    kind="heart",
                    size=random.uniform(7, 11),
                )
            )

    def _spawn_drops(self) -> None:
        for _ in range(12):
            self.particles.append(
                Particle(
                    x=random.uniform(-4, 4),
                    y=-72,
                    vx=random.uniform(-26, 26),
                    vy=random.uniform(-92, -58),
                    life=1.3,
                    total=1.3,
                    kind="drop",
                    size=random.uniform(2.6, 5.2),
                )
            )

    def _spawn_sparks(self) -> None:
        for _ in range(6):
            angle = random.uniform(0, math.tau)
            radius = random.uniform(52, 70)
            self.particles.append(
                Particle(
                    x=math.cos(angle) * radius,
                    y=math.sin(angle) * radius,
                    vx=math.cos(angle) * 30,
                    vy=math.sin(angle) * 30,
                    life=0.7,
                    total=0.7,
                    kind="spark",
                    size=random.uniform(2.6, 4.6),
                    spin=random.uniform(-6, 6),
                )
            )

    # ------------------------------------------------------------ 绘制

    def draw(self, painter: QPainter, cx: float, cy: float) -> None:
        progress = self._progress()
        rot = 0.0
        sx = 1.0
        sy = 1.0
        dy = 0.0

        breathe = 1 + 0.014 * math.sin(self.t * 2.0)
        hover = 1.04 if (self._hover_until and not self.dragging) else 1.0
        sx *= breathe * hover
        sy *= breathe * hover
        dy += 1.6 * math.sin(self.t * 1.6)

        if self.dragging:
            # 被拖着走时东倒西歪
            intensity = min(1.0, self.drag_t / (DRAG_STAGE_STEP * 2))
            rot = 7 * intensity * math.sin(self.t * 19)
            dy -= 3 * intensity * abs(math.sin(self.t * 13))
        elif self.action == "hop":
            lift = math.sin(math.pi * progress)
            dy -= 26 * lift
            sy *= 1 + 0.05 * lift
            sx *= 1 - 0.04 * lift
            if progress > 0.86:
                squash = (progress - 0.86) / 0.14
                sy *= 1 - 0.08 * math.sin(math.pi * squash)
                sx *= 1 + 0.07 * math.sin(math.pi * squash)
        elif self.action == "lift":
            rise = min(1.0, progress * 4.0)
            dy -= 14 * rise
            rot = 3.5 * math.sin(self.t * 9) * rise
        elif self.action == "wave":
            dy -= 2.5 * abs(math.sin(progress * math.pi * 2))
        elif self.action == "dizzy":
            rot = 7 * math.sin(progress * math.pi * 6) * (1 - progress * 0.5)

        self._draw_particles(painter, cx)

        pix = self.frames.get(self.expr)
        if pix is None or pix.isNull():
            return

        box = CHAR_BOX
        center_y = CHAR_TOP + box / 2 + dy + EXPR_OFFSET.get(self.expr, 0.0)
        target = QRectF(
            cx - box * sx / 2,
            center_y - box * sy / 2,
            box * sx,
            box * sy,
        )

        painter.save()
        if rot:
            painter.translate(cx, center_y)
            painter.rotate(rot)
            painter.translate(-cx, -center_y)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(target, pix, QRectF(pix.rect()))
        painter.restore()

    def _draw_particles(self, painter: QPainter, cx: float) -> None:
        base = CHAR_TOP + CHAR_BOX / 2
        for p in self.particles:
            ratio = max(0.0, p.life / p.total)
            if p.kind == "heart":
                painter.setBrush(QColor(255, 122, 158, int(235 * ratio)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.save()
                painter.translate(cx + p.x, base + p.y)
                painter.scale(ratio * 1.1, ratio * 1.1)
                painter.drawPath(_heart_path(p.size))
                painter.restore()
            elif p.kind == "drop":
                painter.setBrush(QColor(150, 205, 250, int(220 * ratio)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(
                    QPointF(cx + p.x, base + p.y), p.size * ratio, p.size * ratio
                )
            else:
                painter.setBrush(QColor(255, 228, 140, int(230 * ratio)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.save()
                painter.translate(cx + p.x, base + p.y)
                painter.rotate(p.spin * (1 - ratio) * 40)
                painter.drawPath(_heart_path(p.size * ratio))
                painter.restore()
