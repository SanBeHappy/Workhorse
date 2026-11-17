"""下班收尾：关掉微信 → 回到桌面 → 关闭显示器。

三步都是系统级操作，失败不抛异常，统一返回 (是否成功, 说明)，由调用方写日志。
自动关机的那天不执行这一套（见 main._maybe_wrapup）。
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

# 微信 4.x 是 Weixin.exe，3.x 是 WeChat.exe，两个都试
WECHAT_PROCESSES = (
    "Weixin.exe",        # 微信 4.x 主进程
    "WeChat.exe",        # 微信 3.x 主进程
    "WeChatAppEx.exe",   # 小程序容器，不关会留着托盘
    "WeixinAppEx.exe",
)

WM_CLOSE = 0x0010
HWND_BROADCAST = 0xFFFF
WM_SYSCOMMAND = 0x0112
SC_MONITORPOWER = 0xF170
SMTO_ABORTIFHUNG = 0x0002

VK_LWIN = 0x5B
VK_D = 0x44
KEYEVENTF_KEYUP = 0x0002


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _running(name: str) -> bool:
    """按进程名查是否还在跑。

    不能用 taskkill 的返回值判断：不带 /F 时它只是「发了个关闭消息」，
    进程不理会（比如微信收进托盘）它照样返回 0，看起来成功了其实还在。
    """
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
            capture_output=True,
            creationflags=_no_window(),
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (proc.stdout or b"").decode("mbcs", "ignore").lower()
    return name.lower() in text


def _taskkill(name: str, force: bool) -> int:
    """返回 taskkill 的退出码：0 表示至少关掉了一个进程。"""
    command = ["taskkill", "/IM", name]
    if force:
        command.insert(1, "/F")
    try:
        proc = subprocess.run(
            command, capture_output=True, creationflags=_no_window(), timeout=10
        )
        return proc.returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


def close_wechat() -> tuple[bool, str]:
    """直接强制结束微信进程，然后确认真的没了。

    强制结束不会通知服务器，手机上的「已登录 Windows 电脑」要等心跳超时
    （1~3 分钟）才消失；这是接受的取舍，不这里做模拟点击那套。
    """
    if sys.platform != "win32":
        return False, "只支持 Windows"

    targets = [name for name in WECHAT_PROCESSES if _running(name)]
    if not targets:
        return False, "微信没在运行"

    for name in targets:
        _taskkill(name, force=True)

    time.sleep(0.8)
    left = [name for name in targets if _running(name)]
    if left:
        return False, "没关掉：" + "、".join(left)
    return True, "已结束 " + "、".join(targets)


def _at_desktop() -> bool:
    """当前焦点是不是已经在桌面（Progman / WorkerW）。"""
    try:
        user32 = ctypes.windll.user32
    except AttributeError:
        return False
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    return buf.value in ("Progman", "WorkerW")


def show_desktop() -> tuple[bool, str]:
    """按 Win+D 回桌面；已经在桌面就不按（再按一次会把窗口还原回来）。"""
    if sys.platform != "win32":
        return False, "只支持 Windows"
    if _at_desktop():
        return True, "已经在桌面"
    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        user32.keybd_event(VK_D, 0, 0, 0)
        user32.keybd_event(VK_D, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
    except (AttributeError, OSError) as exc:
        return False, f"模拟按键失败：{exc}"
    return True, "已回到桌面"


def monitor_off() -> tuple[bool, str]:
    """广播「关闭显示器」，效果等同电源按钮里的关屏。

    动鼠标或敲键盘就亮回来；少数显卡/显示器组合会忽略这条消息。
    """
    if sys.platform != "win32":
        return False, "只支持 Windows"
    try:
        user32 = ctypes.windll.user32
        result = user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SYSCOMMAND,
            SC_MONITORPOWER,
            2,                      # 2 = 关闭显示器
            SMTO_ABORTIFHUNG,
            1000,
            None,
        )
    except (AttributeError, OSError) as exc:
        return False, f"调用失败：{exc}"
    if not result:
        return False, "系统没有响应关屏消息"
    return True, "已发送关屏"


def is_wechat_running() -> bool:
    """给设置面板的按钮做提示用：微信在不在跑。"""
    return any(_running(name) for name in WECHAT_PROCESSES)
