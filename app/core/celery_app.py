"""Celery 应用配置"""
import os
import logging
from celery import Celery
from celery.signals import worker_init
from kombu import Queue, Exchange

celery_app = Celery('iptv_manager')

celery_app.conf.broker_url = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
celery_app.conf.result_backend = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')

celery_app.conf.include = [
    'app.tasks.analysis',
    'app.tasks.scheduled',
    'app.tasks.dispatcher',
]

celery_app.conf.task_routes = {
    'app.tasks.analysis.analyze_stream_task': {'queue': 'analysis-high'},
    'app.tasks.analysis.batch_analyze_streams_task': {'queue': 'analysis'},
    'app.tasks.scheduled.source_refresh_task': {'queue': 'refresh'},
    'app.tasks.scheduled.video_basic_analysis_task': {'queue': 'refresh'},
    'app.tasks.dispatcher.dispatch_tasks': {'queue': 'dispatcher'},
    'app.tasks.scheduled.source_refresh_scheduler': {'queue': 'dispatcher'},
    'app.tasks.scheduled.auto_analysis_scheduler': {'queue': 'dispatcher'},
}

celery_app.conf.task_queues = (
    Queue('analysis-high', Exchange('analysis-high'), routing_key='analysis-high'),
    Queue('analysis', Exchange('analysis'), routing_key='analysis'),
    Queue('refresh', Exchange('refresh'), routing_key='refresh'),
    Queue('dispatcher', Exchange('dispatcher'), routing_key='dispatcher'),
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    task_queue_max_priority=10,
)

celery_app.conf.beat_schedule = {
    'task-dispatcher': {
        'task': 'app.tasks.dispatcher.dispatch_tasks',
        'schedule': 10.0,
        'options': {'queue': 'dispatcher'},
    },
    'source-refresh-scheduler': {
        'task': 'app.tasks.scheduled.source_refresh_scheduler',
        'schedule': 600.0,
        'options': {'queue': 'dispatcher'},
    },
    'auto-analysis-scheduler': {
        'task': 'app.tasks.scheduled.auto_analysis_scheduler',
        'schedule': 600.0,
        'options': {'queue': 'dispatcher'},
    },
    'log-cleanup-scheduler': {
        'task': 'app.tasks.scheduled.log_cleanup_scheduler',
        'schedule': 3600.0,
        'options': {'queue': 'dispatcher'},
    },
}

celery_app.autodiscover_tasks()


@worker_init.connect
def init_worker_logging(**kwargs):
    """在 Celery Worker 启动时初始化日志系统"""
    log_enabled = os.getenv('CELERY_LOG_ENABLED', 'true').lower() == 'true'
    if log_enabled:
        try:
            from app.core.database import async_session_maker
            from app.services.log_service import LogService
            LogService.initialize_logging_sync(async_session_maker, enabled=True)
            logging.getLogger(__name__).info("Celery Worker 日志系统已初始化")
        except Exception as e:
            logging.getLogger(__name__).warning(f"Celery Worker 日志系统初始化失败: {e}")
