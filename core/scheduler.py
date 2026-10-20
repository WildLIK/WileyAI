import asyncio
from .storage import Store


async def run_scheduler(store: Store, background=None):
    while True:
        await asyncio.to_thread(store.queue_due_notifications)
        if background is not None:
            await asyncio.to_thread(background.tick)
        await asyncio.sleep(5)
