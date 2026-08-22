import redis.asyncio as redis
from app.core.config import get_settings
from typing import Optional

settings = get_settings()

# 全局连接池单例：redis.asyncio.Redis 自带连接池，
# 全进程只创建一次，避免每次操作都付出 TCP+握手成本（P6）
_client: Optional[redis.Redis] = None


def _get_shared_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )
    return _client


class RedisClient:
    """共享连接池的 Redis 客户端封装。

    get_client() 返回全局单例客户端（内部持有连接池）。
    close_client() 保留兼容旧调用点，但不再真正关闭共享客户端；
    进程退出时可通过 aclose() 显式关闭。
    """

    async def get_client(self) -> redis.Redis:
        return _get_shared_client()

    async def close_client(self, client: redis.Redis):
        # 共享池客户端不随单次操作关闭；保留空实现以兼容既有调用
        return

    async def aclose(self):
        """进程退出时关闭共享连接池"""
        global _client
        if _client is not None:
            await _client.aclose()
            _client = None

    async def get(self, key: str) -> Optional[str]:
        client = await self.get_client()
        return await client.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None):
        client = await self.get_client()
        return await client.set(key, value, ex=ex)

    async def delete(self, key: str):
        client = await self.get_client()
        return await client.delete(key)

    async def exists(self, key: str) -> bool:
        client = await self.get_client()
        return await client.exists(key) > 0

    async def incr(self, key: str) -> int:
        client = await self.get_client()
        return await client.incr(key)

    async def expire(self, key: str, seconds: int):
        client = await self.get_client()
        return await client.expire(key, seconds)

    async def hset(self, name: str, key: str = None, value: str = None, mapping: dict = None):
        client = await self.get_client()
        return await client.hset(name, key, value, mapping=mapping)

    async def hgetall(self, name: str) -> dict:
        client = await self.get_client()
        return await client.hgetall(name)

    async def hdel(self, name: str, *keys):
        client = await self.get_client()
        return await client.hdel(name, *keys)

    async def setnx(self, key: str, value: str) -> bool:
        client = await self.get_client()
        return await client.setnx(key, value)

    async def sadd(self, name: str, *values):
        client = await self.get_client()
        return await client.sadd(name, *values)

    async def spop(self, name: str, count: int = 1):
        client = await self.get_client()
        result = await client.spop(name, count)
        if result and len(result) > 0:
            return result[0]
        return None


redis_client = RedisClient()
