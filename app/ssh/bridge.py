"""SSH 桥接器 — 持久化事件循环线程。

所有 asyncssh 操作必须在同一个 event loop 上执行，
否则会因底层 transport 绑定而报 'NoneType' object has no attribute 'send'。
"""

from __future__ import annotations

import asyncio
import queue
from typing import Any

from PySide6.QtCore import QThread, Signal


class SSHBridge(QThread):
    """持久化 asyncio 事件循环线程，所有 SSH 操作经此线程。

    用法:
        bridge = SSHBridge()
        bridge.start()
        bridge.submit_async(coro, on_done=callback)
    """

    result_ready = Signal(str, object)  # (task_id, result)
    error_occurred = Signal(str)        # error message

    _instance: SSHBridge | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # 单例模式：QThread.__init__ 只执行一次，否则会破坏运行中的线程状态
        if hasattr(self, "_task_queue"):
            return
        super().__init__()
        self._task_queue: queue.Queue = queue.Queue()
        self._counter: int = 0
        self._ready: bool = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def run(self):
        """线程主循环：持久化运行 asyncio 事件循环。"""
        # Windows 上 asyncssh 需要 SelectorEventLoop
        if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready = True

        async def _worker():
            while True:
                try:
                    # 非阻塞获取任务
                    try:
                        task_id, coro, callback = self._task_queue.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.05)
                        continue

                    if coro is None:  # 停止信号
                        break

                    try:
                        result = await coro
                        self.result_ready.emit(task_id, result)
                    except Exception as e:
                        self.result_ready.emit(
                            task_id, {"status": "error", "message": str(e)}
                        )
                except Exception as e:
                    self.error_occurred.emit(str(e))

        try:
            loop.run_until_complete(_worker())
        finally:
            # 清理待处理任务
            running = asyncio.all_tasks(loop)
            for task in running:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*running, return_exceptions=True))
            loop.close()

    def stop(self):
        """停止事件循环线程。"""
        self._task_queue.put((-1, None, None))  # 停止信号
        self.wait(3000)

    def _wait_ready(self):
        """阻塞等待事件循环就绪。"""
        import time
        deadline = time.time() + 5
        while not self._ready and time.time() < deadline:
            time.sleep(0.01)
        if not self._ready:
            raise RuntimeError("SSHBridge 事件循环未在 5s 内就绪")

    def submit(self, coro) -> dict[str, Any]:
        """同步提交协程并等待结果（仅用于 closeEvent 等同步场景）。

        通过 run_coroutine_threadsafe 在 bridge 的事件循环中执行。
        """
        self._wait_ready()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    def submit_async(self, coro, on_done):
        """异步提交协程，通过回调接收结果。（GUI 线程安全）

        on_done 签名为: def on_done(result: dict) -> None
        """
        self._wait_ready()
        task_id = str(self._counter)
        self._counter += 1

        # 先连接信号，再入队（避免竞态：worker 先完成 emit 再 connect）
        def _handler(tid, result):
            if tid == task_id:
                self.result_ready.disconnect(_handler)
                on_done(result)

        self.result_ready.connect(_handler)
        self._task_queue.put((task_id, coro, on_done))
