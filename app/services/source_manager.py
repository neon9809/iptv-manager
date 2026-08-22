import httpx
import logging
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from app.models.models import SubscriptionSource, Stream
from app.utils.m3u_parser import parse_m3u_from_url
from app.services.notification_service import notify_source_refresh_failed

logger = logging.getLogger(__name__)


async def validate_subscription_source(url: str) -> tuple[bool, str]:
    """验证订阅源 URL 和 M3U 内容是否有效
    
    返回: (是否有效, 错误消息)
    """
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.text
    except httpx.HTTPStatusError as e:
        return False, f"HTTP 错误: {e.response.status_code}"
    except httpx.RequestError as e:
        return False, f"无法连接到服务器: {str(e)}"
    except Exception as e:
        return False, f"网络错误: {str(e)}"
    
    if not content or len(content.strip()) == 0:
        return False, "M3U 文件内容为空"
    
    if '#EXTM3U' not in content[:500]:
        return False, "不是有效的 M3U 文件（缺少 #EXTM3U 头）"
    
    try:
        streams = parse_m3u_from_url(url, content)
    except Exception as e:
        return False, f"M3U 解析失败: {str(e)}"
    
    if not streams or len(streams) == 0:
        return False, "M3U 文件中未找到任何直播流"
    
    return True, f"验证成功，找到 {len(streams)} 个直播流"


async def fetch_m3u_content(url: str) -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return url, response.text


async def validate_subscription_source_light(url: str) -> tuple[bool, str]:
    """轻量校验：仅确认 URL 可达且响应开头为 M3U 头，不做完整下载解析

    用于创建订阅源的请求路径，避免同步下载万级 M3U 导致接口超时。
    """
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # 使用流式请求，只读取前 2KB 判断格式
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    return False, f"HTTP 错误: {response.status_code}"
                head = ""
                async for chunk in response.aiter_bytes(2048):
                    head = chunk.decode(errors="ignore")
                    break
    except httpx.HTTPStatusError as e:
        return False, f"HTTP 错误: {e.response.status_code}"
    except httpx.RequestError as e:
        return False, f"无法连接到服务器: {str(e)}"
    except Exception as e:
        return False, f"网络错误: {str(e)}"

    if '#EXTM3U' not in head[:500]:
        return False, "不是有效的 M3U 文件（缺少 #EXTM3U 头）"

    return True, "校验通过"


async def create_source_record(
    db: AsyncSession,
    nickname: str,
    url: str,
    refresh_frequency_hours: int = 2,
) -> SubscriptionSource:
    """仅创建订阅源记录（不拉取内容），首次刷新由异步任务完成"""
    existing = await db.execute(
        select(SubscriptionSource).where(SubscriptionSource.url == url)
    )
    if existing.scalar_one_or_none():
        raise ValueError("该订阅源 URL 已存在")

    source = SubscriptionSource(
        nickname=nickname,
        url=url,
        refresh_frequency_hours=refresh_frequency_hours,
        last_refresh_status="pending"
    )
    db.add(source)
    await db.flush()
    return source


async def add_subscription_source(
    db: AsyncSession,
    nickname: str,
    url: str,
    refresh_frequency_hours: int = 2,
    analyze_video: bool = True
) -> tuple[SubscriptionSource, dict]:
    existing = await db.execute(
        select(SubscriptionSource).where(SubscriptionSource.url == url)
    )
    if existing.scalar_one_or_none():
        raise ValueError("该订阅源 URL 已存在")
    
    source = SubscriptionSource(
        nickname=nickname,
        url=url,
        refresh_frequency_hours=refresh_frequency_hours,
        last_refresh_status="pending"
    )
    db.add(source)
    await db.flush()
    
    result = await refresh_source(db, source.id, analyze_video=analyze_video)
    
    return source, result


