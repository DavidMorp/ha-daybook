# Daybook

Open **Daybook** in the sidebar. The first time, go to **Settings**:

1. **How you feel**: the states you check in with. Mark each as high or low energy.
2. **What you take**: add a substance (caffeine, your medication…), then the things you take that contain it, such as coffee and espresso, with your usual amount. The substance tells Daybook how long it stays in your body.
3. **Sport places** (optional): pick a Home Assistant zone, the person, the minimum time and your training times. Stays become suggested sport entries.
4. **Comparison lines**: the lines of the "How you felt, depending on what you'd had" chart.

## Logging

- **Panel:** tap a state or something you took. The message at the bottom lets you undo it, move it 15 minutes back or edit it.
- **Home Assistant:** Daybook adds buttons such as `button.daybook_took_coffee` (needs the Mosquitto broker app).
- **Automations and ESPHome:** publish to `daybook/log`, for example `{"kind": "intake", "item": "coffee"}`. Publish `{"source": "..."}` to `daybook/undo` to remove the newest entry from that source.

## Options

- **Log level**: how much Daybook writes to its log.

## Your data

Entries are stored in the app's own folder and included in Home Assistant backups. Export them as JSON or CSV from Settings.

The substance curves are estimates from published averages, not medical advice.
