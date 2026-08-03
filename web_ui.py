# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

# ── 单实例守卫（必须在 import modules.web.app 之前）──
# 避免双击 / 重复启动 / 旧进程残留时多个 dbcheck.exe 同时运行，
# 互相抢占端口、并重复打印整段启动 banner（表现为『反复重启』）。
import os
import sys


def _acquire_single_instance():
    # 仅对 PyInstaller 冻结后的 exe 生效；开发态 `python web_ui.py` 不限制，便于多开调试。
    if not getattr(sys, 'frozen', False):
        return
    _lock = os.path.join(os.path.dirname(sys.executable), '.dbcheck.lock')
    try:
        import psutil  # 冻结构建已内置（hiddenimports）
        _fd = os.open(_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(_fd, str(os.getpid()).encode())
        os.close(_fd)

        # 正常退出时清理锁文件（os._exit 不会触发 atexit，故旧实例异常退出可能留残留锁，
        # 下面 FileExistsError 分支会用 psutil.pid_exists 判定并接管）。
        def _cleanup():
            try:
                if os.path.exists(_lock):
                    os.remove(_lock)
            except Exception:
                pass

        import atexit
        atexit.register(_cleanup)
    except FileExistsError:
        # 锁已存在：检查持有者是否还活着
        try:
            _pid = int(open(_lock, 'r', encoding='utf-8').read().strip() or '0')
            if psutil.pid_exists(_pid):
                print(
                    f"[DBCheck] 已有实例在运行（PID {_pid}），本进程退出以避免端口冲突。",
                    flush=True,
                )
                os._exit(0)
        except Exception:
            pass
        # 旧锁残留（持有进程已死），接管：删除后重试一次
        try:
            os.remove(_lock)
        except Exception:
            pass
        return _acquire_single_instance()
    except Exception:
        # psutil 缺失等异常情况下降级：不阻塞启动
        pass


_acquire_single_instance()

# 启动入口 shim：转发到 modules.web.app.main()，保持 `python web_ui.py` 可启动调试
from modules.web.app import *  # noqa: F401,F403

if __name__ == "__main__":
    main()
