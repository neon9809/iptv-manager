"""通知分发器 - 统一管理三条通知渠道的分发逻辑

渠道说明:
  - homepage-banner: 首页通知栏，显示在页面顶部
  - maintenance-timeline: 最近维护面板，显示在首页时间线
  - smtp: 邮件通知，发送到配置的邮箱

分发流程:
  1. 接收通知请求 (subject, context, severity, channels 等)
  2. 检查各渠道是否启用 (NotificationChannelConfig)
  3. 对启用的渠道执行分发:
     - homepage-banner/maintenance-timeline: 写入 Notification 表
     - smtp: 调用 SMTPService 发送邮件
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Notification, NotificationChannelConfig, SMTPConfig
from app.services.smtp_service import SMTPService, SMTPConfig as SMTPConfigData

logger = logging.getLogger(__name__)

CHANNEL_HOMEPAGE = "homepage-banner"
CHANNEL_MAINTENANCE = "maintenance-timeline"
CHANNEL_SMTP = "smtp"


class NotificationDispatcher:
    """统一通知分发器"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._channel_configs: dict[str, NotificationChannelConfig] = {}
        self._smtp_config: Optional[SMTPConfig] = None

    async def _load_configs(self):
        """加载渠道配置"""
        if self._channel_configs:
            return

        result = await self.db.execute(select(NotificationChannelConfig))
        configs = result.scalars().all()
        self._channel_configs = {c.channel_key: c for c in configs}

        smtp_result = await self.db.execute(select(SMTPConfig).limit(1))
        self._smtp_config = smtp_result.scalar_one_or_none()

    def _is_channel_enabled(self, channel: str) -> bool:
        """检查渠道是否启用"""
        config = self._channel_configs.get(channel)
        if not config:
            return channel in [CHANNEL_HOMEPAGE, CHANNEL_MAINTENANCE]
        return config.enabled

    async def dispatch(
        self,
        issuer: str,
        subject: str,
        context: str,
        severity: str = "info",
        channels: Optional[list[str]] = None,
        valid_hours: int = 24,
        task_identifier: Optional[str] = None,
        update_existing: bool = False,
    ) -> Optional[Notification]:
        """分发通知到指定渠道

        Args:
            issuer: 发布者标识
            subject: 通知标题
            context: 通知内容
            severity: 严重程度 (info/warning/error/success)
            channels: 目标渠道列表，默认为 ["homepage-banner"]
            valid_hours: 有效期（小时）
            task_identifier: 任务标识符，用于更新已有通知 (maintenance-timeline)
            update_existing: 是否更新已有通知 (用于进度更新)

        Returns:
            创建或更新的 Notification 对象 (仅数据库渠道)
        """
        await self._load_configs()

        if channels is None:
            channels = [CHANNEL_HOMEPAGE]

        db_notification = None
        db_channels = [c for c in channels if c in [CHANNEL_HOMEPAGE, CHANNEL_MAINTENANCE]]
        smtp_channels = [c for c in channels if c == CHANNEL_SMTP]

        if db_channels:
            db_notification = await self._dispatch_to_db(
                issuer=issuer,
                subject=subject,
                context=context,
                severity=severity,
                channels=db_channels,
                valid_hours=valid_hours,
                task_identifier=task_identifier,
                update_existing=update_existing,
            )

        if smtp_channels and self._is_channel_enabled(CHANNEL_SMTP):
            await self._dispatch_to_smtp(
                subject=subject,
                context=context,
                severity=severity,
                issuer=issuer,
            )

        return db_notification

    async def _dispatch_to_db(
        self,
        issuer: str,
        subject: str,
        context: str,
        severity: str,
        channels: list[str],
        valid_hours: int,
        task_identifier: Optional[str],
        update_existing: bool,
    ) -> Notification:
        """分发到数据库 (homepage-banner / maintenance-timeline)"""
        now = datetime.utcnow()

        if update_existing and task_identifier:
            existing = await self._find_existing_notification(task_identifier, channels)
            if existing:
                existing.subject = subject
                existing.context = context
                existing.severity = severity
                await self.db.commit()
                await self.db.refresh(existing)
                return existing

        notification = Notification(
            issuer=issuer,
            subject=subject,
            context=context,
            severity=severity,
            notification_channels=channels,
            valid_from=now,
            valid_until=now + timedelta(hours=valid_hours),
        )
        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def _find_existing_notification(
        self,
        task_identifier: str,
        channels: list[str],
    ) -> Optional[Notification]:
        """查找已有的通知 (用于进度更新)"""
        prefix = f"[{task_identifier}]"
        result = await self.db.execute(
            select(Notification).where(
                Notification.issuer == "system",
                Notification.notification_channels.contained_by(channels),
                Notification.subject.startswith(prefix),
            )
        )
        return result.scalars().first()

    async def _dispatch_to_smtp(
        self,
        subject: str,
        context: str,
        severity: str,
        issuer: str,
    ):
        """分发到 SMTP 邮件"""
        if not self._smtp_config or not self._smtp_config.enabled:
            logger.debug("[NotificationDispatcher] SMTP 渠道未启用，跳过邮件发送")
            return

        if not self._smtp_config.sender:
            logger.warning("[NotificationDispatcher] SMTP 发件人未配置，跳过邮件发送")
            return

        try:
            smtp_service = SMTPService(SMTPConfigData(
                host=self._smtp_config.host or "",
                port=self._smtp_config.port,
                username=self._smtp_config.username or "",
                password=self._smtp_config.password or "",
                sender=self._smtp_config.sender,
                use_tls=self._smtp_config.use_tls,
            ))

            success, message = smtp_service.send_email(
                recipient=self._smtp_config.sender,
                subject=subject,
                content=context,
                severity=severity,
                issuer=issuer,
            )

            if success:
                logger.info(f"[NotificationDispatcher] 邮件发送成功: {subject}")
            else:
                logger.warning(f"[NotificationDispatcher] 邮件发送失败: {message}")

        except Exception as e:
            logger.error(f"[NotificationDispatcher] SMTP 发送异常: {e}", exc_info=True)


_dispatcher_instance: Optional[NotificationDispatcher] = None


async def get_dispatcher(db: AsyncSession) -> NotificationDispatcher:
    """获取通知分发器实例"""
    global _dispatcher_instance
    if _dispatcher_instance is None or _dispatcher_instance.db != db:
        _dispatcher_instance = NotificationDispatcher(db)
    return _dispatcher_instance


async def dispatch_notification(
    db: AsyncSession,
    issuer: str,
    subject: str,
    context: str,
    severity: str = "info",
    channels: Optional[list[str]] = None,
    valid_hours: int = 24,
    task_identifier: Optional[str] = None,
    update_existing: bool = False,
) -> Optional[Notification]:
    """便捷函数: 分发通知"""
    dispatcher = await get_dispatcher(db)
    return await dispatcher.dispatch(
        issuer=issuer,
        subject=subject,
        context=context,
        severity=severity,
        channels=channels,
        valid_hours=valid_hours,
        task_identifier=task_identifier,
        update_existing=update_existing,
    )
