#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""IPTV Manager - 应用主入口"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging

from app.core.database import init_db, async_session_maker
from app.api.routes import main as main_router
from app.services.channel_matcher import import_channel_aliases
from app.services.task_recovery_service import recover_interrupted_tasks

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化数据库
    await init_db()

    # 导入频道别名
    async with async_session_maker() as db:
        await import_channel_aliases(db)

    # 初始化日志系统
    try:
        from app.services.log_service import LogService
        await LogService.initialize_logging(async_session_maker)
        logger.info("日志系统初始化完成")
    except Exception as e:
        logger.error(f"日志系统初始化失败: {e}")

    # 后台恢复中断的任务（延迟 5 秒，等待 Celery Worker 就绪）
    async def _delayed_recovery():
        await asyncio.sleep(5)
        await recover_interrupted_tasks()

    asyncio.create_task(_delayed_recovery())

    yield


app = FastAPI(
    title="IPTV Manager",
    description="IPTV Stream Management and Optimization System",
    version="0.4.5",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(main_router.router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def root():
    return {"message": "IPTV Manager API", "version": "0.3.0"}
