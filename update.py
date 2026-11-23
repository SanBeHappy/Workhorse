"""检查更新：读 GitHub 仓库根目录的 VERSION 文件，和本地版本比一下。

选 VERSION 文件而不是 Releases，是因为发版流程最轻 —— 改个文件推上去就生效，
不用每次打包都去 GitHub 建 release。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

REPO = "SanBeHappy/Workhorse"   # 仓库改过名，旧地址 - 会 301 过来
BRANCH = "main"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION"
CHANGELOG_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/CHANGELOG.md"
# 走 GitHub Releases：latest 会自动指向最新一个正式版
# 目录模式发布的是打好的 zip，解压就是 DeskMate\DeskMate.exe
ASSET_URL = f"https://github.com/{REPO}/releases/latest/download/DeskMate.zip"

UPDATE_DIR = Path(tempfile.gettempdir()) / "DeskMate-update"
PAGE_URL = f"https://github.com/{REPO}"

_NUM = re.compile(r"\d+")


def parse_version(text: str) -> tuple[int, ...]:
    """把 1.0.10 拆成 (1, 0, 10)，保证 10 比 9 大。"""
    return tuple(int(x) for x in _NUM.findall(text or "")[:3]) or (0,)


def is_newer(remote: str, local: str) -> bool:
    a, b = parse_version(remote), parse_version(local)
    size = max(len(a), len(b))
    a += (0,) * (size - len(a))
    b += (0,) * (size - len(b))
    return a > b


def parse_changelog(text: str, version: str) -> list[str]:
    """从 CHANGELOG 里挑出指定版本那一段的条目。"""
    items: list[str] = []
    inside = False
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().lstrip("v") == version
            continue
        if inside and line.strip().startswith(("- ", "* ")):
            items.append(line.strip()[2:].strip())
    return items


def open_repo() -> None:
    QDesktopServices.openUrl(QUrl(PAGE_URL))


class UpdateChecker(QObject):
    """一次性的版本查询，成功失败都会回调。"""

    finished = Signal(str, str, list)   # (远端版本号, 错误信息, 更新日志条目)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._busy = False

    def check(self) -> None:
        if self._busy:
            return
        self._busy = True

        request = QNetworkRequest(QUrl(f"{VERSION_URL}?t={int(time.time())}"))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader,
            "Mozilla/5.0 DeskMate-UpdateCheck",
        )
        request.setTransferTimeout(10000)
        reply = self._nam.get(request)
        reply.finished.connect(lambda r=reply: self._on_done(r))

    def _on_done(self, reply: QNetworkReply) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._busy = False
                self.finished.emit("", "网络不通，稍后再试", [])
                return
            text = bytes(reply.readAll()).decode("utf-8", "ignore").strip()
            match = re.search(r"\d+(?:\.\d+){0,2}", text)
            if not match:
                self._busy = False
                self.finished.emit("", "远端的版本文件读不出来", [])
                return
            version = match.group(0)
            self._fetch_notes(version)
        except Exception:
            self._busy = False
            self.finished.emit("", "检查更新失败", [])
        finally:
            reply.deleteLater()

    def _fetch_notes(self, version: str) -> None:
        """拿到版本号后顺手拉更新日志，失败也不影响提示。"""
        request = QNetworkRequest(QUrl(f"{CHANGELOG_URL}?t={int(time.time())}"))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader,
            "Mozilla/5.0 DeskMate-UpdateCheck",
        )
        request.setTransferTimeout(10000)
        reply = self._nam.get(request)

        def done(r=reply) -> None:
            self._busy = False
            notes: list[str] = []
            try:
                if r.error() == QNetworkReply.NetworkError.NoError:
                    text = bytes(r.readAll()).decode("utf-8", "ignore")
                    notes = parse_changelog(text, version)
            except Exception:
                notes = []
            finally:
                r.deleteLater()
            self.finished.emit(version, "", notes)

        reply.finished.connect(done)


# ---------------------------------------------------------------- 下载与替换


SUMS_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/SHA256SUMS"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def _looks_like_zip(path: Path) -> bool:
    """最基础的完整性判断：zip 必须以 PK\x03\x04 开头。"""
    try:
        with open(path, "rb") as handle:
            return handle.read(4) == b"PK\x03\x04"
    except OSError:
        return False


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class UpdateDownloader(QObject):
    """下载新版 exe，并和仓库里的 SHA256SUMS 比对后才算可用。"""

    progress = Signal(int, int)      # 已下载字节, 总字节
    finished = Signal(str, str)      # 文件路径, 错误

    MIN_SIZE = 15 * 1024 * 1024      # 小于 15MB 一定是坏包

    def __init__(self) -> None:
        super().__init__()
        self._nam = QNetworkAccessManager(self)
        self._file = None
        self._target: Path | None = None
        self._part: Path | None = None
        self._expect = ""
        self._bad: list[str] = []    # 网络错误时堆叠的信息

    def start(self) -> None:
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        self._target = UPDATE_DIR / "DeskMate.zip"
        self._part = UPDATE_DIR / "DeskMate.part"
        self._expect = ""
        self._bad.clear()
        try:
            self._file = open(self._part, "wb")
        except OSError as exc:
            self.finished.emit("", f"写不了临时目录：{exc}")
            return

        request = QNetworkRequest(QUrl(f"{ASSET_URL}?t={int(time.time())}"))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader,
            "Mozilla/5.0 DeskMate-Update",
        )
        request.setTransferTimeout(300000)
        reply = self._nam.get(request)
        reply.downloadProgress.connect(self.progress.emit)
        reply.readyRead.connect(lambda r=reply: self._on_chunk(r))
        reply.finished.connect(lambda r=reply: self._on_done(r))

    def _on_chunk(self, reply: QNetworkReply) -> None:
        if self._file is None:
            return
        data = bytes(reply.readAll())
        if data:
            try:
                self._file.write(data)
            except OSError:
                pass

    def _on_done(self, reply: QNetworkReply) -> None:
        error = ""
        if reply.error() != QNetworkReply.NetworkError.NoError:
            error = "下载失败，检查网络后再试"
        try:
            if self._file is not None:
                self._file.close()
                self._file = None
        except OSError:
            pass
        reply.deleteLater()

        if not error and self._part is not None and self._target is not None:
            size = self._part.stat().st_size if self._part.exists() else 0
            if size < self.MIN_SIZE:
                error = "下载到的文件不完整"
            elif not _looks_like_zip(self._part):
                error = "下载到的不是有效的压缩包"
            else:
                try:
                    os.replace(self._part, self._target)
                except OSError as exc:
                    error = f"保存失败：{exc}"

        if error:
            self.finished.emit("", error)
            return
        self._fetch_sums()

    def _fetch_sums(self) -> None:
        """再拉一次 SHA256SUMS；拉不到就只靠 MZ + 体积判断，不卡住用户。"""
        request = QNetworkRequest(QUrl(f"{SUMS_URL}?t={int(time.time())}"))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader,
            "Mozilla/5.0 DeskMate-Update",
        )
        request.setTransferTimeout(15000)
        reply = self._nam.get(request)

        def done(r=reply) -> None:
            text = ""
            try:
                if r.error() == QNetworkReply.NetworkError.NoError:
                    text = bytes(r.readAll()).decode("utf-8", "ignore")
            except Exception:
                text = ""
            finally:
                r.deleteLater()
            self._expect = self._parse_sums(text)
            self._verify()

        reply.finished.connect(done)

    @staticmethod
    def _parse_sums(text: str) -> str:
        for raw in (text or "").splitlines():
            parts = raw.split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == "DeskMate.zip":
                candidate = parts[0].lower()
                if len(candidate) == 64:
                    return candidate
        return ""

    def _verify(self) -> None:
        assert self._target is not None
        try:
            actual = sha256_of(self._target)
        except OSError as exc:
            self.finished.emit("", f"读取下载文件失败：{exc}")
            return

        if self._expect and actual == self._expect:
            self.finished.emit(str(self._target), "")
            return

        # SHA256SUMS 走的是 raw CDN，发版后可能几分钟还是旧内容，
        # 这时改问 GitHub API 上附件的摘要，避免把好包判成坏的
        self._verify_by_api(actual)

    def _verify_by_api(self, actual: str) -> None:
        request = QNetworkRequest(QUrl(f"{API_URL}?t={int(time.time())}"))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader,
            "Mozilla/5.0 DeskMate-Update",
        )
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setTransferTimeout(15000)
        reply = self._nam.get(request)

        def done(r=reply) -> None:
            expect = ""
            try:
                if r.error() == QNetworkReply.NetworkError.NoError:
                    data = json.loads(bytes(r.readAll()).decode("utf-8", "ignore"))
                    for asset in data.get("assets") or []:
                        if asset.get("name") == "DeskMate.zip":
                            expect = (asset.get("digest") or "").replace("sha256:", "").lower()
                            break
            except Exception:
                expect = ""
            finally:
                r.deleteLater()

            if expect and expect == actual:
                self.finished.emit(str(self._target), "")
                return
            if not self._expect and not expect:
                # 两条路都问不到哈希，退回只看文件头，不卡住更新
                self.finished.emit(str(self._target), "")
                return
            try:
                if self._target is not None:
                    self._target.unlink()
            except OSError:
                pass
            self.finished.emit("", "下载的文件校验不通过，已放弃本次更新")

        reply.finished.connect(done)


RESTART_FLAG = "--restarted"


def can_self_update() -> bool:
    """只有打包后的 exe 才能替换自己。"""
    return bool(getattr(sys, "frozen", False))


def current_exe() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve()
    except OSError:
        return None


def mark_started() -> None:
    """跑起来就在临时目录盖个章，更新脚本靠它判断新版本真的启动了。"""
    try:
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        (UPDATE_DIR / "started.txt").write_text(
            f"{int(time.time())} {sys.argv[0]}", encoding="utf-8"
        )
    except OSError:
        pass


def started_after(stamp: float) -> bool:
    marker = UPDATE_DIR / "started.txt"
    try:
        return marker.exists() and marker.stat().st_mtime >= stamp - 1
    except OSError:
        return False


def clear_started() -> None:
    try:
        (UPDATE_DIR / "started.txt").unlink()
    except OSError:
        pass


def drop_old_copy(target: Path | None = None) -> None:
    """启动时清掉上一版留下的 .old 目录；删不掉说明旧进程还没退干净，忽略即可。"""
    exe = Path(target).resolve() if target else current_exe()
    if exe is None:
        return
    app_dir = exe.parent
    backup = app_dir.with_name(app_dir.name + ".old")
    if not backup.exists():
        return
    for _ in range(3):
        try:
            shutil.rmtree(backup)
            return
        except OSError:
            time.sleep(0.5)


# 换目录的批处理：等本进程退干净 → 旧目录改名 .old → 新目录就位 → 启动新版本。
# 全程只用 ASCII，路径靠参数传进来，避免中文路径在 cmd 里变乱码。
_SWAP_BAT = r"""@echo off
setlocal
set "APP=%~1"
set "NEW=%~2"
set "PID=%~3"
set "LOG=%~4"
set "FLAG=%~5"
set "VER=%~6"
set "OLD=%APP%.old"
set /a TRIES=0
:wait
tasklist /FI "PID eq %PID%" 2>nul | find /I "DeskMate.exe" >nul
if errorlevel 1 goto swap
set /a TRIES+=1
if %TRIES% GEQ 30 goto giveup
ping -n 2 127.0.0.1 >nul
goto wait
:swap
>>"%LOG%" echo [%DATE% %TIME%] pid %PID% exited, start swapping
rem let file handles settle before renaming
ping -n 4 127.0.0.1 >nul
if exist "%OLD%" rmdir /s /q "%OLD%" >>"%LOG%" 2>&1
set /a MOVE=0
:trymove
set /a MOVE+=1
move "%APP%" "%OLD%" >>"%LOG%" 2>&1
if not exist "%APP%" goto moved
if %MOVE% GEQ 12 goto failed_old
ping -n 2 127.0.0.1 >nul
goto trymove
:moved
>>"%LOG%" echo [%DATE% %TIME%] old dir -> .old
move "%NEW%" "%APP%" >>"%LOG%" 2>&1
if exist "%APP%\DeskMate.exe" goto restart
>>"%LOG%" echo [%DATE% %TIME%] new dir move failed, restoring
move "%OLD%" "%APP%" >>"%LOG%" 2>&1
goto failed_new
:restart
>>"%LOG%" echo [%DATE% %TIME%] new version in place, starting
start "" "%APP%\DeskMate.exe" --restarted
exit /b 0
:failed_old
rem rename denied (av / indexer / explorer holds a handle): overwrite in place instead
>>"%LOG%" echo [%DATE% %TIME%] rename denied, fallback to overwrite
robocopy "%NEW%" "%APP%" /E /IS /NP /NFL /NDL /NJH /NJS /R:3 /W:1 >>"%LOG%" 2>&1
rem verify the exe really became the new one (fc returns 0 only when identical)
fc /b "%NEW%\DeskMate.exe" "%APP%\DeskMate.exe" >nul 2>&1
if errorlevel 1 goto failed_old_hard
>>"%LOG%" echo [%DATE% %TIME%] overwrite ok, starting
rmdir /s /q "%NEW%" >nul 2>&1
start "" "%APP%\DeskMate.exe" --restarted
exit /b 0
:failed_old_hard
>>"%LOG%" echo [%DATE% %TIME%] update FAILED (move-old)
echo move-old %VER%> "%FLAG%"
start "" "%APP%\DeskMate.exe" --restarted
exit /b 1
:failed_new
>>"%LOG%" echo [%DATE% %TIME%] update FAILED (move-new)
echo move-new %VER%> "%FLAG%"
start "" "%APP%\DeskMate.exe" --restarted
exit /b 1
:giveup
>>"%LOG%" echo [%DATE% %TIME%] giveup waiting pid %PID%
exit /b 2
"""


def _spawn_flags() -> int:
    """给换目录脚本用的启动标志。

    注意不能用 DETACHED_PROCESS：那样 cmd 没有控制台，它里面跑的 tasklist /
    find 会各自新开一个可见的控制台窗口，表现就是右下角一直在闪黑框。
    只用 CREATE_NO_WINDOW 的话 cmd 有一个隐藏控制台，子进程共用它，不闪。
    """
    flags = 0
    for name in ("CREATE_NO_WINDOW", "CREATE_NEW_PROCESS_GROUP"):
        flags |= int(getattr(subprocess, name, 0))
    return flags


def _flag_parts() -> tuple[str, str]:
    try:
        parts = (UPDATE_DIR / "failed.flag").read_text("utf-8", "ignore").split()
    except OSError:
        return "", ""
    reason = parts[0] if parts else ""
    version = parts[1] if len(parts) > 1 else ""
    return reason, version


def update_failed() -> bool:
    """上一次自动更新有没有失败。

    标记里带着「本该变成的版本号」：如果当前版本已经不小于它（手动覆盖安装、
    或者重试成功了），标记就作废，免得换了新包还被旧标记追着提示。
    """
    flag = UPDATE_DIR / "failed.flag"
    if not flag.exists():
        return False
    reason, version = _flag_parts()
    if not reason:
        clear_update_failed()
        return False
    if not version:
        # 老格式没有版本号，无从比较，直接当作过期标记清掉
        clear_update_failed()
        return False
    try:
        from config import APP_VERSION
    except Exception:  # noqa: BLE001
        return True
    if not is_newer(version, APP_VERSION):
        clear_update_failed()
        return False
    return True


def update_failure_reason() -> str:
    """读到失败标记里的原因，翻成人话；没有就返回空串。"""
    raw = _flag_parts()[0]
    if not raw:
        return ""
    mapping = {
        "move-old": "旧版本目录被占用：改名和原地覆盖都没成功（多半是杀软或资源管理器占着文件）。"
                    "可以先用托盘菜单退出，再手动解压 DeskMate.zip 覆盖一次",
        "move-new": "新版本目录没能就位（可能是磁盘空间或权限问题）",
    }
    return mapping.get(raw, raw)


def clear_update_failed() -> None:
    try:
        (UPDATE_DIR / "failed.flag").unlink()
    except OSError:
        pass


def swap_log() -> Path:
    return UPDATE_DIR / "swap.log"


def _spawn_swap(
    app_dir: Path, new_dir: Path, pid: int | None = None, version: str = ""
) -> "subprocess.Popen[bytes]":
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    clear_update_failed()
    script = UPDATE_DIR / "swap.bat"
    script.write_text(_SWAP_BAT, encoding="ascii", newline="\r\n")
    log = swap_log()
    try:
        log.write_text("", encoding="utf-8")
    except OSError:
        pass
    return subprocess.Popen(
        [
            "cmd",
            "/c",
            str(script),
            str(app_dir),
            str(new_dir),
            str(pid or os.getpid()),
            str(log),
            str(UPDATE_DIR / "failed.flag"),
            version,
        ],
        cwd=str(UPDATE_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_spawn_flags(),
        close_fds=True,
    )


def apply_update(
    package: Path, target: Path | None = None, version: str = ""
) -> tuple[bool, str, "subprocess.Popen[bytes] | None"]:
    """把下载好的 zip 解压到临时目录，然后交给换目录脚本处理。

    目录模式的程序没法在运行中替换自己所在的文件夹，所以这里只负责解压 +
    写脚本 + 启动脚本，真正的「旧目录改名 / 新目录就位 / 重启」由脚本在
    本进程退出后完成。返回 (是否成功, 错误信息, 脚本进程句柄)。
    """
    exe = Path(target).resolve() if target else current_exe()
    if exe is None:
        return False, "开发模式下不支持自动更新", None
    package = Path(package)
    if not package.exists():
        return False, "找不到下载好的更新包", None
    if not _looks_like_zip(package):
        return False, "更新包不是有效的压缩文件", None

    app_dir = exe.parent
    if not app_dir.exists():
        # 运行期间目录被改名/移动了，sys.executable 还是老路径，换目录必然失败
        return (
            False,
            f"程序目录已不在原位置（{app_dir}）。如果刚改过文件夹名，请先重启 DeskMate 再更新",
            None,
        )

    # 关键：解压到「和程序目录同一块盘」的兄弟目录里。
    # 放 %TEMP% 的话，旧盘到系统盘是两个卷，move 目录会退化成整份复制，
    # 慢且容易在中途失败；同卷只是改个名字，瞬间完成。
    staging = app_dir.parent / f".{app_dir.name}-new"
    try:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
    except OSError:
        staging = UPDATE_DIR / "new"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        try:
            staging.mkdir(parents=True)
        except OSError as exc:
            return False, f"创建暂存目录失败：{exc}", None

    try:
        with zipfile.ZipFile(package) as archive:
            archive.extractall(staging)
    except (OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return False, f"解压更新包失败：{exc}", None

    root = staging
    if not (root / "DeskMate.exe").exists():
        inner = staging / "DeskMate"
        if (inner / "DeskMate.exe").exists():
            root = inner
        else:
            shutil.rmtree(staging, ignore_errors=True)
            return False, "更新包里没找到 DeskMate.exe", None

    app_dir = exe.parent
    try:
        if _spawn_swap(app_dir, root, version=version):
            return True, "", None
    except OSError as exc:
        return False, f"启动更新脚本失败：{exc}", None
    return False, "启动更新脚本失败", None


def is_folder_install() -> bool:
    """当前是不是目录模式（exe 旁边有 _internal）。"""
    exe = current_exe()
    if exe is None:
        return False
    return (exe.parent / "_internal").is_dir() or (exe.parent / "assets").is_dir()
