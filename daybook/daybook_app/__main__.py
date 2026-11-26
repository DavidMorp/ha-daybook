"""Start Daybook.

Inside Home Assistant (SUPERVISOR_TOKEN is set) it stores data in /data,
connects to Home Assistant and to the MQTT broker the Supervisor provides,
and serves the panel on the ingress port.

For development, set DAYBOOK_DEV=1 and optionally DAYBOOK_DATA and
DAYBOOK_PORT; it then runs on 127.0.0.1 without Home Assistant.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from pathlib import Path

import aiohttp
from aiohttp import web

from .core import Journal
from .ha import HomeAssistantLink
from .mqtt_link import MqttLink
from .server import create_app
from .sport import SportTracker

_LOGGER = logging.getLogger("daybook")
SUPERVISOR = "http://supervisor"


def _options(data_dir: Path) -> dict:
    try:
        return json.loads((data_dir / "options.json").read_text())
    except (OSError, ValueError):
        return {}


async def _mqtt_credentials(token: str) -> dict | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{SUPERVISOR}/services/mqtt", headers={"Authorization": f"Bearer {token}"}) as resp:
                if resp.status != 200:
                    return None
                body = await resp.json()
                return body.get("data") or None
    except aiohttp.ClientError:
        return None


async def main() -> None:
    dev = os.environ.get("DAYBOOK_DEV") == "1"
    token = os.environ.get("SUPERVISOR_TOKEN")
    data_dir = Path(os.environ.get("DAYBOOK_DATA", "/data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    options = _options(data_dir)
    logging.basicConfig(
        level=getattr(logging, str(options.get("log_level", "info")).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    journal = Journal(data_dir, os.environ.get("TZ"))
    await journal.start()

    ha = mqtt = sport = None
    if token and not dev:
        ha = HomeAssistantLink("ws://supervisor/core/websocket", token)

        async def use_ha_time_zone() -> None:
            journal.set_time_zone(ha.config.get("time_zone"))
        ha.on_connect.append(use_ha_time_zone)
        ha.start()
        sport = SportTracker(journal, ha)
        await sport.start()

        creds = await _mqtt_credentials(token)
        if creds:
            mqtt = MqttLink(journal, creds["host"], int(creds.get("port", 1883)),
                            creds.get("username"), creds.get("password"), ha=ha)
            await mqtt.start()
        else:
            _LOGGER.warning("No MQTT broker found. Install the Mosquitto broker app to log from automations and buttons.")

    app = create_app(journal, ha, mqtt, allowed_ips=None if dev else {"172.30.32.2"})
    runner = web.AppRunner(app)
    await runner.setup()
    host = "127.0.0.1" if dev else "0.0.0.0"
    port = int(os.environ.get("DAYBOOK_PORT", "8099"))
    await web.TCPSite(runner, host, port).start()
    _LOGGER.info("Daybook is running on %s:%s", host, port)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    if mqtt:
        await mqtt.stop()
    if ha:
        await ha.stop()
    await runner.cleanup()
    await journal.stop()


if __name__ == "__main__":
    asyncio.run(main())
