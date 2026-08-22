import asyncio
import httpx
import time
import logging
from datetime import datetime
from sqlalchemy import select, update, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import Stream, AnalysisHistory, Channel, NotificationItem
from app.core.config import get_settings
from app.services.notification_service import (
    notify_stream_unreachable_threshold,
    notify_available_channels_threshold,
    notify_channel_all_streams_down
)
from app.services.config_service import ConfigService

settings = get_settings()
logger = logging.getLogger(__name__)


async def _get_stream_by_id(db: AsyncSession, stream_id: str) -> Stream | None:
    result = await db.execute(
        select(Stream).where(Stream.id == stream_id)
    )
    return result.scalar_one_or_none()


def _update_stream_reachability(stream: Stream, latency: int | None):
    if latency is not None:
        stream.latency_ms = latency
        stream.unreachable_count = 0
    else:
        stream.unreachable_count += 1
    stream.last_analysis_time = datetime.utcnow()


async def analyze_stream_latency(stream_url: str, timeout: int = 3) -> int | None:
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(stream_url, follow_redirects=True)
            latency_ms = int((time.time() - start) * 1000)
            
            if response.status_code == 200:
                return latency_ms
            return None
    except Exception:
        logger.debug(f"Failed to analyze stream latency for {stream_url}")
        return None


async def analyze_stream_bitrate(stream_url: str, timeout: int = 3) -> int | None:
    try:
        import subprocess
        import re
        
        result = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_entries', 'stream=bit_rate,codec_name,width,height',
            stream_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, _ = await asyncio.wait_for(result.communicate(), timeout=timeout)
        
        if result.returncode == 0:
            output = stdout.decode().strip()
            
            import json
            try:
                data = json.loads(output)
                for stream in data.get('streams', []):
                    if stream.get('codec_name') in ['h264', 'hevc', 'av1', 'mpeg2video']:
                        bitrate = stream.get('bit_rate')
                        if bitrate:
                            return int(bitrate) // 1000
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        
        bandwidth_result = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_entries', 'manifest#BANDWIDTH',
            '-of', 'json',
            stream_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, _ = await asyncio.wait_for(bandwidth_result.communicate(), timeout=timeout)
        
        if bandwidth_result.returncode == 0:
            output = stdout.decode().strip()
            import json
            try:
                data = json.loads(output)
                for program in data.get('programs', []):
                    for stream in program.get('streams', []):
                        bandwidth = stream.get('BANDWIDTH')
                        if bandwidth:
                            return int(bandwidth) // 1000
                if 'manifest' in data:
                    bandwidth = data['manifest'].get('BANDWIDTH')
                    if bandwidth:
                        return int(bandwidth) // 1000
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        
        return None
    except Exception:
        logger.debug(f"Failed to analyze stream bitrate for {stream_url}")
        return None


