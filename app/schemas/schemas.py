from pydantic import BaseModel, Field, field_serializer, model_serializer, ConfigDict
from datetime import datetime
from typing import Optional
from uuid import UUID


class ChannelBase(BaseModel):
    standard_name: str
    aliases: list[str] = []
    logo_path: Optional[str] = None
    category: Optional[str] = None
    tvg_id: Optional[str] = None
    group_name: Optional[str] = None
    order_index: int = 0


class ChannelCreate(ChannelBase):
    pass


class ChannelUpdate(ChannelBase):
    pass


class ChannelResponse(ChannelBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    created_at: datetime
    updated_at: datetime


class StreamBase(BaseModel):
    url: str
    name: Optional[str] = None
    channel_id: Optional[int] = None


class StreamResponse(StreamBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    url_hash: str
    source_ids: list
    latency_ms: Optional[int] = None
    bitrate_kbps: Optional[int] = None
    stability_score: Optional[float] = None
    video_width: Optional[int] = None
    video_height: Optional[int] = None
    video_fps: Optional[float] = None
    video_codec: Optional[str] = None
    video_bit_depth: Optional[int] = None
    video_color_profile: Optional[str] = None
    audio_codec: Optional[str] = None
    video_analyzed_at: Optional[datetime] = None
    video_bitrate_kbps: Optional[int] = None
    unreachable_count: int
    active: str
    last_analysis_time: Optional[datetime] = None
    first_discovered_at: datetime
    created_at: datetime
    updated_at: datetime
    
    @model_serializer(mode='wrap')
    def serialize_model(self, handler, info):
        data = handler(self, info)
        if 'id' in data and isinstance(data['id'], UUID):
            data['id'] = str(data['id'])
        return data


class SubscriptionSourceBase(BaseModel):
    nickname: str
    url: str
    refresh_frequency_hours: int = 2


class SubscriptionSourceCreate(SubscriptionSourceBase):
    pass


class SubscriptionSourceUpdate(BaseModel):
    nickname: Optional[str] = None
    url: Optional[str] = None
    refresh_frequency_hours: Optional[int] = None


class SubscriptionSourceResponse(SubscriptionSourceBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    last_refresh_time: Optional[datetime] = None
    last_refresh_status: Optional[str] = None
    stream_count: int
    created_at: datetime
    updated_at: datetime


class AnalysisHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    stream_id: str
    analysis_time: datetime
    latency_ms: Optional[int] = None
    bitrate_kbps: Optional[int] = None
    stability_score: Optional[float] = None
    packet_loss: Optional[float] = None
    interrupt_count: Optional[int] = None
    response_code: Optional[int] = None
    created_at: datetime
    
    @model_serializer(mode='wrap')
    def serialize_model(self, handler, info):
        data = handler(self, info)
        if 'stream_id' in data and isinstance(data['stream_id'], UUID):
            data['stream_id'] = str(data['stream_id'])
        return data


class NotificationBase(BaseModel):
    issuer: str
    subject: str
    context: str
    severity: str = "info"
    notification_channels: list[str] = ["homepage-banner"]


class NotificationCreate(NotificationBase):
    valid_until: Optional[datetime] = None


class NotificationResponse(NotificationBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    valid_from: datetime
    valid_until: Optional[datetime] = None
    read_button: str
    created_at: datetime


class StreamUpdateActive(BaseModel):
    active: str = Field(..., pattern="^(true|false|auto)$")


class ChannelOrderUpdate(BaseModel):
    order_index: int


class AnalysisTriggerRequest(BaseModel):
    stream_ids: Optional[list[str]] = None
    mode: str = Field(default="full", pattern="^(quick|full)$")


class RefreshSourceRequest(BaseModel):
    source_id: int


class HealthResponse(BaseModel):
    status: str
    checks: dict
    version: str = "0.2.0"


class SMTPConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    enabled: bool
    host: Optional[str] = None
    port: int = 587
    sender: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    use_tls: bool = True
    tested: bool = False
    created_at: datetime
    updated_at: datetime


class SMTPConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    host: Optional[str] = None
    port: Optional[int] = None
    sender: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    use_tls: Optional[bool] = None
    tested: Optional[bool] = None


class SystemConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_frequency_minutes: int = 45
    analysis_workers: int = 6
    analysis_timeout_seconds: int = 3
    forgiveness_param: int = 10
    source_refresh_frequency_hours: int = 2
    log_enabled: bool = False
    log_retention_hours: int = 1
    created_at: datetime
    updated_at: datetime


class SystemConfigUpdate(BaseModel):
    analysis_frequency_minutes: Optional[int] = None
    analysis_workers: Optional[int] = None
    analysis_timeout_seconds: Optional[int] = None
    forgiveness_param: Optional[int] = None
    source_refresh_frequency_hours: Optional[int] = None
    log_enabled: Optional[bool] = None
    log_retention_hours: Optional[int] = None


class LogEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str
    logger: str
    message: str
    context: dict
    created_at: datetime


class NotificationItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    name: str
    enabled: bool
    has_threshold: bool
    threshold_value: Optional[int] = None
    has_status_config: bool
    statuses: list
    channels: list
    created_at: datetime
    updated_at: datetime


class NotificationItemUpdate(BaseModel):
    enabled: Optional[bool] = None
    threshold_value: Optional[int] = None
    statuses: Optional[list] = None
    channels: Optional[list] = None


class NotificationChannelConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_key: str
    enabled: bool
    config: dict
    created_at: datetime
    updated_at: datetime


class NotificationChannelConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    config: Optional[dict] = None
