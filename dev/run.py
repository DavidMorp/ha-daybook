"""Run the Daybook app locally with sample data and a fake Home Assistant.

    .venv/bin/python dev/run.py [port]

Uses the real app server, store and statistics. Data lives in a temporary
folder and is thrown away.
"""
import asyncio
import random
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "daybook"))
from aiohttp import web  # noqa: E402

from daybook_app.core import Journal  # noqa: E402
from daybook_app.server import create_app  # noqa: E402


class FakeHA:
    connected = True
    notify_services = ["mobile_app_phone"]
    states = {
        "zone.home": {"state": "0", "attributes": {"friendly_name": "Home"}},
        "zone.pool": {"state": "0", "attributes": {"friendly_name": "Pool"}},
        "zone.rowing_club": {"state": "0", "attributes": {"friendly_name": "Rowing club"}},
        "person.alex": {"state": "home", "attributes": {"friendly_name": "Alex"}},
        "schedule.training": {"state": "off", "attributes": {"friendly_name": "Training"}},
    }

    def friendly_name(self, entity_id):
        return self.states.get(entity_id, {}).get("attributes", {}).get("friendly_name", entity_id)


SETTINGS = {
    "items": [
        {"id": "coffee", "name": "Coffee", "profile": "caffeine", "amount": 90, "unit": "mg"},
        {"id": "espresso", "name": "Espresso", "profile": "caffeine", "amount": 65, "unit": "mg"},
        {"id": "elvanse", "name": "Elvanse", "profile": "lisdexamfetamine", "amount": 30, "unit": "mg"},
    ],
    "substances": {
        "caffeine": {"color": "#eda100"},
        "lisdexamfetamine": {"color": "#d4537e", "label": "Elvanse"},
    },
    "comparisons": [
        {"id": "elvanse_coffee", "name": "Elvanse today, coffee 1–4 h ago",
         "conditions": [{"profile": "lisdexamfetamine", "present": True, "from_h": 0, "to_h": 12},
                        {"profile": "caffeine", "present": True, "from_h": 1, "to_h": 4}]},
        {"id": "elvanse_only", "name": "Elvanse today, no coffee in 4 h",
         "conditions": [{"profile": "lisdexamfetamine", "present": True, "from_h": 0, "to_h": 12},
                        {"profile": "caffeine", "present": False, "from_h": 0, "to_h": 4}]},
        {"id": "coffee_only", "name": "Coffee 1–4 h ago, no Elvanse",
         "conditions": [{"profile": "lisdexamfetamine", "present": False, "from_h": 0, "to_h": 12},
                        {"profile": "caffeine", "present": True, "from_h": 1, "to_h": 4}]},
    ],
    "sport_zones": [
        {"id": "pool", "zone": "zone.pool", "person": "person.alex", "activity": "Water polo", "min_minutes": 60,
         "windows": [{"weekdays": [1, 4], "from": "19:30", "to": "21:30"}]},
    ],
}


async def seed(j: Journal) -> None:
    await j.set_settings(SETTINGS)
    rnd = random.Random(7)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    now = time.time()

    async def add(e):
        if e["start"] < now and (e.get("end") is None or e["end"] < now):
            await j.add(e)

    for back in range(28, -1, -1):
        day = today - timedelta(days=back)
        wd = day.weekday()

        def at(h, day=day):
            return (day + timedelta(hours=h)).timestamp()

        wake = 7.4 + rnd.random() * 0.8 + (1.4 if wd >= 5 else 0)
        took = wd < 5 and rnd.random() > 0.15
        if took:
            await add({"kind": "intake", "item": "elvanse", "start": at(wake + 0.3), "source": "button"})
        coffees = [wake + 0.5, 13 + rnd.random()] + ([15.5 + rnd.random()] if rnd.random() > 0.5 else [])
        for c in coffees:
            await add({"kind": "intake", "item": rnd.choice(["coffee", "coffee", "espresso"]), "start": at(c), "source": "box"})
        late = len(coffees) > 2
        for h in sorted(rnd.sample([9.5, 10.5, 11.5, 13.5, 14.5, 16, 17.5, 19, 21, 22.5], 5)):
            if took and 9 < h < 15:
                st = rnd.choice(["productive"] * 4 + ["creative", "overstimulated"])
                if late and h > 13:
                    st = rnd.choice(["overstimulated", "overstimulated", "productive"])
            elif took:
                st = rnd.choice(["productive", "tired", "creative", "overstimulated" if late else "tired"])
            else:
                st = rnd.choice(["lazy", "tired", "creative", "tired", "lazy", "productive"])
            if h > 20:
                st = rnd.choice(["tired", "lazy", "creative"])
            await add({"kind": "state", "item": st, "start": at(h + rnd.random() * 0.4), "source": "box"})
        if wd in (1, 4):
            await add({"kind": "sport", "item": "Water polo", "start": at(19.4), "end": at(21.6),
                       "status": "draft" if back <= 1 else "confirmed", "source": "zone:pool"})
        bed = 23.2 + rnd.random() * 1.0 + (0.7 if late else 0)
        await add({"kind": "sleep", "start": at(bed), "end": at(24 + 7.3 + rnd.random() - (0.6 if late else 0)), "source": "manual"})


async def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    j = Journal(tempfile.mkdtemp())
    await j.start()
    await seed(j)
    runner = web.AppRunner(create_app(j, FakeHA(), None))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    print(f"Daybook dev server on http://localhost:{port}", flush=True)
    await asyncio.Event().wait()


asyncio.run(main())