async def analyze_stream_video_properties(stream_url: str, timeout: int = 10, calculate_bitrate: bool = False, max_retries: int = 2) -> dict:
    """使用 ffprobe 分析视频属性
    
    返回: { width, height, fps, codec, bit_depth, color_profile, audio_codec, bitrate_kbps, analysis_failed }
    当所有尝试都失败时，analysis_failed 为 True
    """
    logger.debug(f"Starting analyze_stream_video_properties for: {stream_url}")
    
    result = {
        "video_width": None,
        "video_height": None,
        "video_fps": None,
        "video_codec": None,
        "video_bit_depth": None,
        "video_color_profile": None,
        "audio_codec": None,
        "video_bitrate_kbps": None,
        "analysis_failed": False,  # 新增字段，标记分析是否失败
    }
    
    logger.debug(f"Result dict created")
    
    # 重试机制
    for attempt in range(max_retries):
        try:
            import json
            
            # 根据URL类型调整FFprobe参数
            is_rtp = 'rtp://' in stream_url or '/rtp/' in stream_url
            
            cmd = [
                'ffprobe', '-v', 'error',
                '-print_format', 'json',
                '-show_format', '-show_streams',
                '-timeout', str(timeout * 1000000),
            ]
            
            # 为RTP流添加额外参数
            if is_rtp:
                cmd.extend([
                    '-probesize', '10000000',  # 增加探测大小
                    '-analyzeduration', '10000000',  # 增加分析时长
                ])
                logger.debug(f"Using RTP-specific parameters for {stream_url}")
            
            cmd.append(stream_url)
            
            logger.debug(f"Attempt {attempt + 1}/{max_retries} for {stream_url}")
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2)
            
            # 记录stderr输出用于调试
            stderr_text = stderr.decode() if stderr else ""
            stdout_text = stdout.decode() if stdout else ""
            
            if stderr_text:
                logger.debug(f"FFprobe stderr for {stream_url}: {stderr_text[:200]}")
            
            # 记录stdout长度用于调试
            logger.debug(f"FFprobe stdout length for {stream_url}: {len(stdout_text)} chars")
            
            # 检查是否有解码错误但可能仍然有有效数据
            has_decoding_errors = 'non-existing PPS' in stderr_text or 'no frame!' in stderr_text
            
            # 即使有错误输出，只要返回码为0且stdout有内容，就尝试解析
            # 对于RTP流，即使有解码错误，也可能有有效的流信息
            if proc.returncode != 0 and not stdout_text:
                logger.debug(f"FFprobe failed for {stream_url}: returncode={proc.returncode}")
                if attempt == max_retries - 1:
                    result["analysis_failed"] = True
                    return result
                continue  # 重试
            
            # 如果有解码错误但stdout有内容，记录警告但继续解析
            if has_decoding_errors and stdout_text:
                logger.debug(f"FFprobe has decoding errors but may still have valid data for {stream_url}")
            
            try:
                data = json.loads(stdout_text)
                streams_count = len(data.get('streams', []))
                logger.debug(f"Successfully parsed JSON for {stream_url}, streams count: {streams_count}")
                
                # 如果没有流信息，记录警告
                if streams_count == 0:
                    logger.debug(f"No streams found in JSON for {stream_url}")
                    if attempt == max_retries - 1:
                        result["analysis_failed"] = True
                        return result
                    continue  # 重试
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.debug(f"Failed to parse FFprobe JSON for {stream_url}: {e}, stdout preview: {stdout_text[:200]}")
                if attempt == max_retries - 1:
                    result["analysis_failed"] = True
                    return result
                continue  # 重试
            
            for stream in data.get('streams', []):
                codec_type = stream.get('codec_type')
                codec_name = stream.get('codec_name', '')
                
                if codec_type == 'video':
                    result['video_width'] = stream.get('width')
                    result['video_height'] = stream.get('height')
                    
                    fps_str = stream.get('r_frame_rate', '0/1')
                    if '/' in fps_str:
                        num, den = fps_str.split('/')
                        if den and int(den) > 0:
                            result['video_fps'] = round(int(num) / int(den), 2)
                    
                    result['video_codec'] = codec_name
                    
                    bit_depth = stream.get('bits_per_raw_sample')
                    if not bit_depth:
                        bit_depth = stream.get('bits_per_sample')
                    if bit_depth:
                        result['video_bit_depth'] = int(bit_depth)
                    
                    profile = stream.get('profile', '')
                    if profile:
                        result['video_color_profile'] = profile
                
                elif codec_type == 'audio':
                    if not result['audio_codec']:
                        result['audio_codec'] = codec_name
            
            if calculate_bitrate and not result['video_bitrate_kbps']:
                bitrate_kbps = await calculate_bitrate_with_ffmpeg(
                    stream_url, 
                    record_duration=settings.BITRATE_RECORD_DURATION_SECONDS, 
                    intervals=1, 
                    wait_seconds=0
                )
                if bitrate_kbps:
                    result['video_bitrate_kbps'] = bitrate_kbps
            
            logger.debug(f"Successfully analyzed {stream_url}: {result['video_width']}x{result['video_height']}")
            result["analysis_failed"] = False  # 明确标记分析成功
            return result
            
        except asyncio.TimeoutError:
            logger.debug(f"FFprobe timeout for {stream_url} (attempt {attempt + 1}/{max_retries})")
            if attempt == max_retries - 1:
                result["analysis_failed"] = True
                logger.debug(f"All {max_retries} attempts failed for {stream_url}")
                return result
            continue  # 重试
            
        except Exception as e:
            logger.debug(f"Unexpected error in analyze_stream_video_properties for {stream_url}: {e}")
            if attempt == max_retries - 1:
                result["analysis_failed"] = True
                return result
            continue  # 重试
    
    logger.debug(f"All attempts failed for {stream_url}")
    result["analysis_failed"] = True
    return result


