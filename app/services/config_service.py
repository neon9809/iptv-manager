from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import SystemConfig
from app.core.config import get_settings

settings = get_settings()

# Redis 中保存配置版本号的 key，任何进程修改配置后递增该值，
# 其他进程通过比对本地缓存的版本号来感知失效（解决跨进程缓存失效问题）
CONFIG_VERSION_KEY = "system_config:version"


class ConfigService:
    _cached_config = None
    _cached_version = None

    @classmethod
    async def _get_remote_version(cls) -> int | None:
        """从 Redis 获取当前配置版本号，Redis 不可用时返回 None"""
        try:
            from app.utils.redis_client import redis_client
            version = await redis_client.get(CONFIG_VERSION_KEY)
            return int(version) if version is not None else 0
        except Exception:
            return None

    @classmethod
    async def get_config(cls, db: AsyncSession) -> SystemConfig:
        """获取系统配置：进程内缓存 + Redis 版本号校验（跨进程失效）"""
        remote_version = await cls._get_remote_version()

        if (
            cls._cached_config is not None
            and remote_version is not None
            and cls._cached_version == remote_version
        ):
            return cls._cached_config

        # Redis 不可用时（remote_version 为 None）直接读库，避免使用可能过期的缓存
        result = await db.execute(select(SystemConfig))
        config = result.scalar_one_or_none()

        if not config:
            config = SystemConfig()
            db.add(config)
            await db.commit()
            await db.refresh(config)

        cls._cached_config = config
        cls._cached_version = remote_version if remote_version is not None else -1
        return config

    @classmethod
    async def invalidate_cache(cls, db: AsyncSession | None = None):
        """使所有进程的配置缓存失效：递增 Redis 版本号"""
        cls._cached_config = None
        cls._cached_version = None
        try:
            from app.utils.redis_client import redis_client
            await redis_client.incr(CONFIG_VERSION_KEY)
        except Exception:
            # Redis 不可用时仅失效本进程缓存
            pass

    @classmethod
    async def get_analysis_frequency_minutes(cls, db: AsyncSession) -> int:
        config = await cls.get_config(db)
        return config.analysis_frequency_minutes

    @classmethod
    async def get_analysis_workers(cls, db: AsyncSession) -> int:
        config = await cls.get_config(db)
        return config.analysis_workers

    @classmethod
    async def get_analysis_timeout_seconds(cls, db: AsyncSession) -> int:
        config = await cls.get_config(db)
        return config.analysis_timeout_seconds

    @classmethod
    async def get_forgiveness_param(cls, db: AsyncSession) -> int:
        config = await cls.get_config(db)
        return config.forgiveness_param

    @classmethod
    async def get_source_refresh_frequency_hours(cls, db: AsyncSession) -> int:
        config = await cls.get_config(db)
        return config.source_refresh_frequency_hours

    @classmethod
    def get_full_analysis_timeout_seconds(cls) -> int:
        return settings.FULL_ANALYSIS_TIMEOUT_SECONDS

    @classmethod
    def get_bitrate_record_duration_seconds(cls) -> int:
        return settings.BITRATE_RECORD_DURATION_SECONDS
