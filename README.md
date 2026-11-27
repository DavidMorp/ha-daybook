# Daybook

A private journal app for Home Assistant. Log what you take and how you feel with one tap, a physical button or an automation. Fix anything afterwards, and see how they relate over days and weeks.

Daybook was built for tracking ADHD medication and caffeine, but it works for anything you take and anything you feel.

- **Fast to log.** Tap a button in the panel, press a button entity from a dashboard or phone widget, or publish an MQTT message from an automation or an ESPHome device. Every log can be undone or moved 15 minutes back.
- **Everything is editable.** Change the time, amount or note of any entry, delete it, or restore it. Every change keeps the previous version.
- **Records what happened, nothing more.** No schedules, reminders or "missed" doses.
- **Your own states.** Instead of a 1–5 score you check in with states such as productive, creative, overstimulated, tired or lazy, each marked high or low energy.
- **What you take, as substances.** Coffee, tea and meds are all things you take, grouped by the substance in them. Each substance starts from a profile (caffeine, methylphenidate, lisdexamfetamine…), so the timeline shows roughly how much was in your body, and when it was effectively gone.
- **Compare days.** The week view puts days side by side, lined up by time of day or by your first coffee or dose.
- **Patterns without AI.** Counts and shares only: your typical week, how you felt depending on what you'd had (lines you define yourself), by hours since your first intake, days with compared with days without, energy through the day, and sleep after more or less caffeine than usual. Nothing is shown until there's enough data.
- **Sport from zones.** Stays in an HA zone during your training times (or an HA Schedule) become suggested sport entries you confirm in the panel or from a phone notification.
- **Private.** Everything stays in one SQLite file inside the app. No cloud, no external requests, no analytics. The panel is admin only.

## Install

Daybook needs Home Assistant OS or a Supervised install, and the **Mosquitto broker** app for buttons and logging from automations.

1. Go to **Settings → Apps → Install app**, open the menu (top right), choose **Repositories**, and add `https://github.com/DavidMorp/ha-daybook`.
2. Find **Daybook** in the store, install it and start it.
3. Open **Daybook** in the sidebar, go to **Settings**, and add what you take and your sport places.

## Logging from anywhere

Daybook creates button entities through MQTT discovery, such as `button.daybook_took_coffee` and `button.daybook_state_tired`. Use them on dashboards, phone widgets, NFC tags or voice assistants.

For more control, publish to `daybook/log` from an automation or script:

```yaml
# Coffee half an hour ago
action: mqtt.publish
data:
  topic: daybook/log
  payload: '{"kind": "intake", "item": "coffee", "offset_minutes": -30}'

# A check-in from a physical button, so it can be undone with a long press
action: mqtt.publish
data:
  topic: daybook/log
  payload: '{"kind": "state", "item": "overstimulated", "source": "hallway_box"}'

# Undo the newest entry from that button (within 10 minutes)
action: mqtt.publish
data:
  topic: daybook/undo
  payload: '{"source": "hallway_box"}'
```

| Field | Meaning |
|---|---|
| `kind` | `state`, `intake`, `sport`, `sleep` or `note` |
| `item` | Id of the state or thing you take, from Settings, or the sport activity |
| `when` | ISO time, defaults to now; `offset_minutes` shifts it |
| `end` or `duration_minutes` | For sport and sleep |
| `amount` | Overrides the usual amount |
| `note`, `source` | Free text; `source` is what `daybook/undo` matches |

Each log fires a `daybook_logged` event in Home Assistant and publishes `daybook/logged`, with the entry's id, kind, item and source (no amounts or notes).

### A button box for the hallway

[`examples/esphome/corridor-box.yaml`](examples/esphome/corridor-box.yaml) is an ESP32 with six buttons and LEDs: one per state, plus coffee. A short press logs and blinks its LED; a long press undoes the last press.

## Substance profiles

| Profile | Examples | Time to peak | Half-life |
|---|---|---|---|
| Caffeine | Coffee, tea | ~45 min | ~5 h (1.5–9.5 h) |
| Methylphenidate, immediate release | Ritalin, Medikinet | 1.5–2 h | 2–4 h |
| Methylphenidate 50:50 extended release | Ritalin LA, Medikinet retard | two peaks | 2–4 h |
| Methylphenidate OROS | Concerta | 6–10 h | ~3.5 h |
| Lisdexamfetamine | Elvanse, Vyvanse | ~4 h | ~10 h |
| Dexamfetamine, immediate release | Attentin | ~3 h | 7–12 h |
| Mixed amphetamine salts, extended release | Adderall XR | ~7 h | ~10 h |
| Guanfacine, extended release | Intuniv | ~5 h | ~17 h |
| Atomoxetine | Strattera | 1–2 h | ~5 h (much longer in slow metabolisers) |
| Custom | | you set it | you set it |

You can override the half-life and time to peak for each substance. Elimination never quite reaches zero, so Daybook treats a substance as cleared once it's below 10% of one usual dose's peak (adjustable).

Being in your body isn't the same as having an effect. For stimulants, Daybook also knows the typical duration of action of one dose reported in labels and clinical reviews (for example about 1.5–13 h for lisdexamfetamine, 0.5–4 h for immediate-release methylphenidate). Curves are solid within it and dashed outside it. It says what studies found on average, not what you feel. Caffeine and non-stimulants have no default window; you can set your own for any substance. Sources are listed in the app and in [`substances.py`](daybook/daybook_app/substances.py).

> These curves estimate how much is in your blood from population averages. They don't show how strong the effect is, effects usually end before the curve does, and your body may differ a lot. Daybook isn't medical advice: talk to your prescriber before changing how you take anything.

## Privacy

- Data lives only in the app's own folder (`/data/daybook.db` inside the app), which is included in Home Assistant backups. Encrypt your backups.
- The panel opens through Home Assistant's ingress and is admin only; the app accepts connections only from the Supervisor's ingress proxy.
- Home Assistant sees only button entities and the level sensors you choose (caffeine by default). Turn a sensor off in Settings if you don't want it in history or visible to voice assistants and other integrations.
- Sport notifications use neutral text. On Android, the companion app's local push delivers them over your own connection instead of Google's servers.
- Export everything as JSON or CSV from Settings at any time.

## Development

```bash
uv venv -p 3.14 .venv
uv pip install -p .venv -r requirements_test.txt
.venv/bin/python -m pytest
.venv/bin/python dev/run.py 8765   # the app with sample data and a fake Home Assistant
```

## Roadmap

- Sleep from Sleep as Android and Health Connect
- Exercise sessions from Health Connect (Garmin and others)
- Small, local models that learn from your corrections (for example which zone stays were really sport)
- Simple personal experiments, such as alternating weeks with and without afternoon coffee
