"""分析任务 - Celery 异步任务 (重构版)

任务优先级说明:
  - 9: 单个流手动增强分析 (SINGLE_STREAM_ANALYSIS) - 最高优先级，可插队
  - 7: 首次添加订阅源触发的基本信息分析 (SOURCE_REFRESH)
  - 5: 手动触发的批量增强分析 (BATCH_ANALYSIS)
  - 4: 订阅源定时刷新 (SOURCE_REFRESH)
  - 2: 自动定时增强分析 (AUTO_ANALYSIS) - 最低优先级
"""

import asyncio
import logging
import uuid
from datetime import datetime

from celery import shared_task
from sqlalchemy import select, update

from app.core.database import async_session_maker
from app.models.models import Stream, Task
from app.services.stream_analyzer import analyze_stream_full, analyze_stream_quick
from app.services.config_service import ConfigService
from app.services.notification_service import (
    notify_task_started,
    notify_task_progress,
    notify_task_completed,
)
from app.utils.async_task_runner import run_async

logger = logging.getLogger(__name__)

# 通知进度更新的最小间隔（每 N 个流更新一次，避免频繁写库）
NOTIFY_INTERVAL = 5
# 进度落库节流间隔（每 N 条流写一次 Task.progress，万级流时避免万次事务）
PROGRESS_INTERVAL = 25


