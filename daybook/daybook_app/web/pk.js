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

export function profileParams(settings, profiles, profileId) {
  const profile = profiles[profileId] || profiles.custom;
  const o = settings.substances?.[profileId] || {};
  return [profile, o.half_life_h || undefined, o.tmax_h || undefined];
}

export function profilesInUse(settings) {
  return [...new Set(settings.items.map((i) => i.profile))];
}

export function referenceAmount(settings, profileId) {
  return settings.items.find((i) => i.profile === profileId && i.amount)?.amount || 1;
}

export function substanceLabel(settings, profiles, profileId) {
  return settings.substances?.[profileId]?.label || profiles[profileId]?.name || profileId;
}

export function substanceColor(settings, profileId) {
  return settings.substances?.[profileId]?.color || "#d4537e";
}

/** [timestamp, amount] of confirmed intakes of one substance. */
export function doses(entries, settings, profileId) {
  const items = Object.fromEntries(settings.items.map((i) => [i.id, i]));
  const out = [];
  for (const e of entries) {
    if (e.kind !== "intake" || e.status !== "confirmed" || e.deleted) continue;
    const item = items[e.item];
    if (!item || item.profile !== profileId) continue;
    const amount = typeof e.value?.amount === "number" ? e.value.amount : item.amount || 1;
    out.push([e.start, amount]);
  }
  return out;
}

export function amountAt(doseList, ts, settings, profiles, profileId) {
  const [p, hl, tm] = profileParams(settings, profiles, profileId);
  let total = 0;
  for (const [t0, a] of doseList) total += a * amountFraction((ts - t0) / HOUR, p, hl, tm);
  return total;
}

/** 1.0 = the peak of one usual dose. */
export function levelAt(doseList, ts, settings, profiles, profileId) {
  const [p, hl, tm] = profileParams(settings, profiles, profileId);
  const peak = singleDosePeak(p, hl, tm) * referenceAmount(settings, profileId);
  return peak > 0 ? amountAt(doseList, ts, settings, profiles, profileId) / peak : 0;
}
