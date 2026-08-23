import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_VERSION: str = "0.6.1"

    DATABASE_URL: str = "postgresql+asyncpg://iptv_user:iptv_pass@localhost:5432/iptv_manager"
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    ANALYSIS_FREQUENCY_MINUTES: int = 45
    ANALYSIS_WORKERS: int = 6
    ANALYSIS_TIMEOUT_SECONDS: int = 3
    FULL_ANALYSIS_TIMEOUT_SECONDS: int = 30
    BITRATE_RECORD_DURATION_SECONDS: int = 10
    FORGIVENESS_PARAM: int = 10
    
    SOURCE_REFRESH_FREQUENCY_HOURS: int = 2
    
    CHANNEL_ALIAS_URL: str = "https://raw.githubusercontent.com/yaoxieyoulei/YYKM_assets/main/channel_alias.json"
    
    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
