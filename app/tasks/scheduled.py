"""定时任务调度器 - Celery Beat 心跳模式 (重构版)

调度器不直接执行业务逻辑，而是检查条件并创建 Task 记录。
实际的任务执行由 dispatcher.py 负责从 Task 表中拉取并分发。

调度器列表:
  - source_refresh_scheduler: 遍历所有订阅源，按各自的 refresh_frequency_hours 创建刷新任务
  - auto_analysis_scheduler: 根据 SystemConfig.analysis_frequency_minutes 创建全局增强分析任务
  - source_refresh_task: 执行单个订阅源的刷新 (由 dispatcher 分发)
  - log_cleanup_scheduler: 定时清理过期日志
"""

import uuid
import logging
from datetime import datetime, timedelta

from celery import shared_task
from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.models import SubscriptionSource, SystemConfig, Task, Stream
from app.services.notification_service import (
    notify_task_started,
    notify_task_completed,
)
from app.services.log_service import LogService
from app.utils.async_task_runner import run_async

logger = logging.getLogger(__name__)

LAST_AUTO_ANALYSIS_KEY = "last_auto_analysis_timestamp"


@shared_task(name="app.tasks.scheduled.source_refresh_scheduler")
@run_async
async def source_refresh_scheduler():
    """订阅源刷新调度器 (心跳)

    遍历所有订阅源，检查每个订阅源各自的 refresh_frequency_hours，
    如果到期则创建一个 SOURCE_REFRESH 类型的 Task。
    """
    logger.info("[Scheduler] Running source refresh scheduler...")
    async with async_session_maker() as db:
        result = await db.execute(select(SubscriptionSource))
        sources = result.scalars().all()

        created_count = 0
        for source in sources:
            needs_refresh = False
            if not source.last_refresh_time:
                needs_refresh = True
            else:
                now = datetime.utcnow()
                next_refresh_at = source.last_refresh_time + timedelta(hours=source.refresh_frequency_hours)
                if now >= next_refresh_at:
                    needs_refresh = True

            if not needs_refresh:
                continue

            existing = await db.execute(
                select(Task).where(
                    Task.task_type == "SOURCE_REFRESH",
                    Task.status.in_(["PENDING", "QUEUED", "RUNNING"]),
                ).filter(Task.payload["source_id"].as_integer() == source.id)
            )
            if existing.scalar_one_or_none():
                logger.debug(f"[Scheduler] Source {source.id} ('{source.nickname}') already has a pending refresh task.")
                continue

            new_task = Task(
                task_name=f"Auto Refresh: {source.nickname}",
                task_type="SOURCE_REFRESH",
                priority=4,
                payload={"source_id": source.id},
            )
            db.add(new_task)
            created_count += 1
            logger.info(f"[Scheduler] Created refresh task for source {source.id} ('{source.nickname}', freq={source.refresh_frequency_hours}h)")

        if created_count > 0:
            await db.commit()
        logger.info(f"[Scheduler] Source refresh check done. Created {created_count} task(s).")


@shared_task(name="app.tasks.scheduled.auto_analysis_scheduler")
@run_async
async def auto_analysis_scheduler():
    """自动增强分析调度器 (心跳)

    根据 SystemConfig.analysis_frequency_minutes 决定是否创建全局增强分析任务。
    使用 Redis 记录上次执行时间以避免重复触发。
    """
    logger.info("[Scheduler] Running auto analysis scheduler...")
    from app.utils.redis_client import redis_client

    async with async_session_maker() as db:
        config = (await db.execute(select(SystemConfig).limit(1))).scalar_one_or_none()
        if not config or config.analysis_frequency_minutes <= 0:
            logger.info("[Scheduler] Auto analysis is disabled (frequency <= 0). Skipping.")
            return

        redis = await redis_client.get_client()
        try:
            last_run_str = await redis.get(LAST_AUTO_ANALYSIS_KEY)
            now_ts = datetime.utcnow().timestamp()

            if last_run_str:
                elapsed = now_ts - float(last_run_str)
                interval = config.analysis_frequency_minutes * 60
                if elapsed < interval:
                    logger.info(f"[Scheduler] Auto analysis interval not reached ({elapsed:.0f}s / {interval}s). Skipping.")
                    return

            existing = await db.execute(
                select(Task).where(
                    Task.task_type == "AUTO_ANALYSIS",
                    Task.status.in_(["PENDING", "QUEUED", "RUNNING"]),
                )
            )
            if existing.scalar_one_or_none():
                logger.info("[Scheduler] Auto analysis task already pending. Skipping.")
                return

            new_task = Task(
                task_name="Scheduled Enhanced Analysis",
                task_type="AUTO_ANALYSIS",
                priority=2,
                payload={"mode": "full"},
            )
            db.add(new_task)
            await db.commit()
            await redis.set(LAST_AUTO_ANALYSIS_KEY, str(now_ts))
            logger.info("[Scheduler] Created a new scheduled enhanced analysis task.")
        finally:
            await redis_client.close_client(redis)


