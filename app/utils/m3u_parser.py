import re
import logging
import m3u8
from typing import Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    url = url.split('?')[0]
    url = url.split('#')[0]
    return url.strip()


def generate_url_hash(url: str, name: str = "") -> str:
    import hashlib
    # v0.2.1: 唯一标识仅与流地址本身相关，不再包含频道名称
    normalized = normalize_url(url)
    return hashlib.sha256(normalized.encode()).hexdigest()


def parse_m3u_content(m3u_content: str, base_url: str = "") -> list[dict]:
    segments = []
    try:
        playlist = m3u8.loads(m3u_content)
        for segment in playlist.segments:
            url = segment.uri
            if base_url and not url.startswith('http'):
                url = urljoin(base_url, url)
            
            attrs = segment.attributes or {}
            name = attrs.get('title', '') or segment.title or ""
            
            tvg_name = attrs.get('name', '')
            group_title = attrs.get('group_title', '')
            tvg_id = attrs.get('tvg_id', '')
            logo = attrs.get('tvg_logo', '')
            
            if not name and group_title:
                name = group_title
            if not name and tvg_name:
                name = tvg_name
            
            segments.append({
                'url': url,
                'name': name,
                'tvg_id': tvg_id,
                'group_title': group_title,
                'logo': logo,
                'url_hash': generate_url_hash(url, name),
            })
    except (ValueError, AttributeError, KeyError) as e:
        logger.debug(f"Failed to parse m3u with m3u8 library, falling back to manual parsing: {e}")
        lines = m3u_content.split('\n')
        current_info = {}
        
        for i, line in enumerate(lines):
            line = line.strip()
            if line.startswith('#EXTINF:'):
                # 移除 #EXTINF: 前缀
                line_without_prefix = line.replace('#EXTINF:', '', 1)
                
                # 按逗号分割，第一部分是duration，剩余部分是属性和名称
                parts = line_without_prefix.split(',', 1)
                duration = parts[0] if parts else ""
                
                current_info = {
                    'duration': duration,
                    'name': '',  # 初始化为空，稍后提取
                }
                
                if len(parts) > 1:
                    remaining = parts[1]
                    
                    # 提取所有属性
                    attr_match = re.search(r'([a-z_-]+)="([^"]*)"', remaining)
                    while attr_match:
                        key = attr_match.group(1)
                        value = attr_match.group(2)
                        # 将连字符转换为下划线，以便统一访问
                        normalized_key = key.replace('-', '_')
                        current_info[normalized_key] = value
                        remaining = remaining[attr_match.end():]
                        attr_match = re.search(r'([a-z_-]+)="([^"]*)"', remaining)
                    
                    # 移除所有属性后，剩余部分就是频道名称
                    # 首先移除所有属性（包括引号内的内容）
                    name_part = re.sub(r'[a-z_-]+="[^"]*"\s*', '', remaining).strip()
                    # 如果还有逗号，按最后一个逗号分割
                    if ',' in name_part:
                        name_part = name_part.split(',')[-1].strip()
                    
                    current_info['name'] = name_part if name_part else remaining.strip()
            elif line and not line.startswith('#'):
                url = line if line.startswith('http') else urljoin(base_url, line)
                segments.append({
                    'url': url,
                    'name': current_info.get('name', ''),
                    'tvg_id': current_info.get('tvg_id', ''),
                    'group_title': current_info.get('group_title', ''),
                    'logo': current_info.get('tvg_logo', ''),
                    'url_hash': generate_url_hash(url, current_info.get('name', '')),
                })
                current_info = {}
    
    return segments


def parse_m3u_from_url(m3u_url: str, content: str) -> list[dict]:
    base_url = m3u_url.rsplit('/', 1)[0] + '/'
    return parse_m3u_content(content, base_url)
