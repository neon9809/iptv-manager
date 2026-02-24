# IPTV Manager 任务队列系统深度分析与重构方案

经过对 `iptv-manager` v0.2.1 项目代码的深入分析和实际部署测试，我发现当前基于 Celery 的异步任务队列在设计和实现上存在一些核心问题，这些问题导致了功能无法按预期工作、系统不稳定以及难以扩展。本文档将详细阐述这些问题，并提出一套完整的重构方案。

## 一、 现有设计核心问题分析

在测试过程中，我发现了以下几个关键问题，严重影响了“视频信息分析”和“增强分析”功能的正确性和鲁棒性。

### 问题 1：异步事件循环冲突 (P0 - 阻塞性 Bug)

- **现象**: 批量增强分析任务 (`batch_analyze_streams`) 必定失败，日志中出现 `RuntimeError: Task got Future attached to a different loop`。
- **根因**: 在 Celery 的 `shared_task` 中，代码通过 `asyncio.new_event_loop()` 创建了一个新的事件循环。然而，全局的 `async_session_maker` (SQLAlchemy 的异步会话工厂) 在创建时已经绑定到了 Celery worker 启动时的主事件循环。当任务试图在新的事件循环中使用这个会话工厂创建的数据库连接时，就引发了跨循环操作的严重错误。
- **影响**: 所有批量分析任务均无法执行，是导致核心功能失效的最高优先级 Bug。

### 问题 2：任务优先级机制无效 (P1 - 设计缺陷)

- **现象**: 设计上要求“手动触发单个视频流的增强分析优先级最高（9）”，但实际测试中，高优先级任务并不能插队到正在执行的低优先级任务之前。
- **根因**: 项目使用了 Redis 作为 Celery 的 Broker。**Redis Broker 本身不支持消息优先级**。虽然在 `celery_app.py` 中设置了 `task_queue_max_priority=10` 并为任务分配了 `priority` 属性，但这些配置对 Redis 是无效的，仅对 RabbitMQ 或 Amazon SQS 等高级消息队列生效。
- **影响**: 无法实现紧急任务优先处理的需求，用户体验不佳。

### 问题 3：任务恢复机制不完整且存在错误 (P2 - 逻辑漏洞)

- **现象**: 应用重启后的任务恢复逻辑 (`task_recovery_service.py` 和 `main.py` 中的 `restore_queued_tasks`) 不可靠且存在代码错误。
- **根因**:
    1.  `task_recovery_service.py` 中引用了不存在的 `Source` 模型和 `Stream` 模型中不存在的 `analysis_status` 字段，导致该服务完全无法正常工作。
    2.  `main.py` 中的恢复逻辑依赖于 Redis 中的 set (`video_analysis:queue`, `full_analysis:queue`)，但这些 set 是在任务运行时才添加的，并且任务完成后即被删除，无法覆盖所有重启场景。
    3.  缺乏一个持久化的、统一的任务状态管理机制。任务的状态分散在 Redis 的各种 key 中，一旦 Redis 数据丢失或服务重启，所有任务状态都会丢失。
- **影响**: 无法保证任务在应用重启或崩溃后能继续执行，不满足“容器重启后自动继续之前的任务”的需求。

### 问题 4：定时任务调度缺失 (P3 - 配置缺失)

- **现象**: `scheduled.py` 中定义了 `refresh_sources_task` (定时刷新订阅源) 和 `auto_analysis_task` (自动分析) 等定时任务，但它们从未被执行。
- **根因**: `celery_app.py` 中完全没有配置 `beat_schedule`。Celery Beat 是用于调度周期性任务的组件，没有它的配置，所有 `@shared_task` 都只会作为普通任务存在，不会被定时触发。
- **影响**: 订阅源自动更新、自动分析等核心自动化功能完全缺失。

### 问题 5：并发控制与任务分发逻辑混乱 (P4 - 设计缺陷)

- **现象**: 不同类型的分析任务之间缺乏有效的并发控制，可能导致对同一资源的重复分析和竞争。
- **根因**:
    1.  `batch_analyze_streams` (增强分析) 使用一个全局 Redis 锁 `full_analysis:task`，意味着同一时间只能有一个增强分析任务运行。
    2.  `analyze_source_streams_basic_info` (基本信息分析) 使用基于 `source_id` 的锁 `video_analysis:task:{source_id}`，允许多个不同订阅源的基本信息分析并行。
    3.  这两种任务之间没有任何协调机制，可能导致一个订阅源的基本信息分析和增强分析同时进行，争抢 `ffprobe` 进程和网络带宽资源。
- **影响**: 系统资源管理混乱，可能导致分析结果不准确或系统过载。

## 二、 任务队列重构方案

为了彻底解决上述问题，我将对任务队列系统进行全面的重构。核心思想是：**引入持久化的任务管理模型，构建一个自定义的、支持优先级的任务调度器，并统一事件循环的管理。**

