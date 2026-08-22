import httpx
import json
import logging
import os
import re
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import Channel, Stream
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

LOCAL_ALIAS_FILE = "app/static/channel_alias.json"

# 预编译归一化正则（避免在热路径中反复编译）
_NORMALIZE_RE = re.compile(r'[^\w\u4e00-\u9fff0-9]')
_EXTRACT_NUM_RE = re.compile(r'(\d+)$')


async def fetch_channel_aliases() -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(settings.CHANNEL_ALIAS_URL)
            response.raise_for_status()
            data = response.json()
            return _parse_alias_data(data)
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to fetch channel aliases from remote: {e}")
            return _load_local_aliases()


def _load_local_aliases() -> list[dict]:
    try:
        if os.path.exists(LOCAL_ALIAS_FILE):
            with open(LOCAL_ALIAS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return _parse_alias_data(data)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load local channel aliases: {e}")
    return []


def _parse_alias_data(data) -> list[dict]:
    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        channels = []
        for name, aliases in data.items():
            if name.startswith('__'):
                continue
            if isinstance(aliases, list):
                channels.append({
                    "name": name,
                    "aliases": aliases
                })
            elif isinstance(aliases, dict):
                channels.append({
                    "name": name,
                    "aliases": aliases.get("aliases", []),
                    "category": aliases.get("category"),
                    "logo": aliases.get("logo"),
                    "tvg_id": aliases.get("tvg_id"),
                    "group": aliases.get("group")
                })
        return channels
    return []


async def import_channel_aliases(db: AsyncSession) -> dict:
    aliases_data = await fetch_channel_aliases()
    
    if not aliases_data:
        return {"status": "no_data", "imported": 0}
    
    # 一次性取回全部频道，内存中按 standard_name 建索引（消除逐条 SELECT）
    all_channels_result = await db.execute(select(Channel))
    existing_by_name = {
        c.standard_name: c for c in all_channels_result.scalars().all()
    }
    
    imported = 0
    updated = 0
    next_order = len(existing_by_name)
    for idx, item in enumerate(aliases_data):
        name = ""
        aliases = []
        category = None
        logo = None
        tvg_id = None
        group = None
        
        if isinstance(item, dict):
            name = item.get("name", item.get("channel_name", ""))
            aliases = item.get("aliases", item.get("alias", []))
            if isinstance(aliases, str):
                aliases = [aliases] if aliases else []
            category = item.get("category")
            logo = item.get("logo", item.get("logo_path"))
            tvg_id = item.get("tvg_id", item.get("tvgId"))
            group = item.get("group", item.get("group_title"))
        elif isinstance(item, str):
            name = item
            aliases = []
        
        if not name:
            continue
        
        existing = existing_by_name.get(name)
        
        if existing:
            existing.aliases = aliases if aliases else []
            if category:
                existing.category = category
            if logo:
                existing.logo_path = logo
            if tvg_id:
                existing.tvg_id = tvg_id
            if group:
                existing.group_name = group
            updated += 1
        else:
            next_order += 1
            channel = Channel(
                standard_name=name,
                aliases=aliases if aliases else [],
                category=category,
                logo_path=logo,
                tvg_id=tvg_id,
                group_name=group,
                order_index=next_order
            )
            db.add(channel)
            existing_by_name[name] = channel  # 防止同批次重复名重复插入
            imported += 1
    
    await db.commit()
    
    return {
        "status": "success",
        "imported": imported,
        "updated": updated
    }


def normalize_channel_name(name: str) -> str:
    name = name.lower().strip()
    # 保留数字，只去除特殊字符
    name = _NORMALIZE_RE.sub('', name)
    return name


def extract_channel_number(name: str) -> str | None:
    """提取频道名称中的数字部分，如 CCTV1 -> 1, CCTV17 -> 17"""
    match = _EXTRACT_NUM_RE.search(name)
    if match:
        return match.group(1)
    return None


def fuzzy_match_score(candidate: str, target: str) -> float:
    """
    改进的匹配算法：
    - 完全匹配：1.0
    - 名称互相包含且数字部分一致：0.9
    - 名称互相包含但数字部分不同：0.3（避免CCTV1匹配CCTV17）
    - 其他情况：0.0
    """
    candidate_norm = normalize_channel_name(candidate)
    target_norm = normalize_channel_name(target)
    
    # 完全匹配
    if candidate_norm == target_norm:
        return 1.0
    
    # 检查是否互相包含
    is_contained = target_norm in candidate_norm or candidate_norm in target_norm
    
    if is_contained:
        # 提取数字部分
        candidate_num = extract_channel_number(candidate_norm)
        target_num = extract_channel_number(target_norm)
        
        # 如果都有数字，必须数字一致才算高匹配
        if candidate_num and target_num:
            if candidate_num == target_num:
                return 0.9
            else:
                # 数字不同，降低匹配度（如CCTV1和CCTV17）
                return 0.3
        elif candidate_num or target_num:
            # 一个有数字一个没数字，可能是不同频道
            return 0.3
        else:
            # 都没有数字，纯文字包含
            return 0.8
    
    return 0.0


async def auto_match_channels(db: AsyncSession) -> dict:
    result = await db.execute(
        select(Stream).where(Stream.channel_id == None)
    )
    unmatched_streams = result.scalars().all()

    result = await db.execute(select(Channel))
    all_channels = result.scalars().all()

    if not unmatched_streams or not all_channels:
        return {
            "matched_streams": 0,
            "matched_channels": 0,
            "unmatched": len(unmatched_streams)
        }

    # 预归一化频道名与别名，构建倒排索引（归一化名 -> channel 列表）
    # 消除 O(流 × 频道 × 别名) 的暴力正则匹配
    name_index: dict[str, list] = {}
    channel_norms: list[tuple] = []  # (channel, norm_name, norm_aliases, num)

    for channel in all_channels:
        norm_name = normalize_channel_name(channel.standard_name)
        norm_aliases = [normalize_channel_name(a) for a in (channel.aliases or []) if a]
        channel_num = extract_channel_number(norm_name)
        channel_norms.append((channel, norm_name, norm_aliases, channel_num))

        for key in [norm_name] + norm_aliases:
            if key:
                name_index.setdefault(key, []).append(channel)

    matched_streams = 0
    matched_channels = set()
    remaining_streams = []

    # 第一轮：倒排索引精确匹配（O(1) 查找）
    for stream in unmatched_streams:
        if not stream.url:
            continue

        stream_name = stream.name if stream.name else stream.url.split('/')[-1].split('.')[0]
        stream_norm = normalize_channel_name(stream_name)
        stream_num = extract_channel_number(stream_norm)

        candidates = name_index.get(stream_norm)
        if candidates:
            # 精确匹配到唯一频道，直接绑定
            if len(candidates) == 1:
                stream.channel_id = candidates[0].id
                matched_streams += 1
                matched_channels.add(candidates[0].id)
                continue
            # 多个候选时，选数字部分一致的
            best = next(
                (c for c in candidates
                 if extract_channel_number(normalize_channel_name(c.standard_name)) == stream_num),
                candidates[0]
            )
            stream.channel_id = best.id
            matched_streams += 1
            matched_channels.add(best.id)
            continue

        remaining_streams.append((stream, stream_name))

    # 第二轮：仅对未精确命中的流做模糊匹配（数量通常很少）
    for stream, stream_name in remaining_streams:
        stream_norm = normalize_channel_name(stream_name)
        stream_num = extract_channel_number(stream_norm)

        best_match = None
        best_score = 0.0

        for channel, norm_name, norm_aliases, channel_num in channel_norms:
            score = fuzzy_match_score(channel.standard_name, stream_name)
            if score > best_score:
                best_score = score
                best_match = channel

            for alias, alias_norm in zip(channel.aliases or [], norm_aliases):
                alias_score = fuzzy_match_score(alias, stream_name)
                if alias_score > best_score:
                    best_score = alias_score
                    best_match = channel

        # 只有匹配度足够高（>= 0.8）才自动匹配，否则保持未匹配状态
        if best_match and best_score >= 0.8:
            stream.channel_id = best_match.id
            matched_streams += 1
            matched_channels.add(best_match.id)

    await db.commit()

    unique_channels = len(matched_channels)
    return {
        "matched_streams": matched_streams,
        "matched_channels": unique_channels,
        "unmatched": len(unmatched_streams) - matched_streams
    }


async def bind_stream_to_channel(db: AsyncSession, stream_id: str, channel_id: int | None) -> bool:
    """手动绑定或解绑直播流到频道"""
    result = await db.execute(
        select(Stream).where(Stream.id == stream_id)
    )
    stream = result.scalar_one_or_none()
    
    if not stream:
        return False
    
    stream.channel_id = channel_id
    await db.commit()
    return True


async def batch_bind_streams(db: AsyncSession, stream_ids: list[str], channel_id: int | None) -> dict:
    """批量绑定或解绑直播流到频道（单条 UPDATE，消除逐条 SELECT 的 N+1）"""
    if not stream_ids:
        return {"success": 0, "failed": 0}

    result = await db.execute(
        update(Stream)
        .where(Stream.id.in_(stream_ids))
        .values(channel_id=channel_id)
    )
    await db.commit()

    success_count = result.rowcount or 0
    failed_count = len(stream_ids) - success_count

    return {
        "success": success_count,
        "failed": failed_count
    }


async def create_channel_and_bind(db: AsyncSession, stream_ids: list[str], channel_name: str) -> dict:
    """创建新频道并绑定直播流"""
    # 创建新频道
    result = await db.execute(
        select(Channel).where(Channel.standard_name == channel_name)
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        channel_id = existing.id
    else:
        # 获取最大order_index
        result = await db.execute(select(Channel).order_by(Channel.order_index.desc()).limit(1))
        last_channel = result.scalar_one_or_none()
        new_order = (last_channel.order_index + 1) if last_channel else 1
        
        channel = Channel(
            standard_name=channel_name,
            aliases=[],
            order_index=new_order
        )
        db.add(channel)
        await db.flush()
        channel_id = channel.id
    
    # 绑定直播流
    bind_result = await batch_bind_streams(db, stream_ids, channel_id)
    
    return {
        "channel_id": channel_id,
        "channel_name": channel_name,
        **bind_result
    }
