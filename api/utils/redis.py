import asyncio
from contextlib import asynccontextmanager

import aioredis

from api import settings


@asynccontextmanager
async def wait_for_redis():  # pragma: no cover
    while not settings.redis_pool:
        await asyncio.sleep(0.01)
    yield


async def make_subscriber(name):
    subscriber = await aioredis.create_redis_pool(settings.REDIS_HOST)
    res = await subscriber.subscribe(f"channel:{name}")
    channel = res[0]
    return subscriber, channel


async def publish_message(channel, message):
    async with wait_for_redis():
        return await settings.redis_pool.publish_json(f"channel:{channel}", message)
