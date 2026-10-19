import asyncio
import logging

log = logging.getLogger(__name__)


async def supervise(desk, name, operation):
    """Expose worker failures and retry without stopping the console."""
    while True:
        try:
            await operation()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            desk.errors[name] = type(exc).__name__
            log.warning("%s worker failed (%s); retrying", name, type(exc).__name__)
            await asyncio.sleep(3)


async def simulate(desk, publish):
    while True:
        events = await asyncio.to_thread(desk.generate)
        for event in events:
            await publish(event)
        await asyncio.sleep(1)


async def watch(desk):
    while True:
        await asyncio.to_thread(desk.watchdog)
        desk.errors.pop("watchdog", None)
        await asyncio.sleep(1)


async def triage_pending(desk):
    while True:
        await asyncio.to_thread(desk.triage_next)
        desk.errors.pop("triage", None)
        await asyncio.sleep(2)
