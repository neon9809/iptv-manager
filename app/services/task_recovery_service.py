#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""任务恢复服务 (重构版)"""

import logging
from sqlalchemy import select, update
from app.core.database import async_session_maker
from app.models.models import Task, Stream

logger = logging.getLogger(__name__)

async def recover_interrupted_tasks():
    """
    在应用启动时恢复被中断的任务。
    将 QUEUED 或 RUNNING 状态的任务重置为 PENDING，以便调度器重新拾取。
    同时解锁被这些任务占用的直播流。
    """
    logger.info("Starting task recovery process...")
    recovered_task_count = 0
    unlocked_stream_count = 0

    async with async_session_maker() as db:
        try:
            # 查找所有中断的任务
            interrupted_tasks_result = await db.execute(
                select(Task).where(Task.status.in_(["QUEUED", "RUNNING"]))
            )
            interrupted_tasks = interrupted_tasks_result.scalars().all()

            if not interrupted_tasks:
                logger.info("No interrupted tasks found. Recovery complete.")
                return

            task_ids_to_reset = [task.id for task in interrupted_tasks]
            logger.info(f"Found {len(task_ids_to_reset)} interrupted tasks to recover.")

            # 1. 解锁被这些任务占用的直播流
            unlock_stmt = (
                update(Stream)
                .where(Stream.current_task_id.in_(task_ids_to_reset))
                .values(current_task_id=None)
            )
            result = await db.execute(unlock_stmt)
            unlocked_stream_count = result.rowcount
            if unlocked_stream_count > 0:
                logger.info(f"Unlocked {unlocked_stream_count} streams.")

            # 2. 将任务状态重置为 PENDING
            reset_stmt = (
                update(Task)
                .where(Task.id.in_(task_ids_to_reset))
                .values(status="PENDING", started_at=None)
            )
            result = await db.execute(reset_stmt)
            recovered_task_count = result.rowcount

            await db.commit()
            logger.info(f"Successfully recovered {recovered_task_count} tasks.")

        except Exception as e:
            logger.error(f"An error occurred during task recovery: {e}", exc_info=True)
            await db.rollback()
