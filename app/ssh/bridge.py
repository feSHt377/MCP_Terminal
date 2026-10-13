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
                    except asyncio.CancelledError:
                        self.result_ready.emit(
                            task_id, {"status": "error", "message": "任务已取消 (CancelledError)", "cancelled": True}
                        )
                    except Exception as e:
                        self.result_ready.emit(
                            task_id, {"status": "error", "message": str(e)}
                        )
                except asyncio.CancelledError:
                    # 避免外层 worker 循环被意外 cancel 导致整个 bridge 线程退出
                    continue
                except Exception as e:
                    self.error_occurred.emit(str(e))

        try:
            loop.run_until_complete(_worker())
        finally:
            # 标记不可用：否则 submit_* 会继续把任务塞进没人消费的队列，
            # 调用方永远等不到回调（表现为"无限卡死"且没有任何报错）。
            self._ready = False
            # 清理待处理任务
            running = asyncio.all_tasks(loop)
            for task in running:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*running, return_exceptions=True))
            loop.close()
            self._loop = None

    def stop(self):
        """停止事件循环线程。"""
        self._task_queue.put((-1, None, None))  # 停止信号
        self.wait(3000)
        self._ready = False

    def is_ready(self) -> bool:
        """事件循环是否可用（线程已退出则为 False）。"""
        return bool(self._ready) and self._loop is not None and not self._loop.is_closed()

    def _wait_ready(self):
        """阻塞等待事件循环就绪。"""
        import time
        deadline = time.time() + 5
        while not self.is_ready() and time.time() < deadline:
            time.sleep(0.01)
        if not self.is_ready():
            raise RuntimeError("SSHBridge 事件循环不可用（未启动或已停止）")

    @staticmethod
    def _close_coro(coro) -> None:
        """丢弃未执行的协程，避免 'coroutine was never awaited' 警告。"""
        try:
            close = getattr(coro, "close", None)
            if callable(close):
                close()
        except Exception:
            pass

    def submit(self, coro) -> dict[str, Any]:
        """同步提交协程并等待结果（仅用于 closeEvent 等同步场景）。

        通过 run_coroutine_threadsafe 在 bridge 的事件循环中执行。
        """
        try:
            self._wait_ready()
        except RuntimeError as exc:
            self._close_coro(coro)
            return {"status": "error", "message": str(exc)}
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=30)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def submit_async(self, coro, on_done):
        """异步提交协程，通过回调接收结果。（GUI 线程安全）

        on_done 签名为: def on_done(result: dict) -> None

        事件循环不可用时也会调用 on_done 并回传错误结果——绝不静默丢弃，
        否则调用方（如 GUI IPC 请求）会永远等不到回调而"无限卡死"。
        """
        try:
            self._wait_ready()
        except RuntimeError as exc:
            self._close_coro(coro)
            on_done({"status": "error", "message": str(exc)})
            return

        task_id = str(self._counter)
        self._counter += 1

        # 先连接信号，再入队（避免竞态：worker 先完成 emit 再 connect）
        def _handler(tid, result):
            if tid == task_id:
                self.result_ready.disconnect(_handler)
                on_done(result)

        self.result_ready.connect(_handler)
        self._task_queue.put((task_id, coro, on_done))

    def submit_parallel(self, coro, on_done):
        """在同一事件循环并行调度，**不排入串行命令队列**。

        用于不触碰活动进程的操作——新建连接、断开连接等。这类操作与「某会话
        正在跑一条长命令」互不冲突，若排在串行队列后面，一条 3600s 的命令就能
        让"点击连接"排队到 IPC 超时，表现为无限卡死。
        """
        try:
            self._wait_ready()
        except RuntimeError as exc:
            self._close_coro(coro)
            on_done({"status": "error", "message": str(exc)})
            return

        task_id = f"parallel-{self._counter}"
        self._counter += 1

        def _handler(tid, result):
            if tid == task_id:
                self.result_ready.disconnect(_handler)
                on_done(result)

        async def _run_parallel():
            try:
                result = await coro
            except Exception as exc:
                result = {"status": "error", "message": str(exc)}
            self.result_ready.emit(task_id, result)

        self.result_ready.connect(_handler)
        asyncio.run_coroutine_threadsafe(_run_parallel(), self._loop)

    def submit_realtime(self, coro, on_done):
        """向已运行的交互进程写入键盘数据等短操作（不排串行队列）。

        普通命令必须继续使用 ``submit_async``，以保留严格的串行执行语义。
        """
        self.submit_parallel(coro, on_done)
