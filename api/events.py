"""Event system for gunicorn workers/background worker communication via redis pub/sub."""

import asyncio

from pydantic import ValidationError

from api import constants, utils


class EventHandler:
    def __init__(self, events=None):
        self.events = events or {}

    def add_event(self, name, event):
        self.events[name] = event

    def add_handler(self, event, handler):
        if event not in self.events:
            return False
        self.events[event]["handlers"].append(handler)
        return True

    def on(self, event):
        def wrapper(func):
            self.add_handler(event, func)
            return func

        return wrapper

    async def process(self, message):
        event = message.event
        data = message.data
        if event not in self.events:
            return
        event_data = self.events[event]
        if not isinstance(data, dict) or data.keys() != event_data["params"]:
            return
        coros = (handler(event, data) for handler in event_data["handlers"])
        await asyncio.gather(*coros, return_exceptions=False)

    async def publish(self, name, data):
        await send_message({"event": name, "data": data})


async def process_message(message, custom_event_handler=None):
    from api import schemes

    try:
        message = schemes.EventSystemMessage(**message)
    except (TypeError, ValidationError):
        return
    custom_event_handler = custom_event_handler or event_handler
    await custom_event_handler.process(message)


async def send_message(message):
    await utils.redis.publish_message(constants.EVENTS_CHANNEL, message)


async def listen(channel, custom_event_handler=None):  # pragma: no cover
    while await channel.wait_message():
        msg = await channel.get_json()
        asyncio.ensure_future(process_message(msg, custom_event_handler))


async def start_listening(custom_event_handler=None):  # pragma: no cover
    _, channel = await utils.redis.make_subscriber(constants.EVENTS_CHANNEL)
    await listen(channel, custom_event_handler)


event_handler = EventHandler(
    events={
        "expired_task": {
            "params": {"id"},
            "handlers": [],
        },
        "sync_wallet": {
            "params": {"id"},
            "handlers": [],
        },
        "deploy_task": {
            "params": {"id"},
            "handlers": [],
        },
    }
)