### 步骤 1: 引入持久化任务模型

我将在 `models.py` 中添加一个新的 SQLAlchemy 模型 `Task`，用于持久化存储所有异步任务的状态。

```python
# app/models/models.py

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_name: Mapped[str] = mapped_column(String(255), index=True)
    task_type: Mapped[str] = mapped_column(String(50), index=True) # e.g., 'BASIC_INFO', 'ENHANCED_ANALYSIS'
    priority: Mapped[int] = mapped_column(Integer, default=5, index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True) # PENDING, QUEUED, RUNNING, SUCCESS, FAILED
    payload: Mapped[dict] = mapped_column(JSONB, default=dict) # e.g., {"stream_ids": [...], "mode": "full"}
    result: Mapped[dict | None] = mapped_column(JSONB)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
```

同时，在 `Stream` 模型中添加字段，用于防止并发分析：

```python
# app/models/models.py in Stream class

    current_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"))
```

### 步骤 2: 统一异步任务执行器

为了解决事件循环冲突问题，我将创建一个工具函数，用于在 Celery 任务中安全地执行异步代码。

```python
# app/utils/async_task_runner.py

import asyncio
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

def run_async(func):
    """Decorator to run async function in Celery task."""
    def wrapper(*args, **kwargs):
        try:
            return asyncio.run(func(*args, **kwargs))
        except Exception as e:
            logger.error(f"Error running async task {func.__name__}: {e}", exc_info=True)
            raise
    return wrapper
```

之后，所有的 Celery 任务都将使用这个装饰器来执行其异步逻辑，确保事件循环的正确管理。

### 步骤 3: 重构核心分析任务

`analysis.py` 中的任务将被重写，以使用新的 `Task` 模型和 `run_async` 装饰器。

- **任务触发**: API 端点不再直接调用 `apply_async`，而是创建一个 `Task` 记录并保存到数据库。
- **任务执行**: Celery 任务会接收 `task_id`，从数据库加载任务信息，执行分析，并实时更新 `Task` 记录的状态、进度和结果。
- **并发控制**: 在开始分析一个流之前，任务会检查 `Stream.current_task_id` 字段。如果该流已在被另一个任务分析，则跳过。

### 步骤 4: 实现自定义优先级调度器与 Celery Beat

这是本次重构的核心。

1.  **配置 Celery Beat Schedule**: 在 `celery_app.py` 中添加 `beat_schedule`，配置一个高频运行的“调度器任务”。

    ```python
    # app/core/celery_app.py
    celery_app.conf.beat_schedule = {
        'task-dispatcher': {
            'task': 'app.tasks.dispatcher.dispatch_tasks',
            'schedule': 10.0,  # 每 10 秒运行一次
            'options': {'queue': 'dispatcher'}
        },
        # 其他定时任务...
    }
    ```

2.  **创建调度器任务**: `app/tasks/dispatcher.py`

    这个新的调度器任务 (`dispatch_tasks`) 的职责是：
    a.  查询数据库中所有处于 `PENDING` 状态的 `Task` 记录。
    b.  根据 `priority` 字段对这些任务进行排序。
    c.  检查当前正在运行的任务数量，以控制并发。
    d.  选择最高优先级的任务，将其状态更新为 `QUEUED`，然后通过 `apply_async` 发送到相应的 Celery worker 队列（`analysis-high` 或 `analysis`）。

### 步骤 5: 完善任务恢复机制

- 新的恢复机制将非常简单和健壮。在应用启动时 (`main.py` 的 `lifespan` 中)，运行一个恢复服务。
- 这个服务会查询数据库中所有处于 `RUNNING` 或 `QUEUED` 状态的 `Task`。
- 它会将这些任务的状态重置为 `PENDING`，这样自定义的调度器 (`dispatch_tasks`) 就会在下一次运行时自动重新拾取并调度它们。

## 三、 方案优势

- **可靠性**: 通过将任务状态持久化到数据库，彻底解决了因服务重启或 Redis 数据丢失导致的任务丢失问题。
- **真正的优先级**: 自定义调度器实现了与 Broker 无关的、真正的业务逻辑优先级，确保高优任务得到优先处理。
- **稳定性**: 统一的异步执行器解决了事件循环冲突，消除了 `RuntimeError`。
- **可扩展性与可观测性**: `Task` 模型提供了一个统一的视角来监控和管理所有异步任务。未来可以基于此轻松构建任务管理仪表盘，进行重试、取消等操作。
- **并发安全**: 通过在数据模型层面引入任务锁定，避免了资源竞争和重复工作。
- **自动化**: 通过正确配置 Celery Beat，使系统的自动化运维能力得以实现。

接下来，我将开始着手实施这一重构方案。
