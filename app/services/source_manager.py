import httpx
import logging
from sqlalchemy import select
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
        
        for stream_data in streams_data:
            result = await db.execute(
                select(Stream).where(Stream.url_hash == stream_data['url_hash'])
            )
            existing_stream = result.scalar_one_or_none()
            
            if existing_stream:
                if source.id not in existing_stream.source_ids:
                    existing_stream.source_ids = existing_stream.source_ids + [source.id]
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
                await db.flush()
                
                if analyze_video:
                    streams_to_analyze.append((str(new_stream.id), stream_data['url']))
                
                new_count += 1
        
        await db.flush()
        
        stream_count_result = await db.execute(
            select(Stream).where(Stream.source_ids.contains([source.id]))
        )
        stream_count = len(stream_count_result.scalars().all())
        
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
        source.last_refresh_time = datetime.utcnow()
        source.last_refresh_status = "failed"
        await db.commit()
        
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
        all_streams_result = await db.execute(select(Stream))
        all_streams = all_streams_result.scalars().all()
        
        for stream in all_streams:
            if stream.source_ids and source_id in stream.source_ids:
                stream.source_ids = [sid for sid in stream.source_ids if sid != source_id]
                if not stream.source_ids:
                    await db.delete(stream)
    
    await db.delete(source)
    await db.commit()
    return True
