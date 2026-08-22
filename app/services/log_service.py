import logging
import asyncio
import queue
import threading
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from datetime import datetime, timedelta
from app.models.models import LogEntry
from app.services.config_service import ConfigService

logger = logging.getLogger(__name__)


class DatabaseLogHandler(logging.Handler):
    """线程安全的数据库日志处理器

    设计：
      - emit() 仅做无阻塞入队（queue.Queue 线程安全，可被多线程/多循环并发调用）
      - 单一后台写线程从队列取日志，通过独立事件循环写入数据库
      - 队列有界（防内存膨胀），满时丢弃并计数（日志系统故障不应影响业务）
      - 所有异常记录到标准 logger，不再静默吞掉
    """

    _MAX_QUEUE_SIZE = 10000
    _BATCH_SIZE = 100
    _FLUSH_INTERVAL = 2.0  # 秒：无新日志时的兜底刷新周期

    def __init__(self, db_session_factory):
        super().__init__()
        self.db_session_factory = db_session_factory
        self._queue: queue.Queue = queue.Queue(maxsize=self._MAX_QUEUE_SIZE)
        self._dropped = 0
        self._writer_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._start_writer_thread()

    def emit(self, record):
        """将日志记录写入队列（线程安全，永不阻塞、永不抛出）"""
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
            try:
                self._queue.put_nowait(log_data)
            except queue.Full:
                self._dropped += 1
                # 每 100 条丢弃才告警一次，避免告警风暴
                if self._dropped % 100 == 1:
                    logging.getLogger(__name__).warning(
                        f"DatabaseLogHandler queue full, dropped {self._dropped} log records total"
                    )
        except Exception:
            self.handleError(record)

    def _start_writer_thread(self):
        if self._writer_thread is not None and self._writer_thread.is_alive():
            return
        self._stop_event.clear()
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="db-log-writer",
            daemon=True,
        )
        self._writer_thread.start()

    def _writer_loop(self):
        """后台写线程：独立事件循环，批量写库"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            while not self._stop_event.is_set():
                batch: list[dict] = []
                try:
                    # 阻塞等待第一条（带超时作为兜底刷新周期）
                    batch.append(self._queue.get(timeout=self._FLUSH_INTERVAL))
                    # 非阻塞取尽当前积压，凑一批
                    while len(batch) < self._BATCH_SIZE:
                        try:
                            batch.append(self._queue.get_nowait())
                        except queue.Empty:
                            break
                except queue.Empty:
                    continue

                try:
                    loop.run_until_complete(self._write_logs_async(batch))
                except Exception as e:
                    logging.getLogger(__name__).error(
                        f"DatabaseLogHandler failed to write {len(batch)} log records: {e}"
                    )
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    async def _write_logs_async(self, logs_data: list[dict]):
        """异步批量写入日志到数据库"""
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
            logging.getLogger(__name__).error(f"DatabaseLogHandler write error: {e}")


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
    async def export_logs(cls, db: AsyncSession, limit: int = 100000) -> str:
        """导出日志为文本格式（默认上限 10 万条，超出部分截断并在末尾提示）"""
        logs = await cls.get_logs(db, limit=limit)
        
        lines = []
        for log in logs:
            line = f"[{log.created_at.isoformat()}] [{log.level}] [{log.logger}] {log.message}"
            lines.append(line)

        if len(logs) >= limit:
            lines.append(f"... [导出已达上限 {limit} 条，更早日志可能被截断或已按保留策略清理]")

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
