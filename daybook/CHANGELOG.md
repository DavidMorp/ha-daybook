# Changelog

## 0.4.0

- Medications show their typical duration of action from studies: the curve is solid within it and dashed outside it, while some is still in your body. You can set your own for any substance (also coffee).
- Comparison lines can use "within duration of action" and "after duration of action (up to 12 h)".
- Curves are lines only, without numbers: the height is how much is in your body, each substance scaled to one usual dose of it. Each curve starts at the baseline at the dose. Dashed lines no longer mean "rough estimate".
- Hover a curve, or its name in the legend, to see its scale in mg; the other curves fade. Felt and Took marks are taller.
- The Day view's "Now" line says when the typical duration of action ends.
- Cards are packed into columns more reliably (the Day view's two cards sit side by side again).
- Fixed: after an update, browsers could keep running the old panel scripts ("settings.items is undefined"). Scripts are now served under a fingerprint of their content, so each version loads fresh files.

## 0.3.0

- What you take is grouped by substance in one Settings card: each substance (Caffeine, Elvanse…) holds the things you take that contain it. You can now have more than one custom substance.
- Settings from 0.2.0 are converted automatically when the app starts, and when you import an older settings file. Button entities, sensors and your entries keep their ids.
- Cards fill the page in columns instead of leaving gaps, and use more of wide screens.
- The Substances tab shows your own substances, with your colours and settings, and remembers which curves you turned on or off.

## 0.2.0

- Daybook is now a Home Assistant app with its own panel, instead of an integration.
- Caffeine and meds are one list of things you take, each linked to a substance profile.
- Removed the idea of a skipped dose: Daybook only records what you did.
- New Substances tab with reference curves; curves fade out once a substance is effectively gone.
- Check-ins and intakes are marks on two lanes at the bottom of the timeline.
- Comparison lines on the Patterns tab are now yours to define.
- The sleep chart compares nights with less or more of a substance left at bedtime than usual.
- Buttons, level sensors and logging go through MQTT.

## 0.1.0

- First version, as a custom integration.
