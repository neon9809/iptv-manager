import redis.asyncio as redis
from app.core.config import get_settings
from typing import Optional

settings = get_settings()


class RedisClient:
    def __init__(self):
        pass

    async def get_client(self) -> redis.Redis:
        return redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )

    async def close_client(self, client: redis.Redis):
        if client:
            await client.close()

    async def get(self, key: str) -> Optional[str]:
        client = await self.get_client()
        try:
            return await client.get(key)
        finally:
            await self.close_client(client)

    async def set(self, key: str, value: str, ex: Optional[int] = None):
        client = await self.get_client()
        try:
            return await client.set(key, value, ex=ex)
        finally:
            await self.close_client(client)

    async def delete(self, key: str):
        client = await self.get_client()
        try:
            return await client.delete(key)
        finally:
            await self.close_client(client)

    async def exists(self, key: str) -> bool:
        client = await self.get_client()
        try:
            return await client.exists(key) > 0
        finally:
            await self.close_client(client)

    async def incr(self, key: str) -> int:
        client = await self.get_client()
        try:
            return await client.incr(key)
        finally:
            await self.close_client(client)

    async def expire(self, key: str, seconds: int):
        client = await self.get_client()
        try:
            return await client.expire(key, seconds)
        finally:
            await self.close_client(client)

    async def hset(self, name: str, key: str = None, value: str = None, mapping: dict = None):
        client = await self.get_client()
        try:
            return await client.hset(name, key, value, mapping=mapping)
        finally:
            await self.close_client(client)

    async def hgetall(self, name: str) -> dict:
        client = await self.get_client()
        try:
            return await client.hgetall(name)
        finally:
            await self.close_client(client)

    async def hdel(self, name: str, *keys):
        client = await self.get_client()
        try:
            return await client.hdel(name, *keys)
        finally:
            await self.close_client(client)

    async def setnx(self, key: str, value: str) -> bool:
        client = await self.get_client()
        try:
            return await client.setnx(key, value)
        finally:
            await self.close_client(client)

    async def sadd(self, name: str, *values):
        client = await self.get_client()
        try:
            return await client.sadd(name, *values)
        finally:
            await self.close_client(client)

    async def spop(self, name: str, count: int = 1):
        client = await self.get_client()
        try:
            result = await client.spop(name, count)
            if result and len(result) > 0:
                return result[0]
            return None
        finally:
            await self.close_client(client)


redis_client = RedisClient()
