#!/bin/bash
set -e

echo "IPTV Manager starting..."
echo "=================================="
echo "Service: ${SERVICE_NAME:-backend}"
echo "=================================="

# 等待 PostgreSQL
echo "Waiting for PostgreSQL (postgres:5432)..."
until pg_isready -h "postgres" -U "iptv_user" -d "iptv_manager" 2>/dev/null; do
  sleep 2
done
echo "PostgreSQL is ready."

# 等待 Redis
echo "Waiting for Redis (redis:6379)..."
until redis-cli -h "redis" -p "6379" ping 2>/dev/null | grep -q PONG; do
  sleep 2
done
echo "Redis is ready."

echo "=================================="
echo "All dependencies ready. Starting service..."
echo ""

# 数据库迁移（幂等，可安全重复执行）
echo "Running database migrations..."
python3 - <<'EOF'
import asyncio
from app.core.database import engine
from app.models.models import Base

async def migrate():
    async with engine.begin() as conn:
        # 创建所有新表（如 tasks）
        await conn.run_sync(Base.metadata.create_all)
        # 幂等地添加 streams.current_task_id 列（v0.3.0 新增）
        await conn.execute(
            __import__('sqlalchemy').text(
                "ALTER TABLE streams ADD COLUMN IF NOT EXISTS "
                "current_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL"
            )
        )

asyncio.run(migrate())
EOF
echo "Database migrations done."

case "${SERVICE_NAME:-backend}" in
  backend)
    echo "Starting Backend API..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  celery-worker)
    CONCURRENCY=${ANALYSIS_WORKERS:-4}
    echo "Starting Celery Worker (concurrency=$CONCURRENCY)..."
    export CELERY_LOG_ENABLED=true
    exec celery -A app.core.celery_app worker \
      --loglevel=info \
      --queues=analysis-high,analysis,refresh,dispatcher \
      --concurrency="$CONCURRENCY"
    ;;
  celery-beat)
    echo "Starting Celery Beat..."
    exec celery -A app.core.celery_app beat --loglevel=info
    ;;
  *)
    echo "Unknown service: ${SERVICE_NAME}"
    exit 1
    ;;
esac
