"""Local preview of the Daybook panel with a fake Home Assistant.

Runs the real store, settings and insights code against a temporary database
seeded with sample data. Not part of the integration.
"""
import json, random, sys, tempfile, time
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from custom_components.daybook import insights  # noqa: E402
from custom_components.daybook.settings import validate  # noqa: E402
from custom_components.daybook.store import DaybookStore  # noqa: E402
from custom_components.daybook.substances import DISCLAIMER, PROFILES  # noqa: E402

TZ = datetime.now().astimezone().tzinfo
store = DaybookStore(str(Path(tempfile.mkdtemp()) / "preview.db"))
store.open()
settings = validate({
    "meds": [{"id": "elvanse", "name": "Elvanse", "dose": 30, "unit": "mg", "profile": "lisdexamfetamine", "color": "#d4537e"}],
    "sport_zones": [
        {"id": "water_polo", "zone": "zone.pool", "person": "person.alex", "activity": "Water polo", "min_minutes": 60,
         "windows": [{"weekdays": [1, 4], "from": "19:30", "to": "21:30"}, {"weekdays": [2], "from": "19:30", "to": "22:00"}]},
        {"id": "rowing", "zone": "zone.rowing_club", "person": "person.alex", "activity": "Rowing", "min_minutes": 60,
         "windows": [{"weekdays": [1, 4], "from": "06:45", "to": "08:30"}, {"weekdays": [5, 6], "from": "10:00", "to": "12:00"}]},
    ],
})


def seed():
    rnd = random.Random(7)
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    for back in range(28, -1, -1):
        day = today - timedelta(days=back)
        wd = day.weekday()
        at = lambda h: (day + timedelta(hours=h)).timestamp()  # noqa: E731
        now = time.time()
        wake = 7.4 + rnd.random() * 0.8 + (1.4 if wd >= 5 else 0)
        took = wd < 5 and rnd.random() > 0.15
        if took:
            store.add({"kind": "med", "item": "elvanse", "start": at(wake + 0.3), "value": {"status": "taken", "dose": 30, "unit": "mg"}, "source": "button"})
        elif wd < 5 or rnd.random() > 0.5:
            store.add({"kind": "med", "item": "elvanse", "start": at(wake + 0.5), "value": {"status": "skipped"}, "source": "panel"})
        coffees = [wake + 0.5, 13 + rnd.random()] + ([15.5 + rnd.random()] if rnd.random() > 0.5 else [])
        for c in coffees:
            if at(c) < now:
                store.add({"kind": "caffeine", "item": "coffee", "start": at(c), "value": {"mg": 90}, "source": "corridor_box"})
        late_coffee = len(coffees) > 2
        for h in sorted(rnd.sample([9.5, 10.5, 11.5, 13.5, 14.5, 16, 17.5, 19, 21, 22.5], 5)):
            if at(h) >= now:
                continue
            if took and 9 < h < 15:
                st = rnd.choice(["productive"] * 4 + ["creative", "overstimulated"])
                if late_coffee and h > 13: st = rnd.choice(["overstimulated", "overstimulated", "productive"])
            elif took and h >= 15:
                st = rnd.choice(["productive", "tired", "creative", "overstimulated" if late_coffee else "tired"])
            else:
                st = rnd.choice(["lazy", "tired", "creative", "tired", "lazy", "productive"])
            if h > 20: st = rnd.choice(["tired", "lazy", "creative"])
            store.add({"kind": "state", "item": st, "start": at(h + rnd.random() * 0.4), "source": "corridor_box"})
        if wd in (1, 4) and at(21.5) < now:
            store.add({"kind": "sport", "item": "Rowing", "start": at(6.75), "end": at(8.4), "source": "zone:rowing"})
            store.add({"kind": "sport", "item": "Water polo", "start": at(19.4), "end": at(21.6), "source": "zone:water_polo",
                       "status": "draft" if back == 0 else "confirmed"})
        bed = 23.3 + rnd.random() * 1.2 + (0.6 if late_coffee else 0)
        if back > 0:
            store.add({"kind": "sleep", "start": at(bed), "end": at(24 + wake + 0.0), "source": "sleep_as_android"})


seed()
STATES = {
    "zone.home": {"attributes": {"friendly_name": "Home"}},
    "zone.pool": {"attributes": {"friendly_name": "Pool"}},
    "zone.rowing_club": {"attributes": {"friendly_name": "Rowing club"}},
    "person.alex": {"attributes": {"friendly_name": "Alex"}},
    "schedule.training": {"attributes": {"friendly_name": "Training"}},
}


def handle(msg):
    global settings
    t = msg["type"]
    if t == "daybook/settings/get":
        return {"settings": settings, "time_zone": "Europe/Amsterdam"}
    if t == "daybook/settings/set":
        settings = validate(msg["settings"])
        return {"settings": settings}
    if t == "daybook/substances":
        return {"profiles": PROFILES, "disclaimer": DISCLAIMER}
    if t == "daybook/entries/list":
        return store.list(msg.get("start"), msg.get("end"))
    if t == "daybook/entries/create":
        e = {k: msg[k] for k in ("kind", "item", "start", "end", "value", "status", "note") if k in msg}
        e.setdefault("start", time.time())
        e["source"] = "panel"
        if e["kind"] == "caffeine" and "mg" not in (e.get("value") or {}):
            e["value"] = {**(e.get("value") or {}), "mg": next(d["mg"] for d in settings["drinks"] if d["id"] == e["item"])}
        return store.add(e)
    if t == "daybook/entries/update":
        return store.update(msg["entry_id"], {k: msg[k] for k in ("item", "start", "end", "value", "status", "note") if k in msg})
    if t == "daybook/entries/delete":
        return store.delete(msg["entry_id"])
    if t == "daybook/entries/restore":
        return store.restore(msg["entry_id"])
    if t == "daybook/insights":
        end = time.time()
        return insights.compute(store.list(end - msg.get("days", 56) * 86400 - 86400, end), settings, TZ)
    raise ValueError(f"unknown {t}")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/dev/index.html"
        elif self.path == "/hass-states.json":
            body = json.dumps(STATES).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body); return
        return super().do_GET()

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            body, code = json.dumps(handle(msg)).encode(), 200
        except Exception as err:  # noqa: BLE001
            body, code = json.dumps({"message": str(err)}).encode(), 400
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"Preview on http://localhost:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
