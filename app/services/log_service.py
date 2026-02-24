import logging
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from datetime import datetime, timedelta
from app.models.models import LogEntry
from app.services.config_service import ConfigService

logger = logging.getLogger(__name__)


class DatabaseLogHandler(logging.Handler):
    """自定义日志处理器，将日志写入数据库"""
    
    def __init__(self, db_session_factory):
        super().__init__()
        self.db_session_factory = db_session_factory
        self._queue = []
        self._flushing = False

    def emit(self, record):
        """将日志记录写入数据库"""
        try:
            msg = self.format(record)
            log_data = {
                'level': record.levelname,
                'logger': record.name,
                'message': msg,
                'context': {
                    'module': record.module,
                    'funcName': record.funcName,
                    'lineno': record.lineno,
                }
            }
            self._queue.append(log_data)
            self._schedule_flush()
        except Exception:
            pass

    def _schedule_flush(self):
        """调度刷新操作"""
        if self._flushing:
            return
        
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon(self._do_flush)
        except RuntimeError:
            self._do_flush_sync()

    def _do_flush(self):
        """异步刷新日志到数据库"""
        if not self._queue:
            self._flushing = False
            return
        
        self._flushing = True
        logs_to_write = self._queue.copy()
        self._queue.clear()
        
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self._write_logs_async(logs_to_write), loop=loop)
        except Exception:
            pass
        finally:
            self._flushing = False

    def _do_flush_sync(self):
        """同步刷新日志到数据库"""
        if not self._queue:
            return
        
        logs_to_write = self._queue.copy()
        self._queue.clear()
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._write_logs_async(logs_to_write))
            finally:
                loop.close()
        except Exception:
            pass

    async def _write_logs_async(self, logs_data):
        """异步写入日志到数据库"""
        try:
            async with self.db_session_factory() as db:
                for log_data in logs_data:
                    log_entry = LogEntry(
                        level=log_data['level'],
                        logger=log_data['logger'],
                        message=log_data['message'],
                        context=log_data['context']
                    )
                    db.add(log_entry)
                await db.commit()
        except Exception as e:
            pass


class LogService:
    """日志服务"""

    _db_handler: DatabaseLogHandler | None = None
    _is_logging_initialized = False

    @classmethod
    async def initialize_logging(cls, db_session_factory):
        """初始化日志系统"""
        if cls._is_logging_initialized:
            return

        cls._enable_database_logging(db_session_factory)
        cls._is_logging_initialized = True
        logger.info("日志系统已初始化")

    @classmethod
    def initialize_logging_sync(cls, db_session_factory, enabled: bool = True):
        """同步初始化日志系统（用于 Celery Worker）"""
        if cls._is_logging_initialized:
            return
        
        if enabled:
            cls._enable_database_logging(db_session_factory)
        
        cls._is_logging_initialized = True

    @classmethod
    def _enable_database_logging(cls, db_session_factory):
        """启用数据库日志"""
        if cls._db_handler is None:
            cls._db_handler = DatabaseLogHandler(db_session_factory)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            cls._db_handler.setFormatter(formatter)
            cls._db_handler.setLevel(logging.INFO)
            
            root_logger = logging.getLogger()
            root_logger.addHandler(cls._db_handler)
            
            root_logger.setLevel(logging.INFO)

    @classmethod
    def _disable_database_logging(cls):
        """禁用数据库日志"""
        if cls._db_handler is not None:
            root_logger = logging.getLogger()
            root_logger.removeHandler(cls._db_handler)
            cls._db_handler = None

    @classmethod
    async def update_logging_status(cls, db: AsyncSession):
        """更新日志状态（根据配置启用/禁用）"""
        config = await ConfigService.get_config(db)
        
        if config.log_enabled:
            from app.core.database import async_session_maker
            cls._enable_database_logging(async_session_maker)
        else:
            cls._disable_database_logging()

    @classmethod
    async def get_logs(cls, db: AsyncSession, limit: int = 100, offset: int = 0, level: str = None) -> list[LogEntry]:
        """获取日志列表"""
        query = select(LogEntry).order_by(LogEntry.created_at.desc())
        
        if level:
            query = query.where(LogEntry.level == level.upper())
        
        query = query.offset(offset).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    @classmethod
    async def get_log_count(cls, db: AsyncSession, level: str = None) -> int:
        """获取日志总数"""
        from sqlalchemy import func
        
        query = select(func.count(LogEntry.id))
        if level:
            query = query.where(LogEntry.level == level.upper())
        
        result = await db.execute(query)
        return result.scalar() or 0

    @classmethod
    async def export_logs(cls, db: AsyncSession) -> str:
        """导出日志为文本格式"""
        logs = await cls.get_logs(db, limit=10000)
        
        lines = []
        for log in logs:
            line = f"[{log.created_at.isoformat()}] [{log.level}] [{log.logger}] {log.message}"
            lines.append(line)
        
        return "\n".join(lines)

    @classmethod
    async def cleanup_old_logs(cls, db: AsyncSession, retention_hours: int = 1):
        """清理过期的日志"""
        cutoff_time = datetime.utcnow() - timedelta(hours=retention_hours)
        
        result = await db.execute(
            delete(LogEntry).where(LogEntry.created_at < cutoff_time)
        )
        await db.commit()
        return result.rowcount
