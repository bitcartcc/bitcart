import notifiers
from aiohttp import ClientSession

from api import models, utils


async def send_ipn(obj, status):  # pragma: no cover
    if obj.notification_url:
        data = {"id": obj.id, "status": status}
        try:
            async with ClientSession() as session:
                await session.post(obj.notification_url, json=data)
        except Exception:
            pass


async def notify(store, text):  # pragma: no cover
    notification_providers = await utils.database.get_objects(models.Notification, store.notifications)
    for provider in notification_providers:
        notifiers.notify(provider.provider, message=text, **provider.data)
