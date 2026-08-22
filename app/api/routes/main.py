#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""API 路由 (v0.3.0 重构版)

变更说明:
  - create_source: 创建订阅源后不再直接调用 Celery，而是创建 Task 记录
  - refresh_source: 手动刷新订阅源时创建 Task 记录
  - trigger_analysis: 分析触发改为创建 Task 记录，由调度器处理
  - 新增 /api/v1/tasks 端点用于查询任务状态
  - 其他所有端点保持不变
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, text, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import urlparse
from datetime import datetime
import logging
import os

from app.core.database import get_db, async_session_maker
from app.models.models import (
    Channel,
    Stream,
    Task,
    Notification,
    NotificationItem,
    NotificationChannelConfig,
    SMTPConfig as SMTPConfigModel,
    SystemConfig,
)
from app.utils.redis_client import redis_client
from app.schemas.schemas import (
    SubscriptionSourceCreate,
    SubscriptionSourceUpdate,
    SubscriptionSourceResponse,
    StreamResponse,
    ChannelResponse,
    NotificationResponse,
    NotificationCreate,
    HealthResponse,
    StreamUpdateActive,
    ChannelOrderUpdate,
    AnalysisTriggerRequest,
    SMTPConfigResponse,
    SMTPConfigUpdate,
    SystemConfigResponse,
    SystemConfigUpdate,
    NotificationItemResponse,
    NotificationItemUpdate,
    NotificationChannelConfigResponse,
    NotificationChannelConfigUpdate,
    LogEntryResponse,
)
from app.services import source_manager, channel_matcher, stream_analyzer, playlist_builder

logger = logging.getLogger(__name__)

router = APIRouter()


# ========================================
# 健康检查
# ========================================

@router.get("/health", response_model=HealthResponse)
async def health_check():
    checks = {"database": "unknown", "redis": "unknown"}

    try:
        async with async_session_maker() as db:
            await db.execute(text("SELECT 1"))
            checks["database"] = "ok"
    except Exception as e:
        logger.error(f"Database check error: {e}")
        checks["database"] = "error"

    try:
        client = await redis_client.get_client()
        await client.ping()
        checks["redis"] = "ok"
    except Exception as e:
        logger.error(f"Redis check error: {e}")
        checks["redis"] = "error"

    status = "healthy" if all(v == "ok" for v in checks.values()) else "unhealthy"
    from app.core.config import get_settings
    return HealthResponse(status=status, checks=checks, version=get_settings().APP_VERSION)


# ========================================
# 播放列表
# ========================================

@router.get("/playfast")
async def get_playlist_playfast(db: AsyncSession = Depends(get_db)):
    content = await playlist_builder.generate_playlist(db, "playfast")
    return PlainTextResponse(content=content, media_type="audio/x-mpegurl", headers={"Content-Disposition": 'attachment; filename="playfast.m3u"'})


@router.get("/playbest")
async def get_playlist_playbest(db: AsyncSession = Depends(get_db)):
    content = await playlist_builder.generate_playlist(db, "playbest")
    return PlainTextResponse(content=content, media_type="audio/x-mpegurl", headers={"Content-Disposition": 'attachment; filename="playbest.m3u"'})


@router.get("/playstable")
async def get_playlist_playstable(db: AsyncSession = Depends(get_db)):
    content = await playlist_builder.generate_playlist(db, "playstable")
    return PlainTextResponse(content=content, media_type="audio/x-mpegurl", headers={"Content-Disposition": 'attachment; filename="playstable.m3u"'})


@router.get("/playoptimized")
async def get_playlist_playoptimized(db: AsyncSession = Depends(get_db)):
    content = await playlist_builder.generate_playlist(db, "playoptimized")
    return PlainTextResponse(content=content, media_type="audio/x-mpegurl", headers={"Content-Disposition": 'attachment; filename="playoptimized.m3u"'})


# ========================================
# 订阅源管理 (重构: 使用 Task 表)
# ========================================

@router.get("/api/v1/sources", response_model=list[SubscriptionSourceResponse])
async def get_sources(db: AsyncSession = Depends(get_db)):
    sources = await source_manager.get_all_sources(db)
    return sources


