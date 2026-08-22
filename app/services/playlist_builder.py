from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import Stream, Channel
from app.core.config import get_settings

settings = get_settings()

# benchmark 数据的进程内缓存（60s TTL）
_benchmark_cache: dict = {"data": None, "ts": 0.0}


def build_m3u_content(channels_data: list[dict]) -> str:
    lines = ["#EXTM3U"]
    
    for channel in channels_data:
        stream = channel.get("stream", {})
        
        extinf = f'#EXTINF:-1 tvg-id="{stream.get("tvg_id", "")}" tvg-name="{channel.get("name", "")}" tvg-logo="{stream.get("logo", "")}" group-title="{channel.get("category", "")}",{channel.get("name", "")}'
        lines.append(extinf)
        lines.append(stream.get("url", ""))
    
    return "\n".join(lines)


async def generate_playlist(
    db: AsyncSession,
    strategy: str = "playoptimized",
    limit: int = None
) -> str:
    forgiveness = settings.FORGIVENESS_PARAM

    # 单查询联表取回所有频道及其可用流（消除每频道一次查询的 N+1）
    streams_query = await db.execute(
        select(Channel, Stream)
        .outerjoin(
            Stream,
            (Stream.channel_id == Channel.id)
            & (Stream.active != "false")
            & ~((Stream.unreachable_count > forgiveness) & (Stream.active != "true"))
        )
        .order_by(Channel.order_index)
    )
    rows = streams_query.all()

    # 按频道分组
    channels_data_map: dict[int, dict] = {}
    for channel, stream in rows:
        if channel.id not in channels_data_map:
            channels_data_map[channel.id] = {
                "channel": channel,
                "streams": [],
            }
        if stream is not None:
            channels_data_map[channel.id]["streams"].append(stream)

    playlist_data = []

    for entry in channels_data_map.values():
        channel = entry["channel"]
        streams = entry["streams"]

        if not streams:
            continue

        if strategy == "playfast":
            streams = sorted(streams, key=lambda s: s.latency_ms or 999999)
        elif strategy == "playbest":
            streams = sorted(streams, key=lambda s: s.bitrate_kbps or 0, reverse=True)
        elif strategy == "playstable":
            streams = sorted(streams, key=lambda s: s.stability_score or 0, reverse=True)
        elif strategy == "playoptimized":
            # v0.2.1: 基于归一化指标的加权得分排序
            valid_streams = [s for s in streams if s.latency_ms is not None and s.bitrate_kbps is not None and s.stability_score is not None]

            if len(valid_streams) >= 2:
                # 获取各指标的 min/max 用于归一化
                latencies = [s.latency_ms for s in valid_streams]
                bitrates = [s.bitrate_kbps for s in valid_streams]
                stabilities = [s.stability_score for s in valid_streams]

                min_latency, max_latency = min(latencies), max(latencies)
                min_bitrate, max_bitrate = min(bitrates), max(bitrates)
                min_stability, max_stability = min(stabilities), max(stabilities)

                # 避免除以零
                latency_range = max_latency - min_latency if max_latency > min_latency else 1
                bitrate_range = max_bitrate - min_bitrate if max_bitrate > min_bitrate else 1
                stability_range = max_stability - min_stability if max_stability > min_stability else 1

                scored_streams = []
                for s in valid_streams:
                    # Min-Max 归一化
                    # 延迟 (越小越好): (max - value) / (max - min)
                    normalized_latency = (max_latency - s.latency_ms) / latency_range
                    # 码率 (越大越好): (value - min) / (max - min)
                    normalized_bitrate = (s.bitrate_kbps - min_bitrate) / bitrate_range
                    # 稳定性 (越大越好): (value - min) / (max - min)
                    normalized_stability = (s.stability_score - min_stability) / stability_range

                    # 加权计算: 延迟 50% + 码率 30% + 稳定性 20%
                    score = normalized_latency * 0.5 + normalized_bitrate * 0.3 + normalized_stability * 0.2
                    scored_streams.append((s, score))

                # 按得分从高到低排序
                streams = [s for s, _ in sorted(scored_streams, key=lambda x: x[1], reverse=True)]
            elif valid_streams:
                streams = valid_streams

        best_stream = streams[0]

        playlist_data.append({
            "name": channel.standard_name,
            "category": channel.category or "",
            "logo": channel.logo_path or "",
            "tvg_id": channel.tvg_id or "",
            "stream": {
                "url": best_stream.url,
                "tvg_id": channel.tvg_id or "",
                "logo": channel.logo_path or "",
                "latency_ms": best_stream.latency_ms,
                "bitrate_kbps": best_stream.bitrate_kbps,
                "stability_score": best_stream.stability_score
            }
        })

        if limit and len(playlist_data) >= limit:
            break

    return build_m3u_content(playlist_data)


async def get_benchmark_data(db: AsyncSession) -> dict:
    import time as _time
    from sqlalchemy import text as sa_text

    # 进程内 60s 缓存：benchmark 数据随分析批次变化，无需每次全表 JSONB 展开
    global _benchmark_cache
    now = _time.monotonic()
    if _benchmark_cache["data"] is not None and (now - _benchmark_cache["ts"]) < 60:
        return _benchmark_cache["data"]

    # 按 jsonb_array_elements 展开统计：多来源流会为每个来源各计一次，
    # 修复原先"按整个数组 GROUP BY 再只取第一个 id"的口径错误，且无 N+1
    sql = sa_text("""
        SELECT
            sid AS source_id,
            AVG(latency_ms) AS avg_latency,
            MIN(latency_ms) AS min_latency,
            MAX(latency_ms) AS max_latency,
            AVG(bitrate_kbps) AS avg_bitrate,
            AVG(stability_score) AS avg_stability,
            COUNT(*) AS total_streams,
            SUM(CASE WHEN unreachable_count > :forgiveness THEN 1 ELSE 0 END) AS unreachable_streams
        FROM (
            SELECT s.*, j.sid
            FROM streams s, jsonb_array_elements_text(s.source_ids) AS j(sid)
        ) expanded
        GROUP BY sid
        ORDER BY sid
    """)

    results = (await db.execute(sql, {"forgiveness": settings.FORGIVENESS_PARAM})).all()

    benchmark = []
    for row in results:
        total = int(row.total_streams or 0)
        source_id = int(row.source_id)
        unreachable = int(row.unreachable_streams or 0)

        benchmark.append({
            "source_id": source_id,
            "avg_latency": float(row.avg_latency) if row.avg_latency else 0,
            "min_latency": float(row.min_latency) if row.min_latency else 0,
            "max_latency": float(row.max_latency) if row.max_latency else 0,
            "avg_bitrate": float(row.avg_bitrate) if row.avg_bitrate else 0,
            "avg_stability": float(row.avg_stability) if row.avg_stability else 0,
            "total_streams": total,
            "unreachable_percentage": (unreachable / total * 100) if total > 0 else 0
        })

    data = {"sources": benchmark}
    _benchmark_cache["data"] = data
    _benchmark_cache["ts"] = now
    return data
