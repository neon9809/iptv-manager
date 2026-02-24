#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""任务分发器 - 从 Task 表中拉取待处理任务并分发到 Celery Worker

由 Celery Beat 每 10 秒调用一次。
核心逻辑:
  1. 检查当前正在运行的任务数量
  2. 如果有空闲槽位，从 Task 表中按 priority DESC, created_at ASC 拉取 PENDING 任务
  3. 将任务状态更新为 QUEUED，创建"排队中"通知，并通过 celery_app.send_task() 分发到对应队列
"""

import logging
from datetime import datetime

from celery import shared_task
from sqlalchemy import select, func

from app.core.database import async_session_maker
from app.models.models import Task
from app.utils.async_task_runner import run_async

logger = logging.getLogger(__name__)

# 最大并发任务数（可通过 SystemConfig 动态读取）
DEFAULT_MAX_CONCURRENT = 4


def _task_type_to_notify_params(task_obj: Task) -> dict:
    """根据任务类型返回 notify_analysis_progress 所需的参数"""
    t = task_obj.task_type
    if t == "SINGLE_STREAM_ANALYSIS":
        return {"task_type": "single", "source_id": None}
    elif t in ("BATCH_ANALYSIS", "AUTO_ANALYSIS"):
        return {"task_type": "full", "source_id": None}
    elif t == "SOURCE_REFRESH":
        source_id = task_obj.payload.get("source_id")
        return {"task_type": "basic", "source_id": source_id}
    return {"task_type": "full", "source_id": None}


@shared_task(name="app.tasks.dispatcher.dispatch_tasks")
@run_async
async def dispatch_tasks():
    """自定义任务分发器 - 实现应用层优先级队列"""
    from app.services.notification_service import notify_analysis_progress

    async with async_session_maker() as db:
        # 1. 统计当前正在运行和排队中的任务数
        running_count_result = await db.execute(
            select(func.count(Task.id)).where(Task.status.in_(["RUNNING", "QUEUED"]))
        )
        running_count = running_count_result.scalar() or 0

        if running_count >= DEFAULT_MAX_CONCURRENT:
            return

        slots_available = DEFAULT_MAX_CONCURRENT - running_count

        # 2. 按优先级降序、创建时间升序获取待处理任务
        pending_result = await db.execute(
            select(Task)
            .where(Task.status == "PENDING")
            .order_by(Task.priority.desc(), Task.created_at.asc())
            .limit(slots_available)
        )
        tasks_to_dispatch = pending_result.scalars().all()

        if not tasks_to_dispatch:
            return

        # 3. 分发任务
        from app.core.celery_app import celery_app

        dispatched = 0
        for task_obj in tasks_to_dispatch:
            try:
                task_obj.status = "QUEUED"
                await db.flush()

                # 创建"排队中"通知，显示在"最近维护"时间线
                notify_params = _task_type_to_notify_params(task_obj)
                try:
                    await notify_analysis_progress(
                        db=db,
                        current=0,
                        total=task_obj.total or 1,
                        current_stream_name="",
                        task_identifier=str(task_obj.id)[:8],
                        is_queued=True,
                        task_type=notify_params["task_type"],
                        source_id=notify_params["source_id"],
                    )
                except Exception as ne:
                    logger.warning(f"[Dispatcher] Failed to create queued notification for task {task_obj.id}: {ne}")

                # 根据任务类型路由到不同的 Celery 任务和队列
                if task_obj.task_type == "SINGLE_STREAM_ANALYSIS":
                    celery_app.send_task(
                        'app.tasks.analysis.analyze_stream_task',
                        args=[str(task_obj.id)],
                        queue='analysis-high',
                    )
                elif task_obj.task_type in ("BATCH_ANALYSIS", "AUTO_ANALYSIS"):
                    celery_app.send_task(
                        'app.tasks.analysis.batch_analyze_streams_task',
                        args=[str(task_obj.id)],
                        queue='analysis',
                    )
                elif task_obj.task_type == "SOURCE_REFRESH":
                    celery_app.send_task(
                        'app.tasks.scheduled.source_refresh_task',
                        args=[str(task_obj.id)],
                        queue='refresh',
                    )
                else:
                    logger.warning(f"[Dispatcher] Unknown task type: {task_obj.task_type}")
                    task_obj.status = "FAILED"
                    task_obj.result = {"error": f"Unknown task type: {task_obj.task_type}"}
                    continue

                dispatched += 1
                logger.info(
                    f"[Dispatcher] Dispatched task {task_obj.id} "
                    f"(type={task_obj.task_type}, priority={task_obj.priority})"
                )
            except Exception as e:
                logger.error(f"[Dispatcher] Failed to dispatch task {task_obj.id}: {e}")
                task_obj.status = "FAILED"
                task_obj.result = {"error": f"Dispatch failed: {str(e)}"}

        await db.commit()

        if dispatched > 0:
            logger.info(f"[Dispatcher] Dispatched {dispatched} task(s) in this cycle.")