@router.post("/api/v1/sources", response_model=SubscriptionSourceResponse)
async def create_source(
    source: SubscriptionSourceCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建订阅源（异步化：仅创建记录 + 刷新任务，立即返回）

    首次刷新、频道匹配、视频分析全部由 SOURCE_REFRESH 任务异步完成，
    避免在请求路径中同步下载/解析万级 M3U 导致超时。
    """
    # 轻量校验：仅确认 URL 可达且为 M3U 头，不做完整下载解析
    is_valid, message = await source_manager.validate_subscription_source_light(source.url)
    if not is_valid:
        raise HTTPException(status_code=400, detail=message)

    try:
        new_source = await source_manager.create_source_record(
            db,
            source.nickname,
            source.url,
            source.refresh_frequency_hours,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 创建初始刷新任务（Worker 领取后完成首次刷新 + 匹配）
    refresh_task = Task(
        task_name=f"Initial Refresh: {new_source.nickname}",
        task_type="SOURCE_REFRESH",
        priority=7,
        payload={"source_id": new_source.id},
    )
    db.add(refresh_task)

    await db.commit()

    return new_source


@router.put("/api/v1/sources/{source_id}", response_model=SubscriptionSourceResponse)
async def update_source(
    source_id: int,
    source: SubscriptionSourceUpdate,
    db: AsyncSession = Depends(get_db),
):
    updated = await source_manager.update_source(
        db,
        source_id,
        source.nickname,
        source.url,
        source.refresh_frequency_hours,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Source not found")
    return updated


@router.delete("/api/v1/sources/{source_id}")
async def delete_source(
    source_id: int,
    delete_streams: bool = False,
    db: AsyncSession = Depends(get_db),
):
    deleted = await source_manager.delete_source(db, source_id, delete_streams)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"status": "deleted"}


@router.post("/api/v1/sources/{source_id}/refresh")
async def refresh_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
):
    """手动刷新订阅源 - 创建一个高优先级的刷新 Task"""
    from app.models.models import SubscriptionSource

    source = (await db.execute(
        select(SubscriptionSource).where(SubscriptionSource.id == source_id)
    )).scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    refresh_task = Task(
        task_name=f"Manual Refresh: {source.nickname}",
        task_type="SOURCE_REFRESH",
        priority=7,
        payload={"source_id": source_id},
    )
    db.add(refresh_task)
    await db.commit()

    return {"status": "submitted", "task_id": str(refresh_task.id), "message": "Refresh task created."}


# ========================================
# 频道管理
# ========================================

@router.get("/api/v1/channels", response_model=list[ChannelResponse])
async def get_channels(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).order_by(Channel.order_index))
    channels = result.scalars().all()
    return channels


@router.put("/api/v1/channels/{channel_id}/order")
async def update_channel_order(
    channel_id: int,
    order_data: ChannelOrderUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    channel.order_index = order_data.order_index
    await db.commit()
    return {"status": "updated"}


# ========================================
# 直播流管理
# ========================================

@router.get("/api/v1/streams", response_model=list[StreamResponse])
async def get_streams(
    channel_id: int = None,
    unmatched: bool = False,
    limit: int = 1000,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    # 分页 + 数据库层过滤，避免全表加载（万级流时响应体可达数十 MB）
    limit = max(1, min(limit, 5000))
    offset = max(0, offset)

    query = select(Stream)
    if unmatched:
        query = query.where(Stream.channel_id == None)
    elif channel_id:
        query = query.where(Stream.channel_id == channel_id)

    query = query.order_by(Stream.created_at).offset(offset).limit(limit)
    result = await db.execute(query)
    streams = result.scalars().all()

    return [StreamResponse(
        id=str(s.id),
        url=s.url,
        name=s.name,
        url_hash=s.url_hash,
        source_ids=s.source_ids or [],
        channel_id=s.channel_id,
        latency_ms=s.latency_ms,
        bitrate_kbps=s.bitrate_kbps,
        stability_score=float(s.stability_score) if s.stability_score else None,
        video_width=s.video_width,
        video_height=s.video_height,
        video_fps=float(s.video_fps) if s.video_fps else None,
        video_codec=s.video_codec,
        video_bit_depth=s.video_bit_depth,
        video_color_profile=s.video_color_profile,
        audio_codec=s.audio_codec,
        video_analyzed_at=s.video_analyzed_at,
        video_bitrate_kbps=s.video_bitrate_kbps,
        video_analysis_failed=s.video_analysis_failed,
        unreachable_count=s.unreachable_count,
        active=s.active,
        last_analysis_time=s.last_analysis_time,
        enhanced_analysis_failed=s.enhanced_analysis_failed,
        first_discovered_at=s.first_discovered_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
    ) for s in streams]


@router.put("/api/v1/streams/{stream_id}/active")
async def update_stream_active(
    stream_id: str,
    active_data: StreamUpdateActive,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Stream).where(Stream.id == stream_id))
    stream = result.scalar_one_or_none()
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")
    stream.active = active_data.active
    await db.commit()
    return {"status": "updated"}


@router.post("/api/v1/streams/{stream_id}/bind")
async def bind_stream_to_channel(
    stream_id: str,
    channel_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await channel_matcher.bind_stream_to_channel(db, stream_id, channel_id)
    if not result:
        raise HTTPException(status_code=404, detail="Stream not found")
    return {"status": "bound"}


@router.post("/api/v1/streams/{stream_id}/unbind")
async def unbind_stream_from_channel(
    stream_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await channel_matcher.bind_stream_to_channel(db, stream_id, None)
    if not result:
        raise HTTPException(status_code=404, detail="Stream not found")
    return {"status": "unbound"}


@router.post("/api/v1/streams/batch-bind")
async def batch_bind_streams(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    stream_ids = data.get("stream_ids", [])
    channel_id = data.get("channel_id")
    if not stream_ids:
        raise HTTPException(status_code=400, detail="stream_ids is required")
    result = await channel_matcher.batch_bind_streams(db, stream_ids, channel_id)
    return {
        "status": "success",
        "message": f"成功绑定 {result['success']} 个直播流" if channel_id else f"成功解绑 {result['success']} 个直播流",
        **result,
    }


@router.post("/api/v1/streams/create-channel-bind")
async def create_channel_and_bind(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    channel_name = data.get("channel_name", "").strip()
    stream_ids = data.get("stream_ids", [])
    if not channel_name:
        raise HTTPException(status_code=400, detail="channel_name is required")
    if not stream_ids:
        raise HTTPException(status_code=400, detail="stream_ids is required")
    result = await channel_matcher.create_channel_and_bind(db, stream_ids, channel_name)
    return {
        "status": "success",
        "message": f"成功创建频道 '{channel_name}' 并绑定 {result['success']} 个直播流",
        **result,
    }


# ========================================
# 分析触发 (重构: 使用 Task 表)
# ========================================

@router.post("/api/v1/analysis/trigger")
async def trigger_analysis(
    request: AnalysisTriggerRequest,
    db: AsyncSession = Depends(get_db),
):
    """触发分析任务 - 创建 Task 记录，由调度器处理

    优先级:
      - 单个流: 9 (最高，可插队)
      - 批量/全局: 5
    """
    if request.stream_ids and len(request.stream_ids) == 1:
        # 单个流高优先级分析
        stream_id = request.stream_ids[0]
        new_task = Task(
            task_name=f"Single Stream Analysis: {stream_id[:8]}...",
            task_type="SINGLE_STREAM_ANALYSIS",
            priority=9,
            payload={"stream_id": stream_id, "mode": "full"},
        )
        db.add(new_task)
        await db.commit()
        return {"status": "submitted", "task_id": str(new_task.id), "total": 1, "mode": "full", "is_single": True}

    elif request.stream_ids:
        # 批量流分析
        new_task = Task(
            task_name=f"Batch Analysis: {len(request.stream_ids)} streams",
            task_type="BATCH_ANALYSIS",
            priority=5,
            payload={"stream_ids": request.stream_ids, "mode": request.mode or "full"},
        )
        db.add(new_task)
        await db.commit()
        return {"status": "submitted", "task_id": str(new_task.id), "total": len(request.stream_ids), "mode": request.mode or "full"}

    else:
        # 全局分析 - 不指定 stream_ids，由 batch_analyze_streams_task 自动获取所有活跃流
        # 仅统计数量用于响应，不把全量 id 写入 payload（避免数 MB 的 JSONB）
        count_result = await db.execute(
            select(func.count(Stream.id)).where(Stream.active != "false")
        )
        total_streams = count_result.scalar() or 0

        if total_streams == 0:
            return {"status": "no_streams", "message": "No active streams to analyze"}

        new_task = Task(
            task_name="Manual Enhanced Analysis (All Streams)",
            task_type="BATCH_ANALYSIS",
            priority=5,
            payload={"mode": request.mode or "full"},
        )
        db.add(new_task)
        await db.commit()
        return {"status": "submitted", "task_id": str(new_task.id), "total": total_streams, "mode": request.mode or "full"}


@router.get("/api/v1/analysis/mode")
async def get_analysis_mode():
    redis = await redis_client.get_client()
    mode = await redis.get("analysis:mode") or "full"
    return {"mode": mode}


@router.post("/api/v1/analysis/mode")
async def set_analysis_mode(data: dict):
    mode = data.get("mode", "full")
    if mode not in ["quick", "full"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'quick' or 'full'")
    redis = await redis_client.get_client()
    # 不设置 TTL：分析模式是持久性配置，1 小时后静默回退为 full 属于 Bug
    await redis.set("analysis:mode", mode)
    return {"mode": mode, "message": f"Analysis mode set to {mode}"}


# ========================================
# 任务管理 (新增)
# ========================================

@router.get("/api/v1/tasks")
async def get_tasks(
    status: str = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """获取最近的任务列表"""
    query = select(Task).order_by(Task.created_at.desc()).limit(limit)
    if status:
        query = query.where(Task.status == status)
    result = await db.execute(query)
    tasks = result.scalars().all()
    return [{
        "id": str(t.id),
        "task_name": t.task_name,
        "task_type": t.task_type,
        "priority": t.priority,
        "status": t.status,
        "progress": t.progress,
        "total": t.total,
        "result": t.result,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    } for t in tasks]


@router.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个任务详情"""
    import uuid
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID")

    task = (await db.execute(select(Task).where(Task.id == task_uuid))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "id": str(task.id),
        "task_name": task.task_name,
        "task_type": task.task_type,
        "priority": task.priority,
        "status": task.status,
        "progress": task.progress,
        "total": task.total,
        "result": task.result,
        "payload": task.payload,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


# ========================================
# Benchmark
# ========================================

@router.get("/api/v1/benchmark")
async def get_benchmark(db: AsyncSession = Depends(get_db)):
    return await playlist_builder.get_benchmark_data(db)


# ========================================
# 通知管理
# ========================================

@router.get("/api/v1/notifications", response_model=list[NotificationResponse])
async def get_notifications(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Notification).where(
            Notification.read_button != "clicked",
            Notification.valid_from <= datetime.utcnow(),
            (Notification.valid_until == None) | (Notification.valid_until >= datetime.utcnow()),
        ).order_by(Notification.created_at.desc())
    )
    return result.scalars().all()


@router.post("/api/v1/notifications", response_model=NotificationResponse)
async def create_notification(
    notification: NotificationCreate,
    db: AsyncSession = Depends(get_db),
):
    new_notification = Notification(
        issuer=notification.issuer,
        subject=notification.subject,
        context=notification.context,
        severity=notification.severity,
        notification_channels=notification.notification_channels,
        valid_until=notification.valid_until,
    )
    db.add(new_notification)
    await db.commit()
    await db.refresh(new_notification)
    return new_notification


@router.put("/api/v1/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Notification).where(Notification.id == notification_id))
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read_button = "clicked"
    await db.commit()
    return {"status": "marked as read"}


@router.delete("/api/v1/notifications/{notification_id}")
async def delete_notification(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Notification).where(Notification.id == notification_id))
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    await db.delete(notification)
    await db.commit()
    return {"status": "deleted"}


@router.post("/api/v1/notifications/test-smtp")
async def test_smtp_config(data: dict):
    from app.services.smtp_service import SMTPConfig, SMTPService

    config = SMTPConfig(
        host=data.get('host', ''),
        port=data.get('port', 587),
        username=data.get('username', ''),
        password=data.get('password', ''),
        sender=data.get('sender', ''),
        use_tls=data.get('use_tls', True),
    )
    smtp_service = SMTPService(config)
    success, message = smtp_service.test_connection()
    if not success:
        return {"success": False, "message": message}

    recipient = data.get('recipient') or config.sender
    success, message = smtp_service.send_test_email(recipient)
    if success:
        return {"success": True, "message": f"测试邮件已发送至 {recipient}"}
    else:
        return {"success": False, "message": message}


# ========================================
# SMTP 配置
# ========================================

@router.get("/api/v1/smtp-config", response_model=SMTPConfigResponse)
async def get_smtp_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SMTPConfigModel))
    config = result.scalar_one_or_none()
    if not config:
        config = SMTPConfigModel()
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return config


