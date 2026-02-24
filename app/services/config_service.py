from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import SystemConfig
from app.core.config import get_settings

settings = get_settings()


class ConfigService:
    _cached_config = None
    _cache_valid = False

    @classmethod
    async def get_config(cls, db: AsyncSession) -> SystemConfig:
        """获取系统配置，优先从数据库读取"""
        if cls._cached_config and cls._cache_valid:
            return cls._cached_config

        result = await db.execute(select(SystemConfig))
        config = result.scalar_one_or_none()

        if not config:
            config = SystemConfig()
            db.add(config)
            await db.commit()
            await db.refresh(config)

        cls._cached_config = config
        cls._cache_valid = True
        return config

    @classmethod
    def invalidate_cache(cls):
        """使配置缓存失效"""
        cls._cache_valid = False

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
