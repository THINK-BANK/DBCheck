"""PyInstaller runtime hook: ensure gevent is fully initialized before app code runs.

注意：本 hook 目前未接入任何 .spec 的 runtime_hooks（三个 spec 均为 []），
保留是为了将来需要时可直接启用。启用后请务必保留下面的环境变量逃生门。

DBCheck_NO_GEVENT_PATCH=1 时整体跳过：
  JDBC 连接测试子进程（``dbcheck.exe --jdbc-test-cli``）会在进程内启动 JVM，
  JVM 用的是原生 OS 线程，与 gevent 的绿色线程/hub 相互踩踏极易死锁。
  该子进程必须运行在**未被 monkey-patch 的干净解释器**里。
"""
import os

if os.environ.get('DBCheck_NO_GEVENT_PATCH') != '1':
    import gevent.monkey
    gevent.monkey.patch_all()

    # gevent 1.4+ 已移除 gevent.wsgi / gevent.http 子模块；仅保留仍在用的组件，
    # 避免将来该 hook 被接入 runtime_hooks 后，冻结程序启动即 ModuleNotFoundError
    import gevent.pywsgi
    import gevent.local
    import gevent.hub
    import gevent.server