@shared_task(name="app.tasks.scheduled.log_cleanup_scheduler")
@run_async
async def log_cleanup_scheduler():
    """日志清理调度器 (心跳)

    根据 SystemConfig.log_retention_hours 清理过期日志。
    默认每小时执行一次。
    """
    logger.info("[Scheduler] Running log cleanup scheduler...")
    async with async_session_maker() as db:
        try:
            config = (await db.execute(select(SystemConfig).limit(1))).scalar_one_or_none()
            retention_hours = config.log_retention_hours if config else 1
            
            deleted_count = await LogService.cleanup_old_logs(db, retention_hours)
            logger.info(f"[Scheduler] Log cleanup done. Deleted {deleted_count} old log entries.")
        except Exception as e:
            logger.error(f"[Scheduler] Log cleanup failed: {e}")


@shared_task(name="app.tasks.scheduled.source_refresh_task")
@run_async
async def source_refresh_task(task_id: str):
    """执行单个订阅源的刷新 - 由调度器分发调用"""
    from app.services import source_manager
    from app.services.channel_matcher import auto_match_channels
    from app.services.notification_service import notify_source_refresh_failed

    task_uuid = uuid.UUID(task_id)
    async with async_session_maker() as db:
        task_obj = (await db.execute(select(Task).where(Task.id == task_uuid))).scalar_one_or_none()
        if not task_obj:
            logger.error(f"[Task {task_id}] 任务不存在。")
            return

        source_id = task_obj.payload.get("source_id")
        task_obj.status = "RUNNING"
        task_obj.started_at = datetime.utcnow()
        await db.commit()

        source = (await db.execute(select(SubscriptionSource).where(SubscriptionSource.id == source_id))).scalar_one_or_none()
        source_name = source.nickname if source else f"ID:{source_id}"
        source_url = source.url if source else ""

        await notify_task_started(
            db=db,
            task_id=task_id,
            task_name=task_obj.task_name,
            task_type="SOURCE_REFRESH",
            total=1,
        )

        try:
            result = await source_manager.refresh_source(db, source_id, analyze_video=False)
            await auto_match_channels(db)
            await db.commit()

            task_obj = (await db.execute(select(Task).where(Task.id == task_uuid))).scalar_one()
            task_obj.status = "SUCCESS"
            task_obj.result = result if isinstance(result, dict) else {"status": "done"}

            await notify_task_completed(
                db=db,
                task_id=task_id,
                task_name=task_obj.task_name,
                task_type="SOURCE_REFRESH",
                total=1,
                success=True,
            )

        except Exception as e:
            logger.error(f"[Task {task_id}] Failed to refresh source {source_id}: {e}", exc_info=True)
            task_obj = (await db.execute(select(Task).where(Task.id == task_uuid))).scalar_one()
            task_obj.status = "FAILED"
            task_obj.result = {"error": str(e)}

            try:
                await notify_source_refresh_failed(db, source_name, source_url, str(e))
            except Exception as notify_error:
                logger.error(f"Failed to send notification: {notify_error}")

            await notify_task_completed(
                db=db,
                task_id=task_id,
                task_name=task_obj.task_name,
                task_type="SOURCE_REFRESH",
                total=1,
                success=False,
                error_message=str(e),
            )

        finally:
            task_obj = (await db.execute(select(Task).where(Task.id == task_uuid))).scalar_one()
            task_obj.completed_at = datetime.utcnow()
            await db.commit()
            logger.info(f"[Task {task_id}] Source refresh finished: {task_obj.status}")