@router.put("/api/v1/smtp-config", response_model=SMTPConfigResponse)
async def update_smtp_config(
    config_update: SMTPConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SMTPConfigModel))
    config = result.scalar_one_or_none()
    if not config:
        config = SMTPConfigModel()
        db.add(config)
    update_data = config_update.model_dump(exclude_unset=True)
    # 安全：前端不再持有明文密码，空字符串/None 表示"不修改密码"
    if "password" in update_data and not update_data["password"]:
        del update_data["password"]
    for field, value in update_data.items():
        setattr(config, field, value)
    await db.commit()
    await db.refresh(config)
    return config


# ========================================
# 直播流域名
# ========================================

@router.get("/api/v1/stream-domains")
async def get_stream_domains(db: AsyncSession = Depends(get_db)):
    # SQL 下推：避免全表加载到内存仅为解析 hostname
    result = await db.execute(
        text("SELECT DISTINCT substring(url from '//([^/:]+)') AS domain FROM streams WHERE url IS NOT NULL")
    )
    domains = sorted(
        d for (d,) in result.all() if d
    )
    return {"domains": domains, "count": len(domains)}


# ========================================
# 系统配置
# ========================================

@router.get("/api/v1/system-config", response_model=SystemConfigResponse)
async def get_system_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemConfig))
    config = result.scalar_one_or_none()
    if not config:
        config = SystemConfig()
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return config


