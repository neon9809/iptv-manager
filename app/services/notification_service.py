"""通知服务模块 - 统一管理三条通知渠道

渠道说明:
  - homepage-banner: 首页通知栏，显示在页面顶部
  - maintenance-timeline: 最近维护面板，显示在首页时间线
  - smtp: 邮件通知，发送到配置的邮箱

使用方式:
  from app.services.notification_service import (
      notify_source_refresh_failed,
      notify_analysis_progress,
      notify_task_status,
  )
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import Notification
from app.services.notification_dispatcher import (
    dispatch_notification,
    CHANNEL_HOMEPAGE,
    CHANNEL_MAINTENANCE,
    CHANNEL_SMTP,
)


async def create_notification(
    db: AsyncSession,
    issuer: str,
    subject: str,
    context: str,
    severity: str = "info",
    notification_channels: Optional[list[str]] = None,
    valid_hours: int = 24
) -> Notification:
    """创建通知 (兼容旧接口)"""
    result = await dispatch_notification(
        db=db,
        issuer=issuer,
        subject=subject,
        context=context,
        severity=severity,
        channels=notification_channels,
        valid_hours=valid_hours,
    )
    if result is None:
        raise ValueError("Failed to create notification")
    return result


async def notify_source_refresh_failed(
    db: AsyncSession,
    source_name: str,
    source_url: str,
    error_message: str
):
    """订阅源刷新失败通知"""
    return await dispatch_notification(
        db=db,
        issuer="system",
        subject=f"订阅源刷新失败: {source_name}",
        context=f"订阅源 '{source_name}' 刷新失败。\nURL: {source_url}\n错误: {error_message}",
        severity="error",
        channels=[CHANNEL_HOMEPAGE, CHANNEL_SMTP],
        valid_hours=24
    )


async def notify_system_status_anomaly(
    db: AsyncSession,
    anomaly_type: str,
    details: str
):
    """系统状态异常通知"""
    return await dispatch_notification(
        db=db,
        issuer="system",
        subject=f"系统状态异常: {anomaly_type}",
        context=details,
        severity="warning",
        channels=[CHANNEL_HOMEPAGE, CHANNEL_SMTP],
        valid_hours=12
    )


async def notify_stream_unreachable_threshold(
    db: AsyncSession,
    threshold_percent: float,
    unreachable_count: int,
    total_count: int
):
    """直播流不可达阈值通知"""
    actual_percent = (unreachable_count / total_count * 100) if total_count > 0 else 0
    return await dispatch_notification(
        db=db,
        issuer="system",
        subject="直播流不可达率超过阈值",
        context=f"不可达直播流比例达到 {actual_percent:.1f}% ({unreachable_count}/{total_count})，超过设定阈值 {threshold_percent}%",
        severity="warning",
        channels=[CHANNEL_HOMEPAGE, CHANNEL_SMTP],
        valid_hours=6
    )


async def notify_available_channels_threshold(
    db: AsyncSession,
    threshold_percent: float,
    available_count: int,
    total_count: int
):
    """可用频道阈值通知"""
    actual_percent = (available_count / total_count * 100) if total_count > 0 else 0
    return await dispatch_notification(
        db=db,
        issuer="system",
        subject="可用频道比例低于阈值",
        context=f"可用频道比例仅为 {actual_percent:.1f}% ({available_count}/{total_count})，低于设定阈值 {threshold_percent}%",
        severity="warning",
        channels=[CHANNEL_HOMEPAGE, CHANNEL_SMTP],
        valid_hours=6
    )


async def notify_channel_all_streams_down(
    db: AsyncSession,
    channel_name: str
):
    """频道全线路不可用通知"""
    return await dispatch_notification(
        db=db,
        issuer="system",
        subject=f"频道全线路不可用: {channel_name}",
        context=f"频道 '{channel_name}' 的所有直播流线路均不可用，请检查订阅源或频道配置。",
        severity="error",
        channels=[CHANNEL_HOMEPAGE, CHANNEL_SMTP],
        valid_hours=12
    )


async def notify_analysis_progress(
    db: AsyncSession | None,
    current: int,
    total: int,
    current_stream_name: str = "",
    task_identifier: str = "default",
    is_queued: bool = False,
    task_type: str = "full",
    source_id: int | None = None
):
    """分析进度通知 - 显示在"最近维护"时间线中

    每个任务都有自己的独立通知，通过 task_identifier 来区分
    支持排队状态显示 [正在排队] 标识
    """
    session_provided = db is not None
    if not session_provided:
        from app.core.database import async_session_maker
        db = async_session_maker()

    try:
        if task_type == "basic" and source_id:
            task_display_name = f"订阅源 {source_id} 视频基本信息分析"
        elif task_type == "video_basic" and source_id:
            task_display_name = f"订阅源 {source_id} 视频基本信息分析"
        elif task_type == "full":
            task_display_name = "直播流质量增强分析"
        elif task_type == "single":
            task_display_name = "单条直播流测试"
        else:
            task_display_name = "分析任务"

        if is_queued:
            subject = f"[{task_identifier}] [正在排队] {task_display_name}"
            context = f"任务等待执行中... 当前队列位置稍后更新"
            severity = "info"
        elif current < total:
            subject = f"[{task_identifier}] {task_display_name} ({current}/{total})"
            context = f"测试进度: 已测试 {current}/{total}，当前测试: {current_stream_name}"
            severity = "info"
        else:
            subject = f"[{task_identifier}] {task_display_name} 完成 ({total}/{total})"
            context = f"分析完成: 共测试 {total} 个直播流"
            severity = "success"

        await dispatch_notification(
            db=db,
            issuer="system",
            subject=subject,
            context=context,
            severity=severity,
            channels=[CHANNEL_MAINTENANCE],
            valid_hours=24,
            task_identifier=task_identifier,
            update_existing=True,
        )
    finally:
        if not session_provided:
            await db.close()


async def notify_task_status(
    db: AsyncSession,
    task_id: str,
    task_name: str,
    task_type: str,
    status: str,
    progress: int = 0,
    total: int = 0,
    error_message: Optional[str] = None,
):
    """任务状态通知 - 统一的任务状态更新通知

    Args:
        db: 数据库会话
        task_id: 任务 ID
        task_name: 任务名称
        task_type: 任务类型 (SINGLE_STREAM_ANALYSIS / BATCH_ANALYSIS / AUTO_ANALYSIS / SOURCE_REFRESH)
        status: 任务状态 (PENDING / QUEUED / RUNNING / SUCCESS / FAILED)
        progress: 当前进度
        total: 总数
        error_message: 错误信息 (可选)
    """
    task_identifier = task_id[:8]

    if task_type == "SINGLE_STREAM_ANALYSIS":
        task_display_name = "单条直播流测试"
    elif task_type == "BATCH_ANALYSIS":
        task_display_name = "批量增强分析"
    elif task_type == "AUTO_ANALYSIS":
        task_display_name = "定时增强分析"
    elif task_type == "SOURCE_REFRESH":
        task_display_name = "订阅源刷新"
    elif task_type == "VIDEO_BASIC_ANALYSIS":
        task_display_name = "视频基本信息分析"
    else:
        task_display_name = task_name or "分析任务"

    if status == "PENDING":
        subject = f"[{task_identifier}] [等待中] {task_display_name}"
        context = f"任务已创建，等待调度..."
        severity = "info"
    elif status == "QUEUED":
        subject = f"[{task_identifier}] [排队中] {task_display_name}"
        context = f"任务已入队，等待执行..."
        severity = "info"
    elif status == "RUNNING":
        if total > 0:
            subject = f"[{task_identifier}] {task_display_name} ({progress}/{total})"
            context = f"执行中: 已处理 {progress}/{total}"
        else:
            subject = f"[{task_identifier}] {task_display_name} (执行中)"
            context = f"任务正在执行..."
        severity = "info"
    elif status == "SUCCESS":
        if total > 0:
            subject = f"[{task_identifier}] {task_display_name} 完成 ({total}/{total})"
            context = f"任务完成: 共处理 {total} 项"
        else:
            subject = f"[{task_identifier}] {task_display_name} 完成"
            context = f"任务执行成功"
        severity = "success"
    elif status == "FAILED":
        subject = f"[{task_identifier}] {task_display_name} 失败"
        context = f"任务执行失败: {error_message or '未知错误'}"
        severity = "error"
    else:
        subject = f"[{task_identifier}] {task_display_name} ({status})"
        context = f"任务状态: {status}"
        severity = "info"

    await dispatch_notification(
        db=db,
        issuer="system",
        subject=subject,
        context=context,
        severity=severity,
        channels=[CHANNEL_MAINTENANCE],
        valid_hours=24,
        task_identifier=task_identifier,
        update_existing=True,
    )

    if status == "FAILED":
        await dispatch_notification(
            db=db,
            issuer="system",
            subject=f"任务失败: {task_display_name}",
            context=f"任务 '{task_display_name}' 执行失败。\n任务ID: {task_id}\n错误: {error_message or '未知错误'}",
            severity="error",
            channels=[CHANNEL_HOMEPAGE, CHANNEL_SMTP],
            valid_hours=24,
        )


async def notify_task_created(
    db: AsyncSession,
    task_id: str,
    task_name: str,
    task_type: str,
):
    """任务创建通知"""
    await notify_task_status(
        db=db,
        task_id=task_id,
        task_name=task_name,
        task_type=task_type,
        status="PENDING",
    )


async def notify_task_started(
    db: AsyncSession,
    task_id: str,
    task_name: str,
    task_type: str,
    total: int = 0,
):
    """任务开始通知"""
    await notify_task_status(
        db=db,
        task_id=task_id,
        task_name=task_name,
        task_type=task_type,
        status="RUNNING",
        progress=0,
        total=total,
    )


async def notify_task_progress(
    db: AsyncSession,
    task_id: str,
    task_name: str,
    task_type: str,
    progress: int,
    total: int,
):
    """任务进度通知"""
    await notify_task_status(
        db=db,
        task_id=task_id,
        task_name=task_name,
        task_type=task_type,
        status="RUNNING",
        progress=progress,
        total=total,
    )


async def notify_task_completed(
    db: AsyncSession,
    task_id: str,
    task_name: str,
    task_type: str,
    total: int = 0,
    success: bool = True,
    error_message: Optional[str] = None,
):
    """任务完成通知"""
    await notify_task_status(
        db=db,
        task_id=task_id,
        task_name=task_name,
        task_type=task_type,
        status="SUCCESS" if success else "FAILED",
        progress=total,
        total=total,
        error_message=error_message,
    )


async def cleanup_expired_notifications(db: AsyncSession):
    """清理过期的通知"""
    result = await db.execute(
        select(Notification).where(
            Notification.valid_until < datetime.utcnow()
        )
    )
    expired = result.scalars().all()
    for notif in expired:
        await db.delete(notif)
    await db.commit()
    return len(expired)
