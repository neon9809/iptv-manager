import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP, NUMERIC
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    standard_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    logo_path: Mapped[str | None] = mapped_column(String(500))
    category: Mapped[str | None] = mapped_column(String(50))
    tvg_id: Mapped[str | None] = mapped_column(String(100))
    group_name: Mapped[str | None] = mapped_column(String(100))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    streams: Mapped[list["Stream"]] = relationship(back_populates="channel", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_channels_order", "order_index"),
        Index("idx_channels_aliases", "aliases", postgresql_using="gin"),
    )


class Task(Base):
    """持久化任务表 - 所有异步任务的中心"""
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_name: Mapped[str] = mapped_column(String(255), index=True)
    task_type: Mapped[str] = mapped_column(String(50), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5, index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)

    __table_args__ = (
        Index("idx_tasks_status_priority", "status", "priority"),
    )


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    channel_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("channels.id", ondelete="SET NULL"))
    source_ids: Mapped[list] = mapped_column(JSONB, default=list)

    latency_ms: Mapped[int | None] = mapped_column(Integer)
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer)
    stability_score: Mapped[float | None] = mapped_column(NUMERIC(5, 2))

    video_width: Mapped[int | None] = mapped_column(Integer)
    video_height: Mapped[int | None] = mapped_column(Integer)
    video_fps: Mapped[float | None] = mapped_column(NUMERIC(6, 2))
    video_codec: Mapped[str | None] = mapped_column(String(32))
    video_bit_depth: Mapped[int | None] = mapped_column(Integer)
    video_color_profile: Mapped[str | None] = mapped_column(String(32))
    audio_codec: Mapped[str | None] = mapped_column(String(32))
    video_analyzed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    video_bitrate_kbps: Mapped[int | None] = mapped_column(Integer)
    video_analysis_failed: Mapped[bool] = mapped_column(Boolean, default=False)

    unreachable_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[str] = mapped_column(String(10), default="auto")
    last_analysis_time: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    enhanced_analysis_failed: Mapped[bool] = mapped_column(Boolean, default=False)
    first_discovered_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    current_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    channel: Mapped["Channel | None"] = relationship(back_populates="streams")
    analysis_history: Mapped[list["AnalysisHistory"]] = relationship(cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_streams_channel", "channel_id"),
        Index("idx_streams_unreachable", "unreachable_count"),
        Index("idx_streams_active", "active"),
        Index("idx_streams_source_ids", "source_ids", postgresql_using="gin"),
    )


class SubscriptionSource(Base):
    __tablename__ = "subscription_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    nickname: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    refresh_frequency_hours: Mapped[int] = mapped_column(Integer, default=6)
    last_refresh_time: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    last_refresh_status: Mapped[str | None] = mapped_column(String(20))
    stream_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


class AnalysisHistory(Base):
    __tablename__ = "analysis_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("streams.id", ondelete="CASCADE"))
    analysis_time: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer)
    stability_score: Mapped[float | None] = mapped_column(NUMERIC(5, 2))

    # v0.2.1: 细化的稳定性指标
    connection_stability: Mapped[float | None] = mapped_column(NUMERIC(3, 2))
    continuity_score: Mapped[float | None] = mapped_column(NUMERIC(5, 2))
    hls_health_score: Mapped[float | None] = mapped_column(NUMERIC(5, 2))

    response_code: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_analysis_stream_time", "stream_id", "analysis_time"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    issuer: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    read_button: Mapped[str] = mapped_column(String(20), default="available")
    severity: Mapped[str] = mapped_column(String(20), default="info")
    notification_channels: Mapped[list] = mapped_column(JSONB, default=["homepage-banner"])
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_notifications_validity", "valid_from", "valid_until"),
    )


class SMTPConfig(Base):
    __tablename__ = "smtp_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    host: Mapped[str | None] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=587)
    sender: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255))
    password: Mapped[str | None] = mapped_column(String(255))
    use_tls: Mapped[bool] = mapped_column(default=True)
    tested: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


class SystemConfig(Base):
    __tablename__ = "system_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_frequency_minutes: Mapped[int] = mapped_column(Integer, default=45)
    analysis_workers: Mapped[int] = mapped_column(Integer, default=6)
    analysis_timeout_seconds: Mapped[int] = mapped_column(Integer, default=3)
    forgiveness_param: Mapped[int] = mapped_column(Integer, default=10)
    source_refresh_frequency_hours: Mapped[int] = mapped_column(Integer, default=2)
    log_enabled: Mapped[bool] = mapped_column(default=True)
    log_retention_hours: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


class LogEntry(Base):
    __tablename__ = "log_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    logger: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_log_level", "level"),
        Index("idx_log_created_at", "created_at"),
    )


class NotificationItem(Base):
    __tablename__ = "notification_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    has_threshold: Mapped[bool] = mapped_column(default=False)
    threshold_value: Mapped[int | None] = mapped_column(Integer)
    has_status_config: Mapped[bool] = mapped_column(default=False)
    statuses: Mapped[list] = mapped_column(JSONB, default=list)
    channels: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationChannelConfig(Base):
    __tablename__ = "notification_channel_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
