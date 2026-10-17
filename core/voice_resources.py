"""Release resident speech models on idle; never loads models or calls providers."""
import asyncio
import logging


def idle_seconds(settings):
    policy = settings.voice_idle_timeout
    if policy == "never":
        return None
    if policy == "profile":
        return {"eco": 60, "balanced": 300, "quality": 900}[settings.profile]
    return {"1m": 60, "5m": 300, "15m": 900}[policy]


async def release_idle(store, voice):
    if not (voice.models or voice.tts_model is not None or voice.piper.model is not None):
        return []
    timeout = idle_seconds(await asyncio.to_thread(store.settings))
    if timeout is None:
        return []
    released = await voice.unload(idle_seconds=timeout)
    if released:
        await asyncio.to_thread(store.audit, "voice.idle_unload", ", ".join(released), "unloaded")
    return released


async def run_idle_resources(store, voice, *, interval=15):
    while True:
        await asyncio.sleep(interval)
        try:
            await release_idle(store, voice)
        except Exception:
            logging.getLogger(__name__).exception("Cannot release idle speech models")
