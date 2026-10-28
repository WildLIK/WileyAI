import asyncio
import logging
import time
from .storage import Store

PRUNE_EVERY = 3600


async def run_scheduler(store: Store, background=None, *, interval=5):
    pruned = None
    while True:
        # One failed tick (locked database, bad row) must not stop reminders for the session.
        try:
            await asyncio.to_thread(store.queue_due_notifications)
            if pruned is None or time.monotonic() - pruned >= PRUNE_EVERY:
                await asyncio.to_thread(store.prune_delivered)
                pruned = time.monotonic()
        except Exception:
            logging.getLogger(__name__).exception("Cannot queue due notifications")
        if background is not None:
            try:
                await asyncio.to_thread(background.tick)
            except Exception:
                logging.getLogger(__name__).exception("Cannot run background tasks")
        await asyncio.sleep(interval)