async def refresh_source(db: AsyncSession, source_id: int, analyze_video: bool = True) -> dict:
    result = await db.execute(
        select(SubscriptionSource).where(SubscriptionSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    
    if not source:
        return {"error": "Source not found"}
    
    try:
        base_url, content = await fetch_m3u_content(source.url)
        streams_data = parse_m3u_from_url(source.url, content)

        new_count = 0
        updated_count = 0
        streams_to_analyze = []

        # 批量取回本次涉及的所有已有流（消除逐条查询的 N+1）
        all_hashes = [sd['url_hash'] for sd in streams_data]
        existing_streams: dict[str, Stream] = {}
        if all_hashes:
            existing_result = await db.execute(
                select(Stream).where(Stream.url_hash.in_(all_hashes))
            )
            for s in existing_result.scalars().all():
                existing_streams[s.url_hash] = s

        new_streams: list[Stream] = []

        for stream_data in streams_data:
            existing_stream = existing_streams.get(stream_data['url_hash'])

            if existing_stream:
                if source.id not in (existing_stream.source_ids or []):
                    existing_stream.source_ids = (existing_stream.source_ids or []) + [source.id]
                if stream_data.get('name') and not existing_stream.name:
                    existing_stream.name = stream_data.get('name')

                if analyze_video and not existing_stream.video_width:
                    streams_to_analyze.append((str(existing_stream.id), stream_data['url']))

                updated_count += 1
            else:
                new_stream = Stream(
                    url=stream_data['url'],
                    url_hash=stream_data['url_hash'],
                    name=stream_data.get('name'),
                    source_ids=[source.id],
                    active="auto",
                    first_discovered_at=datetime.utcnow()
                )
                db.add(new_stream)
                new_streams.append((new_stream, stream_data))
                new_count += 1

        # 单次 flush 为所有新流分配主键，随后补齐待分析列表
        if new_streams:
            await db.flush()
            for new_stream, stream_data in new_streams:
                if analyze_video:
                    streams_to_analyze.append((str(new_stream.id), stream_data['url']))

        # 用 GIN 索引统计该源的流数量（避免全表扫描）
        stream_count_result = await db.execute(
            select(func.count(Stream.id)).where(Stream.source_ids.contains([source.id]))
        )
        stream_count = stream_count_result.scalar() or 0
        
        source.last_refresh_time = datetime.utcnow()
        source.last_refresh_status = "success"
        source.stream_count = stream_count
        
        await db.commit()
        
        return {
            "status": "success",
            "new_streams": new_count,
            "updated_streams": updated_count,
            "total_streams": stream_count,
            "streams_to_analyze": streams_to_analyze,
        }
        
    except Exception as e:
        # 先回滚，避免把异常前已加入 session 的半成品数据（部分新流）一并提交
        try:
            await db.rollback()
        except Exception as re_err:
            logger.warning(f"Rollback after refresh failure failed: {re_err}")

        # 用独立会话更新 source 状态（原 session 事务已回滚）
        try:
            from app.core.database import async_session_maker
            async with async_session_maker() as status_db:
                status_source = (await status_db.execute(
                    select(SubscriptionSource).where(SubscriptionSource.id == source_id)
                )).scalar_one_or_none()
                if status_source:
                    status_source.last_refresh_time = datetime.utcnow()
                    status_source.last_refresh_status = "failed"
                    await status_db.commit()
        except Exception as status_err:
            logger.error(f"Failed to update source refresh status: {status_err}")

        try:
            await notify_source_refresh_failed(db, source.nickname, source.url, str(e))
        except Exception as notify_error:
            logger.error(f"Failed to send notification: {notify_error}")

        return {
            "status": "failed",
            "error": str(e)
        }


async def get_all_sources(db: AsyncSession) -> list[SubscriptionSource]:
    result = await db.execute(select(SubscriptionSource))
    return result.scalars().all()


async def get_source_by_id(db: AsyncSession, source_id: int) -> SubscriptionSource | None:
    result = await db.execute(
        select(SubscriptionSource).where(SubscriptionSource.id == source_id)
    )
    return result.scalar_one_or_none()


async def update_source(
    db: AsyncSession,
    source_id: int,
    nickname: str | None = None,
    url: str | None = None,
    refresh_frequency_hours: int | None = None
) -> SubscriptionSource | None:
    result = await db.execute(
        select(SubscriptionSource).where(SubscriptionSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    
    if not source:
        return None
    
    if nickname is not None:
        source.nickname = nickname
    if url is not None:
        source.url = url
    if refresh_frequency_hours is not None:
        source.refresh_frequency_hours = refresh_frequency_hours
    
    await db.commit()
    return source


async def delete_source(db: AsyncSession, source_id: int, delete_streams: bool = False) -> bool:
    result = await db.execute(
        select(SubscriptionSource).where(SubscriptionSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    
    if not source:
        return False
    
    if delete_streams:
        # 使用 GIN 索引只取回属于该源的流，避免全表加载
        streams_result = await db.execute(
            select(Stream).where(Stream.source_ids.contains([source_id]))
        )
        source_streams = streams_result.scalars().all()

        for stream in source_streams:
            stream.source_ids = [sid for sid in (stream.source_ids or []) if sid != source_id]
            if not stream.source_ids:
                await db.delete(stream)
    
    await db.delete(source)
    await db.commit()
    return True