@router.put("/api/v1/system-config", response_model=SystemConfigResponse)
async def update_system_config(
    config_update: SystemConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    from app.services.config_service import ConfigService
    from app.services.log_service import LogService

    result = await db.execute(select(SystemConfig))
    config = result.scalar_one_or_none()
    if not config:
        config = SystemConfig()
        db.add(config)
    update_data = config_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)
    await db.commit()
    await db.refresh(config)
    await ConfigService.invalidate_cache(db)
    await LogService.update_logging_status(db)
    return config


# ========================================
# 日志
# ========================================

@router.get("/api/v1/logs", response_model=list[LogEntryResponse])
async def get_logs(
    limit: int = 100,
    offset: int = 0,
    level: str = None,
    db: AsyncSession = Depends(get_db),
):
    from app.services.log_service import LogService
    logs = await LogService.get_logs(db, limit=limit, offset=offset, level=level)
    return logs


@router.get("/api/v1/logs/export")
async def export_logs(db: AsyncSession = Depends(get_db)):
    from app.services.log_service import LogService
    log_content = await LogService.export_logs(db)
    return PlainTextResponse(
        content=log_content,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=iptv-manager-logs.txt"},
    )


# ========================================
# 通知事项
# ========================================

@router.get("/api/v1/notification-items", response_model=list[NotificationItemResponse])
async def get_notification_items(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationItem).order_by(NotificationItem.id))
    items = result.scalars().all()
    if not items:
        default_items = [
            NotificationItem(key="source_refresh_failed", name="订阅源自动更新异常", enabled=True, has_status_config=True, statuses=["failed", "timeout"], channels=["homepage"]),
            NotificationItem(key="system_status_anomaly", name="系统状态异常", enabled=True, has_status_config=True, statuses=["error"], channels=["homepage"]),
            NotificationItem(key="stream_unreachable", name="直播流不可达阈值", enabled=True, has_threshold=True, threshold_value=30, channels=["homepage"]),
            NotificationItem(key="channel_available", name="可用频道阈值", enabled=True, has_threshold=True, threshold_value=50, channels=["homepage"]),
            NotificationItem(key="channel_all_down", name="频道全线路不可用", enabled=True, channels=["homepage"]),
        ]
        for item in default_items:
            db.add(item)
        await db.commit()
        result = await db.execute(select(NotificationItem).order_by(NotificationItem.id))
        items = result.scalars().all()
    return items


