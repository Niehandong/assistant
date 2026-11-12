"""进程池子进程的“孤儿自杀”守卫。

父进程（kb-worker）被 SIGKILL 时，spawn 出来的池子进程阻塞在任务队列上，不会收到 EOF，
会变成 ppid=1 的孤儿并长期驻留。这里在子进程 initializer 中起一个守护线程，周期性检查
``os.getppid()`` 是否变化，变化即 ``os._exit``。

不用 ``prctl(PR_SET_PDEATHSIG)``：它绑定的是“创建子进程的线程”，而 ``ProcessPoolExecutor``
在 executor 管理线程里按需拉起子进程，该线程退出会误杀正常的子进程；且仅限 Linux。
轮询线程跨平台、无副作用，SIGTERM 正常停止流程（主进程 shutdown 池）不受影响。
"""

from __future__ import annotations

import os
import threading
import time

POLL_INTERVAL_SECONDS = 2.0


def _watch(parent_pid: int, interval: float) -> None:
    while True:
        time.sleep(interval)
        if os.getppid() != parent_pid:
            os._exit(1)


def init_worker_process(parent_pid: int, interval: float = POLL_INTERVAL_SECONDS) -> None:
    """``ProcessPoolExecutor(initializer=...)`` 入口；``parent_pid`` 由父进程传入。"""
    if os.getppid() != parent_pid:  # 启动前父进程就已死亡
        os._exit(1)
    threading.Thread(target=_watch, args=(parent_pid, interval), name="orphan-guard", daemon=True).start()