@shared_task(bind=True, name="app.tasks.analysis.analyze_stream_task", max_retries=2)
@run_async
async def analyze_stream_task(self, task_id: str):
    """分析单个直播流任务 - 由调度器分发调用

    此任务从 Task 表中读取 payload，获取 stream_id 和 mode，
    执行分析后更新 Task 和 Stream 的状态，并通过通知服务更新"最近维护"时间线。
    """
    from app.services.notification_service import notify_analysis_progress

    task_uuid = uuid.UUID(task_id)
    task_identifier = task_id[:8]

    async with async_session_maker() as db:
        task_obj = (await db.execute(select(Task).where(Task.id == task_uuid))).scalar_one_or_none()
        if not task_obj:
            logger.error(f"[Task {task_id}] 任务不存在，终止执行。")
            return

        stream_id = task_obj.payload.get("stream_id")
        mode = task_obj.payload.get("mode", "full")

        stream = (await db.execute(select(Stream).where(Stream.id == stream_id))).scalar_one_or_none()
        if not stream:
            logger.error(f"[Task {task_id}] 直播流 {stream_id} 不存在，任务失败。")
            task_obj.status = "FAILED"
            task_obj.result = {"error": f"Stream {stream_id} not found"}
            task_obj.completed_at = datetime.utcnow()
            await db.commit()
            await notify_task_completed(
                db=db,
                task_id=task_id,
                task_name=task_obj.task_name,
                task_type=task_obj.task_type,
                total=1,
                success=False,
                error_message=f"直播流 {stream_id} 不存在",
            )
            return

        if stream.current_task_id and stream.current_task_id != task_obj.id:
            logger.warning(f"[Task {task_id}] 直播流 {stream_id} 正在被任务 {stream.current_task_id} 分析，跳过。")
            task_obj.status = "SKIPPED"
            task_obj.result = {"error": "Stream is being analyzed by another task"}
            task_obj.completed_at = datetime.utcnow()
            await db.commit()
            return

        stream_name = stream.name or str(stream_id)

        # 原子加锁：仅当流当前无锁时才上锁并置 RUNNING，消除竞态窗口
        lock_result = await db.execute(
            update(Stream)
            .where(Stream.id == stream.id, Stream.current_task_id.is_(None))
            .values(current_task_id=task_obj.id)
        )
        if (lock_result.rowcount or 0) == 0:
            logger.warning(f"[Task {task_id}] 直播流 {stream_id} 加锁失败（已被其他任务占用），跳过。")
            task_obj.status = "SKIPPED"
            task_obj.result = {"error": "Stream is being analyzed by another task"}
            task_obj.completed_at = datetime.utcnow()
            await db.commit()
            return

        task_obj.status = "RUNNING"
        task_obj.started_at = datetime.utcnow()
        task_obj.total = 1
        task_obj.queued_at = None
        await db.commit()

        # 通知：开始分析
        try:
            await notify_analysis_progress(
                db=db,
                current=0,
                total=1,
                current_stream_name=stream_name,
                task_identifier=task_identifier,
                is_queued=False,
                task_type="single",
            )
        except Exception as ne:
            logger.warning(f"[Task {task_id}] 创建开始通知失败: {ne}")

    # 2. 执行分析
        await notify_task_started(
            db=db,
            task_id=task_id,
            task_name=task_obj.task_name,
            task_type=task_obj.task_type,
            total=1,
        )

    try:
        async with async_session_maker() as db:
            if mode == "quick":
                analysis_result = await analyze_stream_quick(db, str(stream_id))
            else:
                analysis_result = await analyze_stream_full(db, str(stream_id))

            task_obj_update = (await db.execute(select(Task).where(Task.id == task_uuid))).scalar_one()
            task_obj_update.status = "SUCCESS"
            task_obj_update.result = analysis_result if isinstance(analysis_result, dict) else {"status": "done"}
            task_obj_update.progress = 1
            task_obj_update.completed_at = datetime.utcnow()
            await db.commit()

            # 通知：分析完成
            try:
                await notify_analysis_progress(
                    db=db,
                    current=1,
                    total=1,
                    current_stream_name=stream_name,
                    task_identifier=task_identifier,
                    is_queued=False,
                    task_type="single",
                )
            except Exception as ne:
                logger.warning(f"[Task {task_id}] 创建完成通知失败: {ne}")
            await notify_task_completed(
                db=db,
                task_id=task_id,
                task_name=task_obj_update.task_name,
                task_type=task_obj_update.task_type,
                total=1,
                success=True,
            )

    except Exception as e:
        logger.error(f"[Task {task_id}] 分析直播流 {stream_id} 时发生错误: {e}", exc_info=True)
        async with async_session_maker() as db:
            task_obj_update = (await db.execute(select(Task).where(Task.id == task_uuid))).scalar_one()
            task_obj_update.status = "FAILED"
            task_obj_update.result = {"error": str(e)}
            task_obj_update.completed_at = datetime.utcnow()
            await db.commit()

            # 通知：分析失败（用 warning 级别）
            try:
                from app.services.notification_service import create_notification
                await create_notification(
                    db=db,
                    issuer="system",
                    subject=f"[{task_identifier}] 单条直播流测试失败",
                    context=f"直播流 '{stream_name}' 分析失败：{str(e)[:200]}",
                    severity="error",
                    notification_channels=["maintenance-timeline"],
                    valid_hours=24,
                )
            except Exception as ne:
                logger.warning(f"[Task {task_id}] 创建失败通知失败: {ne}")
            await notify_task_completed(
                db=db,
                task_id=task_id,
                task_name=task_obj_update.task_name,
                task_type=task_obj_update.task_type,
                total=1,
                success=False,
                error_message=str(e),
            )

    finally:
        async with async_session_maker() as db:
            stream_update = (await db.execute(select(Stream).where(Stream.id == stream_id))).scalar_one_or_none()
            if stream_update and stream_update.current_task_id == task_uuid:
                stream_update.current_task_id = None
                await db.commit()
        logger.info(f"[Task {task_id}] 单个流分析完成。")


@shared_task(bind=True, name="app.tasks.analysis.batch_analyze_streams_task",
             max_retries=1, time_limit=7200, soft_time_limit=7100)
