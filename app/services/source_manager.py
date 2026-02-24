import httpx
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from app.models.models import SubscriptionSource, Stream
from app.utils.m3u_parser import parse_m3u_from_url
from app.services.notification_service import (
    notify_source_refresh_failed,
    dispatch_notification,
    CHANNEL_MAINTENANCE,
)
from app.services.stream_analyzer import analyze_stream_video_properties

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
                    existing_stream.name = stream_data['name']
                
                if analyze_video and not existing_stream.video_width:
                    streams_to_analyze.append((existing_stream, stream_data['url']))
                
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
                    streams_to_analyze.append((new_stream, stream_data['url']))
                
                new_count += 1
        
        if analyze_video and streams_to_analyze:
            task_identifier = f"video-basic-{source_id}"
            total_to_analyze = len(streams_to_analyze)
            analyzed_count = 0
            
            await dispatch_notification(
                db=db,
                issuer="system",
                subject=f"[{task_identifier}] 订阅源 {source.nickname} 视频基本信息分析 (0/{total_to_analyze})",
                context=f"开始分析视频基本信息: 共 {total_to_analyze} 个直播流",
                severity="info",
                channels=[CHANNEL_MAINTENANCE],
                valid_hours=24,
                task_identifier=task_identifier,
                update_existing=True,
            )
            
            for stream_obj, stream_url in streams_to_analyze:
                try:
                    video_props = await analyze_stream_video_properties(stream_url, timeout=5)
                    stream_obj.video_width = video_props.get('video_width')
                    stream_obj.video_height = video_props.get('video_height')
                    stream_obj.video_fps = video_props.get('video_fps')
                    stream_obj.video_codec = video_props.get('video_codec')
                    stream_obj.video_bit_depth = video_props.get('video_bit_depth')
                    stream_obj.video_color_profile = video_props.get('video_color_profile')
                    stream_obj.audio_codec = video_props.get('audio_codec')
                    stream_obj.video_bitrate_kbps = video_props.get('video_bitrate_kbps')
                    stream_obj.video_analyzed_at = datetime.utcnow()
                except Exception as e:
                    logger.warning(f"Failed to analyze video properties for {stream_url}: {e}")
                
                analyzed_count += 1
                
                if analyzed_count % 5 == 0 or analyzed_count == total_to_analyze:
                    await dispatch_notification(
                        db=db,
                        issuer="system",
                        subject=f"[{task_identifier}] 订阅源 {source.nickname} 视频基本信息分析 ({analyzed_count}/{total_to_analyze})",
                        context=f"分析进度: 已分析 {analyzed_count}/{total_to_analyze} 个直播流",
                        severity="info" if analyzed_count < total_to_analyze else "success",
                        channels=[CHANNEL_MAINTENANCE],
                        valid_hours=24,
                        task_identifier=task_identifier,
                        update_existing=True,
                    )
        
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
            "total_streams": stream_count
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