async def calculate_bitrate_with_ffmpeg(stream_url: str, record_duration: int = 3, intervals: int = 1, wait_seconds: int = 0) -> int | None:
    """使用 ffmpeg 录制多次流来计算平均码率
    
    根据: https://blog.csdn.net/qq_23282479/article/details/119488291
    每次录制 record_duration 秒，录制 intervals 次，每次间隔 wait_seconds 秒，取平均
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        import re
        bitrates = []
        
        logger.info(f"开始计算码率，录制时长: {record_duration}秒")
        
        for i in range(intervals):
            if i > 0:
                await asyncio.sleep(wait_seconds)
            
            logger.info(f"开始第 {i+1} 次录制")
            
            # 不使用 -re：-re 会按原生速率限制读取，录制时长被强制拉满，
            # 纯属多余且拖慢单流分析
            cmd = [
                'ffmpeg', '-y', '-i', stream_url,
                '-t', str(record_duration),
                '-f', 'null', '-'
            ]
            
            logger.debug(f"执行命令: {' '.join(cmd)}")
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=record_duration + 15)
            except asyncio.TimeoutError:
                logger.warning(f"码率计算超时，杀死进程")
                proc.kill()
                await proc.wait()
                continue
            
            logger.info(f"ffmpeg 退出码: {proc.returncode}")
            
            output = stderr.decode()
            
            if output:
                logger.debug(f"ffmpeg stderr 输出: {output[-500:]}")
            
            bitrate_match = re.search(r'bitrate[:\s]+(\d+\.?\d*)\s*kbits/s', output, re.IGNORECASE)
            if bitrate_match:
                bitrate = int(float(bitrate_match.group(1)))
                logger.info(f"直接匹配到 bitrate: {bitrate} kbps")
                bitrates.append(bitrate)
                continue
            
            logger.info("未直接匹配到 bitrate，尝试其他方法计算")
            
            video_kib_match = re.search(r'video:(\d+)\s*KiB', output)
            audio_kib_match = re.search(r'audio:(\d+)\s*KiB', output)
            time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', output)
            
            if video_kib_match and audio_kib_match and time_match:
                video_kib = int(video_kib_match.group(1))
                audio_kib = int(audio_kib_match.group(1))
                
                hours = int(time_match.group(1))
                minutes = int(time_match.group(2))
                seconds = float(time_match.group(3))
                total_seconds = hours * 3600 + minutes * 60 + seconds
                
                logger.info(f"video: {video_kib} KiB, audio: {audio_kib} KiB, time: {total_seconds}s")
                
                if total_seconds > 0:
                    total_kib = video_kib + audio_kib
                    avg_bitrate_kbps = int((total_kib * 8) / total_seconds)
                    logger.info(f"计算得到 bitrate: {avg_bitrate_kbps} kbps")
                    bitrates.append(avg_bitrate_kbps)
                continue
            
            lsize_match = re.search(r'Lsize=(\d+)\s*kB', output)
            
            if lsize_match and time_match:
                size_kb = int(lsize_match.group(1))
                hours = int(time_match.group(1))
                minutes = int(time_match.group(2))
                seconds = float(time_match.group(3))
                total_seconds = hours * 3600 + minutes * 60 + seconds
                
                logger.info(f"Lsize: {size_kb} kB, time: {total_seconds}s")
                
                if total_seconds > 0:
                    avg_bitrate_kbps = int((size_kb * 8) / total_seconds)
                    logger.info(f"通过 Lsize 计算得到 bitrate: {avg_bitrate_kbps} kbps")
                    bitrates.append(avg_bitrate_kbps)
                continue
            
            logger.warning(f"所有方法都未能计算出码率，输出: {output[-800:]}")
        
        if bitrates:
            avg_bitrate = sum(bitrates) // len(bitrates)
            logger.info(f"码率计算成功，最终平均: {avg_bitrate} kbps, 所有结果: {bitrates}")
            return avg_bitrate
        
        logger.warning("所有录制都未能计算出码率")
        return None
    except Exception as e:
        logger.error(f"码率计算异常: {e}", exc_info=True)
        return None


async def analyze_stream_stability(stream_url: str, duration: int = 3) -> dict:
    """
    v0.2.1: 细化的稳定性测试
    - connection_stability: 连接稳定性 (0-1)
    - continuity_score: 数据流连续性评分 (0-100)
    - hls_health_score: HLS协议健康度 (0-100)
    """
    connection_stability = 1.0
    continuity_score = 100.0
    hls_health_score = 100.0
    stability_score = 100.0
    
    try:
        async with httpx.AsyncClient(timeout=duration + 2) as client:
            start_time = time.time()
            bytes_received = 0
            chunks_received = 0
            empty_chunks = 0
            time_slices = []  # 用于计算连续性
            
            async with client.stream('GET', stream_url) as response:
                if response.status_code != 200:
                    return {
                        "connection_stability": 0.0,
                        "continuity_score": 0.0,
                        "hls_health_score": 0.0,
                        "stability_score": 0.0
                    }
                
                slice_duration = duration / 10  # 分成10个时间片
                last_slice_time = start_time
                slice_data_count = 0
                
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    current_time = time.time()
                    bytes_received += len(chunk)
                    chunks_received += 1
                    
                    # 检查时间片内是否收到数据
                    if current_time - last_slice_time >= slice_duration:
                        time_slices.append(slice_data_count > 0)
                        slice_data_count = 0
                        last_slice_time = current_time
                    
                    if len(chunk) > 0:
                        slice_data_count += 1
                    else:
                        empty_chunks += 1
                    
                    if current_time - start_time >= duration:
                        break
                
                # 添加最后一个时间片
                time_slices.append(slice_data_count > 0)
                
                elapsed = current_time - start_time
                
                # 连接稳定性: 测试期间连接是否断开
                connection_stability = 1.0 if chunks_received > 0 else 0.0
                
                # 数据流连续性评分: 收到数据的时间片比例
                if time_slices:
                    continuity_score = (sum(time_slices) / len(time_slices)) * 100
                else:
                    continuity_score = 0.0
                
                # HLS健康度检查 (简单检查)
                if stream_url.endswith('.m3u8') or 'm3u8' in stream_url:
                    try:
                        head_response = await client.head(stream_url, timeout=2)
                        hls_health_score = 100.0 if head_response.status_code == 200 else 50.0
                    except (httpx.HTTPError, asyncio.TimeoutError):
                        hls_health_score = 0.0
                else:
                    hls_health_score = 100.0  # 非HLS流默认健康
                
                # 综合稳定性评分: 加权平均（统一归一化到 0-100 后加权 40/40/20）
                stability_score = (
                    connection_stability * 100 * 0.4 +
                    continuity_score * 0.4 +
                    hls_health_score * 0.2
                )
                
    except Exception as e:
        connection_stability = 0.0
        continuity_score = 0.0
        hls_health_score = 0.0
        stability_score = 0.0
    
    return {
        "connection_stability": round(connection_stability, 2),
        "continuity_score": round(continuity_score, 2),
        "hls_health_score": round(hls_health_score, 2),
        "stability_score": round(stability_score, 2)
    }


async def analyze_stream_full(db: AsyncSession, stream_id: str) -> dict:
    stream = await _get_stream_by_id(db, stream_id)
    
    if not stream:
        return {"error": "Stream not found"}
    
    stream_url = stream.url
    
    analysis_timeout = await ConfigService.get_analysis_timeout_seconds(db)
    full_analysis_timeout = ConfigService.get_full_analysis_timeout_seconds()
    
    latency = await analyze_stream_latency(stream_url, analysis_timeout)
    bitrate = await analyze_stream_bitrate(stream_url, timeout=full_analysis_timeout)
    stability = await analyze_stream_stability(stream_url, analysis_timeout)
    video_props = await analyze_stream_video_properties(
        stream_url, 
        timeout=full_analysis_timeout, 
        calculate_bitrate=True
    )
    
    video_bitrate_from_props = video_props.get('video_bitrate_kbps') if video_props else None
    final_bitrate = video_bitrate_from_props if video_bitrate_from_props is not None else bitrate
    
    history = AnalysisHistory(
        stream_id=stream.id,
        latency_ms=latency,
        bitrate_kbps=final_bitrate,
        stability_score=stability.get("stability_score"),
        connection_stability=stability.get("connection_stability"),
        continuity_score=stability.get("continuity_score"),
        hls_health_score=stability.get("hls_health_score"),
        response_code=200 if latency else 500
    )
    db.add(history)
    
    if latency is not None:
        stream.latency_ms = latency
        stream.bitrate_kbps = final_bitrate
        stream.stability_score = stability.get("stability_score")
        stream.enhanced_analysis_failed = False
    else:
        stream.enhanced_analysis_failed = True
    _update_stream_reachability(stream, latency)
    
    if video_props:
        if video_props.get('analysis_failed'):
            stream.video_analysis_failed = True
        else:
            stream.video_width = video_props.get('video_width')
            stream.video_height = video_props.get('video_height')
            stream.video_fps = video_props.get('video_fps')
            stream.video_codec = video_props.get('video_codec')
            stream.video_bit_depth = video_props.get('video_bit_depth')
            stream.video_color_profile = video_props.get('video_color_profile')
            stream.audio_codec = video_props.get('audio_codec')
            stream.video_bitrate_kbps = video_bitrate_from_props
            stream.video_analysis_failed = False
        stream.video_analyzed_at = datetime.utcnow()
    
    await db.commit()
    
    return {
        "stream_id": stream_id,
        "latency_ms": latency,
        "bitrate_kbps": final_bitrate,
        "stability_score": stability.get("stability_score"),
        "connection_stability": stability.get("connection_stability"),
        "continuity_score": stability.get("continuity_score"),
        "hls_health_score": stability.get("hls_health_score"),
        "unreachable_count": stream.unreachable_count
    }


async def analyze_stream_quick(db: AsyncSession, stream_id: str) -> dict:
    stream = await _get_stream_by_id(db, stream_id)
    
    if not stream:
        return {"error": "Stream not found"}
    
    analysis_timeout = await ConfigService.get_analysis_timeout_seconds(db)
    latency = await analyze_stream_latency(stream.url, analysis_timeout)
    
    history = AnalysisHistory(
        stream_id=stream.id,
        latency_ms=latency,
        response_code=200 if latency else 500
    )
    db.add(history)
    
    _update_stream_reachability(stream, latency)
    
    if latency is not None:
        stream.enhanced_analysis_failed = False
    else:
        stream.enhanced_analysis_failed = True
    
    await db.commit()
    
    return {
        "stream_id": stream_id,
        "latency_ms": latency,
        "unreachable_count": stream.unreachable_count
    }


async def analyze_all_streams(db: AsyncSession, mode: str = "full") -> dict:
    result = await db.execute(
        select(Stream).where(Stream.active != "false")
    )
    streams = result.scalars().all()

    total = len(streams)
    success = 0
    failed = 0

    for stream in streams:
        if mode == "quick":
            result = await analyze_stream_quick(db, str(stream.id))
        else:
            result = await analyze_stream_full(db, str(stream.id))

        if result.get("error"):
            failed += 1
        else:
            success += 1

    # 分析完成后检查阈值并发送通知
    await _check_and_send_notifications(db)

    return {
        "total": total,
        "success": success,
        "failed": failed
    }


async def check_thresholds_and_notify(db: AsyncSession):
    """批量分析完成后检查各类阈值并发送通知（供 batch_analyze_streams_task 调用）

    使用聚合 SQL 实现，避免全表载入内存 + O(C×S) 线性扫描。
    """
    forgiveness_param = await ConfigService.get_forgiveness_param(db)

    # 读取通知事项配置（阈值/开关），未配置时使用默认值
    items_result = await db.execute(
        select(NotificationItem).where(NotificationItem.key.in_(
            ["stream_unreachable", "channel_available", "channel_all_down"]
        ))
    )
    item_map = {item.key: item for item in items_result.scalars().all()}

    def _enabled(key: str) -> bool:
        item = item_map.get(key)
        return item.enabled if item else True

    def _threshold(key: str, default: int) -> int:
        item = item_map.get(key)
        if item and item.threshold_value is not None:
            return item.threshold_value
        return default

    # ---- 聚合统计 1：流级指标（单条 SQL）----
    stream_stats_result = await db.execute(
        select(
            func.count(Stream.id).label("total"),
            func.sum(
                case((Stream.unreachable_count > forgiveness_param, 1), else_=0)
            ).label("unreachable"),
        )
    )
    row = stream_stats_result.one()
    total_streams = int(row.total or 0)
    unreachable_count = int(row.unreachable or 0)

    if total_streams == 0:
        return

    # 直播流不可达阈值
    if _enabled("stream_unreachable"):
        unreachable_percent = unreachable_count / total_streams * 100
        threshold = _threshold("stream_unreachable", 30)
        if unreachable_percent >= threshold:
            try:
                await notify_stream_unreachable_threshold(db, threshold, unreachable_count, total_streams)
            except Exception as e:
                logger.error(f"Failed to send stream unreachable notification: {e}")

    # ---- 聚合统计 2：频道级指标（按 channel_id GROUP BY，走 idx_streams_channel）----
    channel_stats_result = await db.execute(
        select(
            Stream.channel_id,
            func.count(Stream.id).label("total"),
            func.sum(
                case(
                    (
                        (Stream.unreachable_count <= forgiveness_param) & (Stream.active != "false"),
                        1,
                    ),
                    else_=0,
                )
            ).label("available"),
        )
        .where(Stream.channel_id.isnot(None))
        .group_by(Stream.channel_id)
    )
    channel_rows = channel_stats_result.all()

    total_channels_with_streams = len(channel_rows)
    if total_channels_with_streams == 0:
        return

    available_channels = 0
    all_down_names: list[str] = []

    # 仅对"全下线"的频道取名称（数量通常极少）
    all_down_ids = [
        r.channel_id for r in channel_rows
        if (r.available or 0) == 0
    ]

    if _enabled("channel_all_down") and all_down_ids:
        names_result = await db.execute(
            select(Channel.id, Channel.standard_name).where(Channel.id.in_(all_down_ids))
        )
        id_to_name = {cid: name for cid, name in names_result.all()}
        for cid in all_down_ids:
            name = id_to_name.get(cid, f"ID:{cid}")
            all_down_names.append(name)
            try:
                await notify_channel_all_streams_down(db, name)
            except Exception as e:
                logger.error(f"Failed to send channel all down notification: {e}")

    for r in channel_rows:
        if (r.available or 0) > 0:
            available_channels += 1

    # 可用频道比例阈值
    if _enabled("channel_available"):
        available_percent = available_channels / total_channels_with_streams * 100
        threshold = _threshold("channel_available", 50)
        if available_percent < threshold:
            try:
                await notify_available_channels_threshold(db, threshold, available_channels, total_channels_with_streams)
            except Exception as e:
                logger.error(f"Failed to send available channels notification: {e}")


async def _check_and_send_notifications(db: AsyncSession):
    """兼容旧调用入口"""
    await check_thresholds_and_notify(db)
