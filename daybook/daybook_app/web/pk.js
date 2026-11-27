// Same model as substances.py / model.py, for drawing curves in the browser.

export const HOUR = 3600;

const kaCache = new Map();

export function kaFromTmax(tmaxH, halfLifeH) {
  const key = `${tmaxH}|${halfLifeH}`;
  if (kaCache.has(key)) return kaCache.get(key);
  const ke = Math.LN2 / halfLifeH;
  let result;
  if (tmaxH >= 1 / ke) {
    result = ke * 1.0001;
  } else {
    let lo = ke * 1.0001;
    let hi = 200;
    for (let i = 0; i < 100; i++) {
      const mid = (lo + hi) / 2;
      const t = Math.log(mid / ke) / (mid - ke);
      if (t > tmaxH) lo = mid;
      else hi = mid;
    }
    result = (lo + hi) / 2;
  }
  kaCache.set(key, result);
  return result;
}

function bateman(dtH, ka, ke) {
  if (dtH <= 0) return 0;
  return (ka / (ka - ke)) * (Math.exp(-ke * dtH) - Math.exp(-ka * dtH));
}

export function amountFraction(dtH, profile, halfLifeH, tmaxH) {
  const hl = halfLifeH || profile.half_life_h;
  const tm = tmaxH || profile.tmax_h;
  const ke = Math.LN2 / hl;
  const ka = kaFromTmax(tm, hl);
  let total = 0;
  for (const c of profile.components) {
    const t = dtH - c.lag_h;
    if (t <= 0) continue;
    if (!c.release_h) {
      total += c.fraction * bateman(t, ka, ke);
    } else {
      const steps = 24;
      const w = c.release_h / steps;
      for (let i = 0; i < steps; i++) total += (c.fraction / steps) * bateman(t - (i + 0.5) * w, ka, ke);
    }
  }
  return total;
}

const peakCache = new Map();

export function singleDosePeak(profile, halfLifeH, tmaxH) {
  const key = `${profile.name}|${halfLifeH}|${tmaxH}`;
  if (peakCache.has(key)) return peakCache.get(key);
  let peak = 0;
  for (let i = 1; i < 20 * 36; i++) peak = Math.max(peak, amountFraction(i / 20, profile, halfLifeH, tmaxH));
  peakCache.set(key, peak);
  return peak;
}

/** Hours after one dose until it falls below `share` of its peak. */
export function hoursUntilBelow(profile, share, halfLifeH, tmaxH) {
  const peak = singleDosePeak(profile, halfLifeH, tmaxH);
  let peaked = false;
  for (let i = 1; i < 20 * 96; i++) {
    const v = amountFraction(i / 20, profile, halfLifeH, tmaxH) / peak;
    if (v > 0.99) peaked = true;
    if (peaked && v < share) return i / 20;
  }
  return null;
}

// Substances are the ones in settings, by id. Each has a profile, optional
// overrides, and the items you take that contain it.
export function findSubstance(settings, id) {
  return settings.substances.find((s) => s.id === id);
}

export function substanceIds(settings) {
  return settings.substances.map((s) => s.id);
}

/** Every item, with its substance id under `substance`. */
export function allItems(settings) {
  return settings.substances.flatMap((s) => s.items.map((it) => ({ ...it, substance: s.id })));
}

export function itemSubstance(settings, itemId) {
  return settings.substances.find((s) => s.items.some((it) => it.id === itemId));
}

export function profileParams(settings, profiles, id) {
  const sub = findSubstance(settings, id) || {};
  const profile = profiles[sub.profile] || profiles.custom;
  return [profile, sub.half_life_h || undefined, sub.tmax_h || undefined];
}

export function referenceAmount(settings, id) {
  return findSubstance(settings, id)?.items.find((i) => i.amount)?.amount || 1;
}

export function unitOf(settings, id) {
  return findSubstance(settings, id)?.items[0]?.unit || "";
}

export function substanceLabel(settings, profiles, id) {
  return findSubstance(settings, id)?.name || id;
}

export function substanceColor(settings, id) {
  return findSubstance(settings, id)?.color || "#d4537e";
}

/** [timestamp, amount] of confirmed intakes of one substance. */
export function doses(entries, settings, id) {
  const items = Object.fromEntries((findSubstance(settings, id)?.items || []).map((i) => [i.id, i]));
  const out = [];
  for (const e of entries) {
    if (e.kind !== "intake" || e.status !== "confirmed" || e.deleted) continue;
    const item = items[e.item];
    if (!item) continue;
    const amount = typeof e.value?.amount === "number" ? e.value.amount : item.amount || 1;
    out.push([e.start, amount]);
  }
  return out;
}

export function amountAt(doseList, ts, settings, profiles, id) {
  const [p, hl, tm] = profileParams(settings, profiles, id);
  let total = 0;
  for (const [t0, a] of doseList) total += a * amountFraction((ts - t0) / HOUR, p, hl, tm);
  return total;
}

/** 1.0 = the peak of one usual dose. */
export function levelAt(doseList, ts, settings, profiles, id) {
  const [p, hl, tm] = profileParams(settings, profiles, id);
  const peak = singleDosePeak(p, hl, tm) * referenceAmount(settings, id);
  return peak > 0 ? amountAt(doseList, ts, settings, profiles, id) / peak : 0;
}

/** [starts, stops] working in hours after one dose, or null (see model.py). */
export function effectWindow(settings, profiles, id) {
  const sub = findSubstance(settings, id) || {};
  const pub = (profiles[sub.profile] || profiles.custom)?.effect || {};
  const duration = sub.effect_h || pub.duration_h;
  if (!duration) return null;
  const onset = sub.onset_h ?? pub.onset_h ?? 0;
  return [onset, Math.max(duration, onset)];
}

/** Merged [start, end] timestamps within at least one dose's typical duration of action. */
export function workingIntervals(doseList, window) {
  if (!window) return [];
  const out = [];
  for (const t0 of doseList.map(([t]) => t).sort((a, b) => a - b)) {
    const a = t0 + window[0] * HOUR, b = t0 + window[1] * HOUR;
    if (out.length && a <= out[out.length - 1][1]) out[out.length - 1][1] = Math.max(out[out.length - 1][1], b);
    else out.push([a, b]);
  }
  return out;
}
