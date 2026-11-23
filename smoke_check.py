"""冒烟自检：不弹窗口跑一遍关键路径，抓「信号没接上」这类只在运行时才炸的错误。

跑法（在项目根目录）：
    QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe smoke_check.py

检查项：
  · 主窗口能起来
  · 设置窗口能打开（信号连接全部存在）
  · 卡片风格能来回切
  · 角色显示开关能开关
  · 关机测试流程的函数都在（不真的执行）
"""

from __future__ import annotations

import sys
import traceback

from PySide6.QtWidgets import QApplication


def main() -> int:
    app = QApplication(sys.argv[:1])

    failures: list[str] = []

    def check(name: str, func) -> None:
        try:
            func()
            print(f"  [OK] {name}")
        except Exception:  # noqa: BLE001
            failures.append(name)
            print(f"  [FAIL] {name}")
            traceback.print_exc()

    import main as app_main

    holder: dict[str, object] = {}

    def boot() -> None:
        holder["app"] = app_main.DeskMate(app)

    check("主窗口启动", boot)
    mate = holder.get("app")
    if mate is None:
        return 1

    def open_settings() -> None:
        mate.open_settings()  # noqa: SLF001
        app.processEvents()
        window = mate.settings_window  # noqa: SLF001
        assert window is not None and window.isVisible(), "设置窗口没显示"
        assert hasattr(window, "shutdown_test"), "缺少测试按钮"

    check("打开设置窗口", open_settings)

    def switch_style() -> None:
        mate.apply_style("glass")  # noqa: SLF001
        app.processEvents()
        mate.apply_style("pixel")  # noqa: SLF001
        app.processEvents()

    check("切换卡片风格", switch_style)

    def toggle_character() -> None:
        mate.toggle_character(False)  # noqa: SLF001
        app.processEvents()
        mate.toggle_character(True)  # noqa: SLF001
        app.processEvents()

    check("角色显示开关", toggle_character)

    def engine_day_sweep() -> None:
        """把一天里几个关键时点都跑一遍，抓 drink_ratio 这类只在特定时段才炸的错。"""
        from datetime import datetime

        from config import Config
        from engine import Engine

        for enabled in (True, False):
            cfg = Config()
            cfg["drink_enabled"] = enabled
            cfg["shutdown_enabled"] = False
            engine = Engine(cfg)
            for hour in (8, 9, 10, 12, 13, 14, 18, 21, 23):
                engine.tick(
                    datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0)
                )

    check("引擎整天走时", engine_day_sweep)

    def shutdown_api() -> None:
        import shutdown

        assert callable(shutdown.perform_shutdown)
        assert callable(shutdown.cancel_pending)
        assert callable(mate.test_shutdown_flow)  # noqa: SLF001

    check("关机接口存在", shutdown_api)

    print("")
    if failures:
        print(f"冒烟自检失败：{len(failures)} 项 —— {', '.join(failures)}")
        return 1
    print("冒烟自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
