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


# QUEUED 任务超过该时长未被 Worker 领取即视为投递丢失
QUEUED_STALE_SECONDS = 300
# RUNNING 任务超过该时长无进展即视为僵尸（需大于最长任务时限 7200s）
RUNNING_STALE_SECONDS = 7500


async def recover_stale_tasks():
    """僵尸任务超时回收（由 Celery Beat 周期调用，不依赖 backend 重启）

    - QUEUED 超时：Celery 投递丢失或 Worker 消费延迟过久 → 重置为 PENDING
    - RUNNING 超时：Worker 崩溃/OOM 等导致任务卡死 → 标记 FAILED 并解锁占用的流

    解决"仅 Worker 崩溃而后端常驻时，QUEUED/RUNNING 任务永久卡死、
    占满并发槽位导致整个系统停摆"的问题。
    """
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    recovered_queued = 0
    recovered_running = 0
    unlocked_streams = 0

    async with async_session_maker() as db:
        try:
            # 1. QUEUED 超时回收：重置为 PENDING（基于 queued_at，
            #    避免 PENDING→QUEUED 循环中因 created_at 过旧而被立即再次重置）
            queued_cutoff = now - timedelta(seconds=QUEUED_STALE_SECONDS)
            result = await db.execute(
                update(Task)
                .where(
                    Task.status == "QUEUED",
                    Task.queued_at < queued_cutoff,
                )
                .values(status="PENDING", queued_at=None)
            )
            recovered_queued = result.rowcount or 0

            # 2. RUNNING 超时回收：标记 FAILED 并解锁流
            stale_result = await db.execute(
                select(Task).where(
                    Task.status == "RUNNING",
                    Task.started_at < now - timedelta(seconds=RUNNING_STALE_SECONDS),
                )
            )
            stale_tasks = stale_result.scalars().all()

            if stale_tasks:
                stale_ids = [t.id for t in stale_tasks]
                logger.warning(f"[Recovery] Found {len(stale_ids)} zombie RUNNING task(s): {stale_ids}")

                unlock_result = await db.execute(
                    update(Stream)
                    .where(Stream.current_task_id.in_(stale_ids))
                    .values(current_task_id=None)
                )
                unlocked_streams = unlock_result.rowcount or 0

                await db.execute(
                    update(Task)
                    .where(Task.id.in_(stale_ids))
                    .values(
                        status="FAILED",
                        completed_at=now,
                        result={"error": "Task timed out and was recovered by zombie reaper"},
                    )
                )
                recovered_running = len(stale_ids)

            if recovered_queued or recovered_running:
                await db.commit()
                logger.info(
                    f"[Recovery] Stale task recovery done. "
                    f"Queued->Pending: {recovered_queued}, Running->Failed: {recovered_running}, "
                    f"Unlocked streams: {unlocked_streams}"
                )
        except Exception as e:
            logger.error(f"[Recovery] Error during stale task recovery: {e}", exc_info=True)
            await db.rollback()
