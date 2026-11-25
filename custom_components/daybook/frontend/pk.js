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

export function caffeineDoses(entries) {
  return entries
    .filter((e) => e.kind === "caffeine" && e.status === "confirmed" && !e.deleted && e.value && e.value.mg > 0)
    .map((e) => [e.start, e.value.mg]);
}

export function caffeineAt(doses, ts, profiles, settings) {
  const p = profiles.caffeine;
  if (!p) return 0;
  let total = 0;
  for (const [t0, mg] of doses) {
    total += mg * amountFraction((ts - t0) / HOUR, p, settings.caffeine_half_life_h, settings.caffeine_absorption_min / 60);
  }
  return total;
}

export function medDoses(entries, medId) {
  return entries
    .filter(
      (e) =>
        e.kind === "med" &&
        e.item === medId &&
        e.status === "confirmed" &&
        !e.deleted &&
        (e.value?.status ?? "taken") === "taken",
    )
    .map((e) => [e.start, typeof e.value?.dose === "number" ? e.value.dose : 1]);
}

export function medProfile(med, profiles) {
  return profiles[med.profile] || profiles.custom;
}

// 1.0 = the peak of one usual dose of this med.
export function medLevel(doses, ts, med, profiles) {
  const p = medProfile(med, profiles);
  if (!p) return 0;
  const usual = med.dose || 1;
  const peak = singleDosePeak(p, med.half_life_h, med.tmax_h) * usual;
  if (peak <= 0) return 0;
  let total = 0;
  for (const [t0, d] of doses) total += d * amountFraction((ts - t0) / HOUR, p, med.half_life_h, med.tmax_h);
  return total / peak;
}