@router.put("/api/v1/notification-items/{item_key}", response_model=NotificationItemResponse)
async def update_notification_item(
    item_key: str,
    item_update: NotificationItemUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(NotificationItem).where(NotificationItem.key == item_key))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Notification item not found")
    update_data = item_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return item


# ========================================
# 通知管道配置
# ========================================

@router.get("/api/v1/notification-channel-configs", response_model=list[NotificationChannelConfigResponse])
async def get_notification_channel_configs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationChannelConfig).order_by(NotificationChannelConfig.id))
    configs = result.scalars().all()
    if not configs:
        default_configs = [
            NotificationChannelConfig(channel_key="homepage", enabled=True, config={"defaultMessage": "系统正常运行中"}),
            NotificationChannelConfig(channel_key="smtp", enabled=False, config={}),
        ]
        for config in default_configs:
            db.add(config)
        await db.commit()
        result = await db.execute(select(NotificationChannelConfig).order_by(NotificationChannelConfig.id))
        configs = result.scalars().all()
    return configs


@router.put("/api/v1/notification-channel-configs/{channel_key}", response_model=NotificationChannelConfigResponse)
async def update_notification_channel_config(
    channel_key: str,
    config_update: NotificationChannelConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(NotificationChannelConfig).where(NotificationChannelConfig.channel_key == channel_key))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Notification channel config not found")
    update_data = config_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)
    await db.commit()
    await db.refresh(config)
    return config