@run_async
async def batch_analyze_streams_task(self, task_id: str):
    """批量分析直播流任务 - 由调度器分发调用

    支持两种 payload 格式:
      1. {"stream_ids": [...], "mode": "full"}  - 指定流列表
      2. {"mode": "full"}                       - 分析所有活跃流 (AUTO_ANALYSIS)
    """
    from app.services.notification_service import notify_analysis_progress

    task_uuid = uuid.UUID(task_id)
    task_identifier = task_id[:8]

    async with async_session_maker() as db:
        task_obj = (await db.execute(select(Task).where(Task.id == task_uuid))).scalar_one_or_none()
        if not task_obj:
            logger.error(f"[Task {task_id}] 任务不存在，终止执行。")
            return

        stream_ids = task_obj.payload.get("stream_ids", [])
        mode = task_obj.payload.get("mode", "full")
        # AUTO_ANALYSIS 不带 stream_ids，需要查询所有活跃流
        is_auto = task_obj.task_type == "AUTO_ANALYSIS"

        if not stream_ids:
            result = await db.execute(select(Stream.id).where(Stream.active != "false"))
            stream_ids = [str(row[0]) for row in result.all()]

        if not stream_ids:
            task_obj.status = "SUCCESS"
            task_obj.result = {"message": "No streams to analyze"}
            task_obj.completed_at = datetime.utcnow()
            await db.commit()
            await notify_task_completed(
                db=db,
                task_id=task_id,
                task_name=task_obj.task_name,
                task_type=task_obj.task_type,
                total=0,
                success=True,
            )
            return

        task_obj.status = "RUNNING"
        task_obj.started_at = datetime.utcnow()
        task_obj.total = len(stream_ids)
        task_obj.queued_at = None
        await db.commit()

        # 通知：开始批量分析
        try:
            await notify_analysis_progress(
                db=db,
                current=0,
                total=len(stream_ids),
                current_stream_name="",
                task_identifier=task_identifier,
                is_queued=False,
                task_type="full",
            )
        except Exception as ne:
            logger.warning(f"[Task {task_id}] 创建开始通知失败: {ne}")

    # 2. 筛选可分析的流并原子加锁
    async with async_session_maker() as db:
        ids_requested = []
        for sid in stream_ids:
            stream = (await db.execute(select(Stream).where(Stream.id == sid))).scalar_one_or_none()
            if not stream:
                continue
            if stream.current_task_id:
                logger.debug(f"[Task {task_id}] 流 {sid} 正在被其他任务分析，跳过。")
                continue
            ids_requested.append(str(stream.id))

        streams_to_analyze = []
        if ids_requested:
            # 原子加锁：仅更新当前无锁的流，并按实际影响行数确定归属，
            # 消除"检查-上锁"两步之间的竞态窗口
            lock_result = await db.execute(
                update(Stream)
                .where(Stream.id.in_(ids_requested), Stream.current_task_id.is_(None))
                .values(current_task_id=task_uuid)
            )
            locked_ids = lock_result.rowcount or 0

            if locked_ids > 0:
                locked_rows = await db.execute(
                    select(Stream.id, Stream.name).where(
                        Stream.current_task_id == task_uuid
                    )
                )
                for row_id, row_name in locked_rows.all():
                    streams_to_analyze.append((str(row_id), row_name or str(row_id)))

            skipped = len(ids_requested) - len(streams_to_analyze)
            if skipped > 0:
                logger.debug(f"[Task {task_id}] {skipped} 条流因并发竞争未能加锁，跳过。")

        await db.commit()

    if not streams_to_analyze:
        async with async_session_maker() as db:
            task_final = (await db.execute(select(Task).where(Task.id == task_uuid))).scalar_one()
            task_final.status = "SUCCESS"
            task_final.result = {"message": "All streams are being analyzed by other tasks"}
            task_final.completed_at = datetime.utcnow()
            await db.commit()
        return

    # 3. 使用信号量进行并发控制
    async with async_session_maker() as db:
        max_workers = await ConfigService.get_analysis_workers(db)
    logger.info(f"[Task {task_id}] 并发 Worker 数: {max_workers}")
    semaphore = asyncio.Semaphore(max_workers)
    completed_count = 0
    success_count = 0
    failed_count = 0
    current_active = 0
    worker_counter = 0
    lock = asyncio.Lock()
    ids_only = [s[0] for s in streams_to_analyze]
    total = len(streams_to_analyze)
    total_count = len(streams_to_analyze)

    async def analyze_one(sid: str, sname: str):
        nonlocal completed_count, success_count, failed_count, current_active, worker_counter
        async with semaphore:
            async with lock:
                current_active += 1
                worker_counter += 1
                worker_no = worker_counter
            logger.info(f"[Task {task_id}] Worker {current_active}/{max_workers} (#{worker_no}) 开始分析: {sname}")
            try:
                async with async_session_maker() as session:
                    if mode == "quick":
                        await analyze_stream_quick(session, sid)
                    else:
                        await analyze_stream_full(session, sid)
                    success_count += 1
                    logger.info(f"[Task {task_id}] Worker {current_active}/{max_workers} (#{worker_no}) 完成: {sname}")
            except Exception as e:
                logger.error(f"[Task {task_id}] 分析流 {sid} 失败: {e}")
                failed_count += 1
            finally:
                completed_count += 1
                async with lock:
                    current_active -= 1
                # 进度落库节流：每 PROGRESS_INTERVAL 条或最后一条才写库，
                # 万级流时避免每条流一次 UPDATE 事务
                if completed_count % PROGRESS_INTERVAL == 0 or completed_count == total_count:
                    try:
                        async with async_session_maker() as session:
                            await session.execute(
                                update(Task).where(Task.id == task_uuid).values(progress=completed_count)
                            )
                            await session.commit()

                            if completed_count % 5 == 0 or completed_count == total_count:
                                await notify_task_progress(
                                    db=session,
                                    task_id=task_id,
                                    task_name="",
                                    task_type="BATCH_ANALYSIS",
                                    progress=completed_count,
                                    total=total_count,
                                )
                    except Exception as pe:
                        logger.warning(f"[Task {task_id}] 更新任务进度失败: {pe}")

                # 按间隔更新通知进度（避免每个流都写库）
                if completed_count % NOTIFY_INTERVAL == 0 or completed_count == total:
                    try:
                        async with async_session_maker() as session:
                            await notify_analysis_progress(
                                db=session,
                                current=completed_count,
                                total=total,
                                current_stream_name=sname,
                                task_identifier=task_identifier,
                                is_queued=False,
                                task_type="full",
                            )
                    except Exception as ne:
                        logger.warning(f"[Task {task_id}] 更新进度通知失败: {ne}")

    # 执行所有分析
    tasks = [analyze_one(sid, sname) for sid, sname in streams_to_analyze]
    await asyncio.gather(*tasks)

    async with async_session_maker() as db:
        if ids_only:
            await db.execute(
                update(Stream)
                .where(Stream.id.in_(ids_only), Stream.current_task_id == task_uuid)
                .values(current_task_id=None)
            )

        task_final = (await db.execute(select(Task).where(Task.id == task_uuid))).scalar_one()
        task_final.status = "SUCCESS"
        task_final.completed_at = datetime.utcnow()
        task_final.result = {
            "success": success_count,
            "failed": failed_count,
            "total": total,
        }
        await db.commit()

        # 通知：批量分析完成
        try:
            await notify_analysis_progress(
                db=db,
                current=total,
                total=total,
                current_stream_name="",
                task_identifier=task_identifier,
                is_queued=False,
                task_type="full",
            )
        except Exception as ne:
            logger.warning(f"[Task {task_id}] 创建完成通知失败: {ne}")
        await notify_task_completed(
            db=db,
            task_id=task_id,
            task_name=task_final.task_name,
            task_type=task_final.task_type,
            total=len(streams_to_analyze),
            success=True,
        )

        # 批量分析完成后检查阈值并发送告警通知（不可达率/可用频道/频道全下线）
        try:
            from app.services.stream_analyzer import check_thresholds_and_notify
            await check_thresholds_and_notify(db)
        except Exception as te:
            logger.error(f"[Task {task_id}] 阈值检查失败: {te}", exc_info=True)

    logger.info(f"[Task {task_id}] 批量分析完成。成功: {success_count}, 失败: {failed_count}")
