# Update Log

## 2026-02-24 - 视频基本信息分析异步化改造

### 问题描述

添加订阅源时，视频基本信息分析是同步执行的，会阻塞 API 请求。当直播流数量较多时（如 64 个），用户需要等待很长时间，前端弹窗一直不关闭，用户体验较差。

### 修复内容

#### 1. 新增 Celery 任务 `VIDEO_BASIC_ANALYSIS`

**文件**: `app/tasks/scheduled.py`

新增 `video_basic_analysis_task()` Celery 任务，将视频基本信息分析（分辨率、帧率、编码、比特率等）改为异步执行：

```python
@shared_task(name="app.tasks.scheduled.video_basic_analysis_task")
@run_async
async def video_basic_analysis_task(task_id: str):
    """执行订阅源视频基本信息分析 - 由 dispatcher 分发调用"""
    # 分析直播流的视频属性
    for stream_id, stream_url in stream_urls:
        video_props = await analyze_stream_video_properties(stream_url, timeout=5)
        # 更新 stream 对象的视频属性...
```

#### 2. 更新任务优先级列表

| 优先级 | 任务类型 | 说明 |
|--------|----------|------|
| 9 | SINGLE_STREAM_ANALYSIS | 单个流手动增强分析 (最高) |
| 7 | SOURCE_REFRESH | 首次添加/手动刷新订阅源 |
| **6** | **VIDEO_BASIC_ANALYSIS** | **视频基本信息分析 (新增)** |
| 5 | BATCH_ANALYSIS | 手动触发的批量增强分析 |
| 4 | SOURCE_REFRESH | 订阅源定时刷新 |
| 2 | AUTO_ANALYSIS | 自动定时增强分析 (最低) |

#### 3. 修改 API 立即返回

**文件**: `app/api/routes/main.py`

`create_source` API 验证 M3U 合法后立即返回，创建两个异步任务：
- `SOURCE_REFRESH` (优先级 7): 刷新订阅源
- `VIDEO_BASIC_ANALYSIS` (优先级 6): 视频基本信息分析

```python
# 创建刷新任务
refresh_task = Task(
    task_name=f"Initial Refresh: {new_source.nickname}",
    task_type="SOURCE_REFRESH",
    priority=7,
    payload={"source_id": new_source.id},
)

# 创建视频分析任务
if streams_to_analyze:
    video_task = Task(
        task_name=f"Video Analysis: {new_source.nickname}",
        task_type="VIDEO_BASIC_ANALYSIS",
        priority=6,
        payload={"source_id": new_source.id, "stream_urls": streams_to_analyze},
    )
```

#### 4. 更新任务分发器

**文件**: `app/tasks/dispatcher.py`

支持分发新的 `VIDEO_BASIC_ANALYSIS` 任务类型到 `refresh` 队列。

### 效果对比

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 添加订阅源响应时间 | 需等待所有视频分析完成（可能数十秒） | 验证 M3U 后立即返回（约 1-2 秒） |
| 前端弹窗 | 一直显示直到分析完成 | 验证成功后立即关闭 |
| 视频分析 | 同步阻塞执行 | 异步队列执行，可在"最近维护"面板查看进度 |

### 涉及文件

- `app/tasks/scheduled.py` - 新增 `video_basic_analysis_task` 任务
- `app/tasks/dispatcher.py` - 支持新任务类型分发
- `app/core/celery_app.py` - 添加任务路由
- `app/services/source_manager.py` - 移除同步视频分析逻辑
- `app/api/routes/main.py` - 创建异步任务并立即返回
- `app/services/notification_service.py` - 支持新任务类型通知

---

## 2026-02-24 - 订阅源重复添加错误处理优化

### 问题描述

当用户尝试添加一个已存在的订阅源 URL 时，系统返回 500 Internal Server Error，错误信息为数据库唯一约束冲突 (`UniqueViolationError`)，而非友好的错误提示。

### 修复内容

#### 1. source_manager.py - 添加 URL 重复检查

在 `add_subscription_source` 函数中添加了预先检查逻辑：

```python
existing = await db.execute(
    select(SubscriptionSource).where(SubscriptionSource.url == url)
)
if existing.scalar_one_or_none():
    raise ValueError("该订阅源 URL 已存在")
```

#### 2. main.py - API 层异常处理

在 `create_source` 端点中捕获 `ValueError` 并返回 400 错误：

```python
try:
    new_source, result = await source_manager.add_subscription_source(...)
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))
```

#### 3. main.py - 配置恢复功能异常处理

在配置恢复功能 (`import_config`) 中添加了相同的异常处理，将重复的订阅源添加到跳过列表中。

### 效果对比

| 场景 | 修复前 | 修复后 |
|------|--------|--------|
| 添加重复订阅源 URL | 500 Internal Server Error | 400 Bad Request，提示"该订阅源 URL 已存在" |
| 配置恢复时遇到重复 URL | 可能导致整个恢复失败 | 自动跳过并记录原因 |

### 涉及文件

- `app/services/source_manager.py`
- `app/api/routes/main.py`