# ========================================
# 配置备份与恢复
# ========================================

@router.get("/api/v1/config/backup")
async def export_config(db: AsyncSession = Depends(get_db)):
    """导出所有配置为 JSON 文件"""
    import json
    
    config_data = {}
    
    system_config = (await db.execute(select(SystemConfig).limit(1))).scalar_one_or_none()
    if system_config:
        config_data["system_config"] = {
            "analysis_frequency_minutes": system_config.analysis_frequency_minutes,
            "analysis_workers": system_config.analysis_workers,
            "analysis_timeout_seconds": system_config.analysis_timeout_seconds,
            "forgiveness_param": system_config.forgiveness_param,
            "source_refresh_frequency_hours": system_config.source_refresh_frequency_hours,
            "log_enabled": system_config.log_enabled,
            "log_retention_hours": system_config.log_retention_hours,
        }
    
    smtp_config = (await db.execute(select(SMTPConfigModel).limit(1))).scalar_one_or_none()
    if smtp_config:
        config_data["smtp_config"] = {
            "enabled": smtp_config.enabled,
            "host": smtp_config.host,
            "port": smtp_config.port,
            "sender": smtp_config.sender,
            "username": smtp_config.username,
            "use_tls": smtp_config.use_tls,
        }
    
    notification_items_result = await db.execute(select(NotificationItem))
    config_data["notification_items"] = [
        {
            "key": item.key,
            "name": item.name,
            "enabled": item.enabled,
            "has_threshold": item.has_threshold,
            "threshold_value": item.threshold_value,
            "has_status_config": item.has_status_config,
            "statuses": item.statuses,
            "channels": item.channels,
        }
        for item in notification_items_result.scalars().all()
    ]
    
    channel_configs_result = await db.execute(select(NotificationChannelConfig))
    config_data["notification_channel_configs"] = [
        {
            "channel_key": config.channel_key,
            "enabled": config.enabled,
            "config": config.config,
        }
        for config in channel_configs_result.scalars().all()
    ]
    
    sources_result = await db.execute(select(SubscriptionSource))
    config_data["subscription_sources"] = [
        {
            "nickname": source.nickname,
            "url": source.url,
            "refresh_frequency_hours": source.refresh_frequency_hours,
        }
        for source in sources_result.scalars().all()
    ]
    
    config_data["export_time"] = datetime.utcnow().isoformat()
    config_data["version"] = "0.4.0"
    
    return PlainTextResponse(
        content=json.dumps(config_data, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=iptv-manager-config.json"},
    )


@router.post("/api/v1/config/restore")
async def import_config(
    config_data: dict,
    db: AsyncSession = Depends(get_db),
):
    """从 JSON 文件恢复配置"""
    from app.models.models import SubscriptionSource
    
    restored_sources = []
    skipped_sources = []
    failed_sources = []
    
    if "system_config" in config_data:
        system_config = (await db.execute(select(SystemConfig).limit(1))).scalar_one_or_none()
        if system_config:
            for key, value in config_data["system_config"].items():
                if hasattr(system_config, key):
                    setattr(system_config, key, value)
    
    if "smtp_config" in config_data:
        smtp_config = (await db.execute(select(SMTPConfigModel).limit(1))).scalar_one_or_none()
        if smtp_config:
            for key, value in config_data["smtp_config"].items():
                if hasattr(smtp_config, key):
                    setattr(smtp_config, key, value)
    
    if "notification_items" in config_data:
        for item_data in config_data["notification_items"]:
            result = await db.execute(select(NotificationItem).where(NotificationItem.key == item_data["key"]))
            item = result.scalar_one_or_none()
            if item:
                for key, value in item_data.items():
                    if key != "key" and hasattr(item, key):
                        setattr(item, key, value)
    
    if "notification_channel_configs" in config_data:
        for config_data_item in config_data["notification_channel_configs"]:
            result = await db.execute(
                select(NotificationChannelConfig).where(NotificationChannelConfig.channel_key == config_data_item["channel_key"])
            )
            config = result.scalar_one_or_none()
            if config:
                for key, value in config_data_item.items():
                    if key != "channel_key" and hasattr(config, key):
                        setattr(config, key, value)
    
    if "subscription_sources" in config_data:
        for source_data in config_data["subscription_sources"]:
            url = source_data.get("url")
            nickname = source_data.get("nickname")
            refresh_frequency_hours = source_data.get("refresh_frequency_hours", 2)
            
            if not url or not nickname:
                failed_sources.append({"nickname": nickname or "未知", "reason": "缺少必要字段"})
                continue
            
            existing = (await db.execute(
                select(SubscriptionSource).where(SubscriptionSource.url == url)
            )).scalar_one_or_none()
            
            if existing:
                skipped_sources.append({"nickname": nickname, "reason": "订阅源已存在"})
                continue
            
            # 异步化：仅创建源记录 + 刷新任务，校验/拉取/匹配交给 Worker，
            # 避免在单请求内逐源完整下载 M3U 导致超时
            try:
                new_source = await source_manager.create_source_record(
                    db,
                    nickname,
                    url,
                    refresh_frequency_hours,
                )
            except ValueError as e:
                skipped_sources.append({"nickname": nickname, "reason": str(e)})
                continue
            
            refresh_task = Task(
                task_name=f"Config Restore Refresh: {new_source.nickname}",
                task_type="SOURCE_REFRESH",
                priority=7,
                payload={"source_id": new_source.id},
            )
            db.add(refresh_task)
            
            restored_sources.append(nickname)
    
    await db.commit()
    
    return {
        "status": "success",
        "message": "配置已恢复（订阅源将在后台异步完成首次刷新与频道匹配）",
        "details": {
            "restored_sources": restored_sources,
            "skipped_sources": skipped_sources,
            "failed_sources": failed_sources,
        }
    }


from app.models.models import SubscriptionSource
