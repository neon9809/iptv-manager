#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""异步任务执行器 - 解决 Celery Worker 中事件循环冲突问题

Celery Worker 是同步的，但我们的数据库操作 (asyncpg) 和分析服务都是异步的。

重要：asyncpg 连接绑定到创建它的事件循环。若每个任务新建并销毁一个事件循环，
全局连接池中的连接会被复用到不同循环上，触发 "Future attached to a different loop"。
因此这里采用【进程级长驻事件循环】方案：
  - Worker 进程启动时创建一个后台线程运行常驻 loop；
  - 每个任务通过 asyncio.run_coroutine_threadsafe 提交到该 loop 执行；
  - 连接池中的连接始终在同一循环中创建与复用，彻底消除跨循环冲突。
"""

import asyncio
import threading
from functools import wraps
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()


def _get_shared_loop() -> asyncio.AbstractEventLoop:
    """获取（或惰性创建）当前进程的长驻事件循环"""
    global _loop, _loop_thread
    if _loop is not None and _loop.is_running():
        return _loop

    with _loop_lock:
        # 双重检查：可能其他线程刚创建完
        if _loop is not None and _loop.is_running():
            return _loop

        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)

        def _run_forever():
            asyncio.set_event_loop(new_loop)
            new_loop.run_forever()

        thread = threading.Thread(
            target=_run_forever,
            name="celery-asyncio-loop",
            daemon=True,
        )
        thread.start()

        _loop = new_loop
        _loop_thread = thread
        logger.info("Created persistent event loop for Celery worker (daemon thread).")
        return _loop


def run_async(func):
    """装饰器: 将 async Celery 任务提交到进程级长驻事件循环执行

    使用方式:
        @shared_task(bind=True)
        @run_async
        async def my_task(self, arg1, arg2):
            await some_async_operation()
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        loop = _get_shared_loop()
        future = asyncio.run_coroutine_threadsafe(func(*args, **kwargs), loop)
        try:
            return future.result()
        except Exception as e:
            logger.error(f"Error running async task {func.__name__}: {e}", exc_info=True)
            raise

    return wrapper
