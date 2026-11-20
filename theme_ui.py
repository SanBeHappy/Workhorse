"""对话框：无边框深色基类 + 更新提示窗。

（角色主题的管理与编辑界面已移除，角色固定使用内置形象。）
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import update
from theme import (
    BASE_QSS,
    BG,
    BG_INPUT,
    BG_RAISED,
    MINT,
    ORANGE,
    SETTINGS_QSS,
    TEXT_HI,
    TEXT_LOW,
    TEXT_MID,
    THEME_UI_QSS,
    ui_font,
)

DIALOG_QSS = BASE_QSS + SETTINGS_QSS + THEME_UI_QSS


class DarkDialog(QDialog):
    """无边框圆角深色窗口，标题栏区域可拖动。"""

    def __init__(
        self,
        title: str,
        width: int,
        height: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(DIALOG_QSS)
        self.setFixedWidth(width)
        self._drag_at = None

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(26, 17, 26, 20)
        self._root.setSpacing(0)
        self._root.addLayout(self._header(title))
        self._root.addSpacing(12)
        self._root.addWidget(self._divider())
        self._root.addSpacing(10)

        self._content = QVBoxLayout()
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(0)
        self._root.addLayout(self._content, 1)

        if height:
            self.setFixedHeight(height)
        else:
            self.adjustSize()

    # ---- 结构 ----

    def body(self) -> QVBoxLayout:
        return self._content

    def _header(self, title: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setFont(ui_font(15, QFont.Weight.DemiBold))
        label.setStyleSheet(f"color: {TEXT_HI}; padding: 0;")
        close = QPushButton("×")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFixedSize(26, 26)
        close.setFont(ui_font(19))
        close.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #6B717C;"
            " border-radius: 13px; padding-bottom: 4px; }"
            "QPushButton:hover { background: rgba(255,255,255,22); color: #F2F3F5; }"
        )
        close.clicked.connect(self.reject)
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(close)
        return row

    def _divider(self) -> QWidget:
        line = QWidget(self)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(255,255,255,18);")
        return line

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        label.setFont(ui_font(11))
        label.setStyleSheet(f"color: {TEXT_LOW}; padding: 0; letter-spacing: 1px;")
        return label

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(ui_font(11))
        label.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
        return label

    def _primary(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("primary")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _ghost(self, text: str, width: int = 0) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("mini")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(28)
        if width:
            btn.setFixedWidth(width)
        return btn

    # ---- 外框 ----

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(QColor(255, 255, 255, 34))
        painter.setBrush(QColor(BG))
        painter.drawRoundedRect(rect, 16, 16)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 50:
            self._drag_at = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_at is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_at)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_at = None
        super().mouseReleaseEvent(event)


class UpdateDialog(DarkDialog):
    """发现新版本时先看更新日志，再决定去不去。"""

    def __init__(self, version: str, current: str, notes: list[str], parent=None) -> None:
        super().__init__("发现新版本", 440, parent=parent)
        self._version = version
        body = self.body()

        head = QHBoxLayout()
        big = QLabel(f"v{version}")
        big.setFont(ui_font(24, QFont.Weight.DemiBold))
        big.setStyleSheet(f"color: {MINT}; padding: 0;")
        head.addWidget(big)
        head.addSpacing(10)
        head.addWidget(self._hint(f"你现在用的是 v{current}"), 0, Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        body.addLayout(head)
        body.addSpacing(14)

        body.addWidget(self._section("更新内容"))
        body.addSpacing(9)

        if notes:
            for note in notes[:6]:
                item = QLabel(f"·  {note}")
                item.setWordWrap(True)
                item.setFont(ui_font(12))
                item.setStyleSheet(f"color: {TEXT_MID}; padding: 0;")
                body.addWidget(item)
                body.addSpacing(5)
        else:
            body.addWidget(self._hint("这次没写更新说明，去仓库看看提交记录。"))

        self.status = QLabel("")
        self.status.setFont(ui_font(11))
        self.status.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
        body.addWidget(self.status)
        body.addSpacing(10)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.later = self._ghost("以后再说", 92)
        self.later.clicked.connect(self.reject)
        self.go = self._primary("立即更新")
        self.go.clicked.connect(self._start_download)
        footer.addWidget(self.later)
        footer.addSpacing(8)
        footer.addWidget(self.go)
        body.addLayout(footer)
        self.adjustSize()

        self._downloader = None
        self._proc = None
        self._stamp = 0.0
        self._waited = 0
        self._watch: QTimer | None = None
        self.before_apply = None      # 替换前调用（让出单实例锁）
        self.after_fail = None        # 回滚后调用（把锁拿回来）

    def _start_download(self) -> None:
        if not update.can_self_update():
            self.status.setText("开发模式下不支持自动更新")
            self.status.setStyleSheet(f"color: {ORANGE}; padding: 0;")
            return
        self.go.setEnabled(False)
        self.go.setText("下载中")
        self.later.setEnabled(False)
        self.status.setText("正在连接…")
        self.status.setStyleSheet(f"color: {TEXT_MID}; padding: 0;")

        self._downloader = update.UpdateDownloader()
        self._downloader.progress.connect(self._on_progress)
        self._downloader.finished.connect(self._on_downloaded)
        self._downloader.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = min(100, int(done * 100 / total))
            self.status.setText(f"正在下载 {pct}%  ·  {done / 1048576:.1f} / {total / 1048576:.1f} MB")
        else:
            self.status.setText(f"正在下载  ·  {done / 1048576:.1f} MB")

    def _on_downloaded(self, path: str, error: str) -> None:
        if error:
            self._retry(error)
            return

        if callable(self.before_apply):
            try:
                self.before_apply()
            except Exception:
                pass
        stamp = time.time()
        ok, msg, proc = update.apply_update(Path(path), version=self._version)
        if not ok:
            if callable(self.after_fail):
                try:
                    self.after_fail()      # 替换没成功，把单实例锁拿回来
                except Exception:
                    pass
            self._retry(msg)
            return

        self._proc = proc
        self._stamp = stamp
        self.go.setEnabled(False)
        self.go.setText("重启中")
        self.later.setEnabled(False)
        self.status.setText("新版本已就位，正在重启…")
        self.status.setStyleSheet(f"color: {TEXT_MID}; padding: 0;")

        # 目录模式没法在运行中替换自己所在的文件夹：更新脚本会等本进程退出后
        # 再换目录并拉起新版，所以这里只管退出，不再等新进程的启动标记。
        QTimer.singleShot(800, QApplication.instance().quit)

    def _retry(self, message: str) -> None:
        self.status.setText(message)
        self.status.setStyleSheet(f"color: {ORANGE}; padding: 0;")
        self.go.setEnabled(True)
        self.go.setText("重试")
        self.later.setEnabled(True)
        self._watch = None


# ---------------------------------------------------------------- 简易确认框


