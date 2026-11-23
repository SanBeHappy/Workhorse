"""到点自动关机：按设定的星期和时间关机，关机前 5 分钟先提醒一次。

只在下面两种情况真的执行：
  · 命中选中的星期 + 时间点；
  · 当前时间距离目标时间不超过 60 秒（避免电脑睡眠/关机一阵后醒来，
    开机瞬间被补一次关机）。

提醒过一次就记在内存里，同一天不会重复弹；用户点「今晚不关」会把日期写进
配置的 shutdown_skip_date，当天彻底跳过。
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

WARN_BEFORE = 5 * 60          # 关机前 5 分钟提醒
LATE_GRACE = 60               # 晚于目标时间超过这个秒数就不补关了
ENV_DRY_RUN = "DESKMATE_NO_SHUTDOWN"
COMMENT = "DeskMate: scheduled shutdown"


def parse_hhmm(value, fallback: str = "21:30") -> tuple[int, int]:
    """把 "21:30" / "2130" / "21" 解析成 (时, 分)，坏值回落到 fallback。"""
    text = str(value or "").strip().replace("：", ":")
    try:
        if ":" in text:
            left, _, right = text.partition(":")
            hour = int(left) if left else 0
            minute = int(right) if right else 0
        elif len(text) >= 3:
            hour, minute = int(text[:-2]), int(text[-2:])
        elif text:
            hour, minute = int(text), 0
        else:
            raise ValueError(text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(text)
        return hour, minute
    except (TypeError, ValueError):
        return parse_hhmm(fallback, "21:30") if fallback != value else (21, 30)


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _initiate_shutdown(seconds: int) -> tuple[bool, str]:
    """用 InitiateShutdownW 直接下达关机，不经过 shutdown.exe 的关机原因对话框。

    shutdown.exe 带 /d p:0:0 时，某些机器（组策略要求填写关机原因、或有多用户登录）
    会弹出「关闭 Windows / 注销」的选择框等用户点确认，窗口一被关掉关机就没了，
    而命令本身早就返回 0，日志里就变成了「成功但没关」。
    API 调用把原因直接写进参数，系统不会再弹框。
    """
    import ctypes
    from ctypes import wintypes

    try:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        func = advapi.InitiateShutdownW
    except Exception as exc:  # noqa: BLE001
        return False, f"advapi32 不可用：{exc}"

    func.argtypes = [
        wintypes.LPCWSTR,   # lpMachineName
        wintypes.LPCWSTR,   # lpMessage
        wintypes.DWORD,     # dwGracePeriod
        wintypes.DWORD,     # dwShutdownFlags
        wintypes.DWORD,     # dwReason
    ]
    func.restype = wintypes.DWORD

    SHUTDOWN_FORCE_OTHERS = 0x00000001
    SHUTDOWN_FORCE_SELF = 0x00000002
    SHTDN_REASON_MAJOR_OTHER = 0x00000000
    SHTDN_REASON_FLAG_PLANNED = 0x80000000

    code = func(
        None,
        COMMENT,
        int(seconds),
        SHUTDOWN_FORCE_OTHERS | SHUTDOWN_FORCE_SELF,
        SHTDN_REASON_MAJOR_OTHER | SHTDN_REASON_FLAG_PLANNED,
    )
    if code == 0:
        return True, f"{seconds} 秒后关机"
    hint = {
        5: "权限不足（可能需要管理员）",
        1314: "缺少关机特权",
        1190: "已有一次关机在排队",
        1115: "关机会话不可用",
    }.get(code, "")
    return False, f"InitiateShutdown 返回 {code}" + (f"（{hint}）" if hint else "")


def perform_shutdown(seconds: int = 30) -> tuple[bool, str]:
    """真正执行关机；带 30 秒缓冲，这段时间里 shutdown /a 还能取消。

    先走 Win32 API（不会弹关机原因框），失败再退回 shutdown.exe；
    两条路都可能被系统策略拦下，所以返回值只在系统明确受理时才是 True。
    """
    if os.environ.get(ENV_DRY_RUN):
        return False, "dry-run（DESKMATE_NO_SHUTDOWN 已设置，没有真的关机）"
    if sys.platform != "win32":
        return False, "只支持 Windows"

    ok, msg = _initiate_shutdown(seconds)
    if ok:
        return True, msg

    try:
        proc = subprocess.run(
            [
                "shutdown",
                "/s",
                "/f",
                "/t",
                str(int(seconds)),
                "/c",
                COMMENT,
            ],
            capture_output=True,
            creationflags=_no_window(),
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"{msg}；调用 shutdown 也失败：{exc}"
    if proc.returncode == 0:
        return True, f"{seconds} 秒后关机（走 shutdown.exe）"
    detail = (proc.stderr or proc.stdout or b"").decode("mbcs", "ignore").strip()
    return False, f"{msg}；shutdown.exe：{detail or proc.returncode}"


def cancel_pending() -> bool:
    """撤销已经下达、还在倒计时里的关机。"""
    if os.environ.get(ENV_DRY_RUN) or sys.platform != "win32":
        return False
    try:
        proc = subprocess.run(
            ["shutdown", "/a"], capture_output=True, creationflags=_no_window(), timeout=10
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


class ShutdownScheduler:
    """由主循环每 tick 调一次 check()，返回 warn / run / None。"""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._warned_date = ""
        self._fired_date = ""

    # ------------------------------------------------------------ 状态

    def enabled(self) -> bool:
        return bool(self.cfg["shutdown_enabled"])

    def days(self) -> list[int]:
        value = self.cfg["shutdown_days"]
        return list(value) if isinstance(value, (list, tuple)) else []

    def target_time(self) -> str:
        hour, minute = parse_hhmm(self.cfg["shutdown_time"])
        return f"{hour:02d}:{minute:02d}"

    def skipped_today(self, now: datetime) -> bool:
        return (self.cfg["shutdown_skip_date"] or "") == now.strftime("%Y-%m-%d")

    def target_of(self, now: datetime) -> datetime | None:
        """今天该不该关机、该在几点关；不该关返回 None。"""
        if not self.enabled() or now.weekday() not in self.days():
            return None
        if self.skipped_today(now):
            return None
        hour, minute = parse_hhmm(self.cfg["shutdown_time"])
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def skip_today(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        self.cfg["shutdown_skip_date"] = now.strftime("%Y-%m-%d")
        self.cfg.save()
        cancel_pending()

    # ------------------------------------------------------------ 判定

    def check(self, now: datetime) -> str | None:
        target = self.target_of(now)
        if target is None:
            return None
        key = now.strftime("%Y-%m-%d")
        delta = (target - now).total_seconds()

        if self._warned_date != key and 0 < delta <= WARN_BEFORE:
            self._warned_date = key
            return "warn"
        if self._fired_date != key and -LATE_GRACE <= delta <= 0:
            self._fired_date = key
            return "run"
        return None

    def fire(self) -> tuple[bool, str]:
        return perform_shutdown(30)
