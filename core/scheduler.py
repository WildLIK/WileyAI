import asyncio
from .storage import Store


async def run_scheduler(store: Store):
    while True:
        await asyncio.to_thread(store.queue_due_notifications)
        await asyncio.sleep(5)
