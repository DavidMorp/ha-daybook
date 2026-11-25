# Daybook

A private journal for Home Assistant. Log meds, caffeine, how you feel and sport with one tap, a physical button or an automation. Fix anything afterwards, and see how they relate over days and weeks.

Daybook was built for tracking ADHD medication and caffeine, but it works for anything you take and anything you feel.

- **Fast to log.** Tap a button in the panel, press a button entity from a dashboard or phone widget, or call `daybook.log` from an automation or an ESPHome device. Every log can be undone or moved 15 minutes back from the toast.
- **Everything is editable.** Change the time, amount, dose or note of any entry, delete it, or restore it. Every change keeps the previous version.
- **Skipped is data.** A med can be recorded as taken or skipped on purpose; a day with neither is "not recorded", never a guess.
- **Your own states.** Instead of a 1–5 score you check in with states such as productive, creative, overstimulated, tired or lazy. Each is marked high or low energy.
- **Curves of what's in your body.** Caffeine and common ADHD meds are modelled from published averages (time to peak, half-life, release type), so the timeline shows roughly what was active when.
- **Compare days.** The week view puts days side by side, aligned by clock time, by med dose or by first coffee.
- **Patterns without AI.** Counts and shares only: your typical week, how you feel after coffee with and without meds, by hours since your dose, on days you took a med compared with days you skipped it, energy through the day, and caffeine at bedtime against sleep. Nothing is shown until there's enough data.
- **Sport from zones.** Stays in an HA zone during your training times (or an HA Schedule) become suggested sport entries you confirm in the panel or from a phone notification.
- **Private.** Everything stays in one SQLite file in your config folder. No cloud, no external requests, no analytics. The panel and its API are admin only.

## Install

Daybook isn't in the default HACS / Marketplace list yet.

1. In HACS (or the Marketplace), open the menu, choose **Custom repositories**, and add `https://github.com/DavidMorp/ha-daybook` as an **Integration**.
2. Install **Daybook** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → Daybook**.
4. Open **Daybook** in the sidebar, go to **Settings**, and add your meds, drinks and sport places.

Manual install: copy `custom_components/daybook` into your `config/custom_components` folder and restart.

## Logging from anywhere

Daybook creates button entities such as `button.daybook_log_coffee`, `button.daybook_log_feeling_tired`, and `button.daybook_log_<med>_taken` / `_skipped`. Use them on dashboards, phone widgets, NFC tags or voice assistants.

For more control, use the actions:

```yaml
# Coffee half an hour ago
action: daybook.log
data:
  kind: caffeine
  item: coffee
  offset_minutes: -30

# A med skipped on purpose
action: daybook.log
data:
  kind: med
  item: elvanse
  skipped: true

# A check-in from a physical button, so it can be undone with a long press
action: daybook.log
data:
  kind: state
  item: overstimulated
  source: corridor_box
```

| Action | What it does |
|---|---|
| `daybook.log` | Adds an entry. Returns its `id`. |
| `daybook.update` | Changes an entry by `id`. |
| `daybook.delete` | Deletes an entry (it can be restored in the panel). |
| `daybook.undo_last` | Deletes the newest entry, optionally only from one `source` and within N minutes. |

Each log fires a `daybook_logged` event with the entry's id, kind, item and source (no values), for example to flash a light.

### A button box for the hallway

[`examples/esphome/corridor-box.yaml`](examples/esphome/corridor-box.yaml) is an ESP32 with six buttons and LEDs: one per state, plus coffee. A short press logs and blinks its LED; a long press undoes the last press. Turn on **Allow the device to perform Home Assistant actions** for the device in the ESPHome integration.

## Substance profiles

| Profile | Examples | Time to peak | Half-life |
|---|---|---|---|
| Caffeine | Coffee, tea | ~45 min (setting) | ~5 h (setting) |
| Methylphenidate, immediate release | Ritalin, Medikinet | 1.5–2 h | 2–4 h |
| Methylphenidate 50:50 extended release | Ritalin LA, Medikinet retard | two peaks | 2–4 h |
| Methylphenidate OROS | Concerta | 6–10 h | ~3.5 h |
| Lisdexamfetamine | Elvanse, Vyvanse | ~4 h | ~10 h |
| Dexamfetamine, immediate release | Attentin | ~3 h | 7–12 h |
| Mixed amphetamine salts, extended release | Adderall XR | ~7 h | ~10 h |
| Guanfacine, extended release | Intuniv | ~5 h | ~17 h |
| Atomoxetine | Strattera | 1–2 h | ~5 h (much longer in slow metabolisers) |
| Custom | | you set it | you set it |

Each med can override its half-life and time to peak. Sources are listed in the panel and in [`substances.py`](custom_components/daybook/substances.py).

> These curves estimate how much is in your blood from population averages. They don't show how strong the effect is, effects usually end before the curve does, and your body may differ a lot. Daybook isn't medical advice: talk to your prescriber before changing how you take anything.

## Privacy

- Data lives only in `config/daybook.db`, which is included in Home Assistant backups. Encrypt your backups.
- The panel and the WebSocket API require an admin user.
- Entities expose only what they must: buttons (their state is the last press time) and an optional caffeine estimate sensor. Turn the sensor off in Settings if you don't want it in history or visible to voice assistants and other integrations.
- Sport notifications use neutral text. On Android, the companion app's local push delivers them over your own connection instead of Google's servers.
- Export everything as JSON or CSV from Settings at any time.

## Development

```bash
uv venv -p 3.14 .venv
uv pip install -p .venv -r requirements_test.txt
.venv/bin/python -m pytest
```

`dev/server.py` serves the panel with a fake Home Assistant and three weeks of sample data, using the real storage and statistics code:

```bash
.venv/bin/python dev/server.py 8765
```

## Roadmap

- Sleep from Sleep as Android and Health Connect
- Exercise sessions from Health Connect (Garmin and others)
- Small, local models that learn from your corrections (for example which zone stays were really sport)
- Simple personal experiments, such as alternating weeks with and without afternoon coffee
