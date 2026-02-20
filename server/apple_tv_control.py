from __future__ import annotations

import pyatv
from pyatv.interface import AppleTV, BaseConfig
from pyatv.storage.file_storage import FileStorage

from server import config

import structlog

log = structlog.get_logger()


async def scan_devices(identifier: str | None = None) -> list[BaseConfig]:
    if identifier:
        return await pyatv.scan(identifier=identifier)
    return await pyatv.scan()


async def connect(identifier: str | None = None) -> AppleTV:
    device_id = identifier or config.APPLE_TV_ID
    devices = await scan_devices(device_id)
    if not devices:
        raise ConnectionError(f"Apple TV not found: {device_id}")

    storage = FileStorage(config.PYATV_CONF)
    await storage.load()
    return await pyatv.connect(devices[0], storage=storage)


async def launch(bundle_id: str, deep_link: str | None = None) -> str:
    atv = await connect()
    try:
        if deep_link:
            await atv.apps.launch_app(bundle_id, url=deep_link)
            return "deep_link"
        await atv.apps.launch_app(bundle_id)
        return "app_launch"
    finally:
        atv.close()


async def check_connectivity() -> bool:
    try:
        atv = await connect()
        atv.close()
        return True
    except Exception as e:
        log.warning("connectivity_check_failed", error=str(e))
        return False


async def pair_device(identifier: str, pin: str | None = None) -> dict:
    devices = await scan_devices(identifier)
    if not devices:
        raise ConnectionError(f"Device not found: {identifier}")

    storage = FileStorage(config.PYATV_CONF)
    await storage.load()
    pairing = await pyatv.pair(devices[0], protocol=pyatv.Protocol.Companion, storage=storage)

    await pairing.begin()

    if pin is not None:
        pairing.pin(int(pin))
        await pairing.finish()
        if pairing.has_paired:
            await storage.save()
            return {"status": "paired", "message": "Successfully paired"}
        return {"status": "failed", "message": "Pairing failed"}

    return {"status": "awaiting_pin", "message": "Enter PIN shown on Apple TV"}
