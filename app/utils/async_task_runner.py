#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""异步任务执行器 - 解决 Celery Worker 中事件循环冲突问题

Celery Worker 是同步的，但我们的数据库操作 (asyncpg) 和分析服务都是异步的。
此模块提供装饰器 `run_async`，为每个 Celery 任务创建独立的事件循环来运行异步函数，
从而避免 "attached to a different loop" 等错误。
"""

import asyncio
from functools import wraps
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


def run_async(func):
    """装饰器: 将 async Celery 任务包装为同步函数

    使用方式:
        @shared_task(bind=True)
        @run_async
        async def my_task(self, arg1, arg2):
            await some_async_operation()
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(func(*args, **kwargs))
        except Exception as e:
            logger.error(f"Error running async task {func.__name__}: {e}", exc_info=True)
            raise
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    return wrapper
