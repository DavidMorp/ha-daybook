// SVG renderers shared by the views.
import {
  HOUR, doses, levelAt, substanceIds, substanceColor, substanceLabel, amountFraction,
  singleDosePeak, hoursUntilBelow, allItems, itemSubstance, effectWindow, workingIntervals,
  profileParams, referenceAmount, unitOf,
} from "./pk.js";

export const SPORT_COLOR = "#0ca30c";
export const SLEEP_COLOR = "#888780";
export const NOTE_COLOR = "#888780";

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function fmtDuration(seconds) {
  const m = Math.round(seconds / 60);
  const h = Math.floor(m / 60);
  return h ? (m % 60 ? `${h} h ${m % 60} min` : `${h} h`) : `${m} min`;
}

export function fmtHours(h) {
  return fmtDuration(h * 3600);
}

export function itemName(settings, kind, item) {
  if (kind === "state") return settings.states.find((s) => s.id === item)?.name || item;
  if (kind === "intake") return allItems(settings).find((s) => s.id === item)?.name || item;
  if (kind === "sleep") return "Sleep";
  if (kind === "note") return "Note";
  return item || kind;
}

export function stateColor(settings, id) {
  return settings.states.find((s) => s.id === id)?.color || "#888780";
}

export function intakeColor(settings, itemId) {
  const sub = itemSubstance(settings, itemId);
  return sub ? sub.color : "#888780";
}

const LEVEL_SCALE = 1.4; // relative level at full curve height

/**
 * One timeline row for [tFrom, tTo] mapped to [x0, x0 + w].
 *
 * Curves show how much of each substance is in your body, each scaled to
 * one usual dose of it (so one coffee and one Elvanse peak at the same
 * height, and a second coffee stacks higher). Hovering a curve shows its
 * scale in mg (see mgScale). Check-ins and intakes are marks on two lanes at
 * the bottom. `entries`
 * should include ~1.5 days before tFrom for carry-over.
 */
export function timelineRow({ entries, tFrom, tTo, x0, w, y, h, settings, profiles, interactive = true, scale = null, mgScales = false }) {
  const x = (t) => x0 + ((t - tFrom) / (tTo - tFrom)) * w;
  const inRange = (t) => t >= tFrom && t <= tTo;
  const live = entries.filter((e) => e.status !== "rejected" && !e.deleted);
  const laneH = 13;
  const stateLane = y + h - 2 * laneH - 4;
  const intakeLane = y + h - laneH;
  const base = stateLane - 5;
  const top = y + 4;
  const usable = base - top - 4;
  const negligible = settings.negligible_share ?? 0.1;
  let o = "";

  for (const e of live) {
    if (e.kind === "sleep" && e.end) {
      const a = Math.max(tFrom, e.start), b = Math.min(tTo, e.end);
      if (b > a) o += `<rect x="${x(a)}" y="${top}" width="${x(b) - x(a)}" height="${base - top}" fill="${SLEEP_COLOR}" opacity=".1"${hit(e, interactive)}><title>Sleep ${fmtTime(e.start)}–${fmtTime(e.end)}</title></rect>`;
    }
    if (e.kind === "sport") {
      const end = e.end || e.start + HOUR;
      const a = Math.max(tFrom, e.start), b = Math.min(tTo, end);
      if (b > a) {
        const draft = e.status === "draft";
        o += `<rect x="${x(a)}" y="${top}" width="${Math.max(2, x(b) - x(a))}" height="${base - top}" rx="3" fill="${SPORT_COLOR}" opacity="${draft ? 0.07 : 0.15}"${draft ? ` stroke="${SPORT_COLOR}" stroke-dasharray="3 3"` : ""}${hit(e, interactive)}><title>${esc(e.item || "Sport")} ${fmtTime(e.start)}–${fmtTime(end)}${draft ? " (suggested)" : ""}</title></rect>`;
      }
    }
  }
  o += `<line x1="${x0}" x2="${x0 + w}" y1="${base}" y2="${base}" stroke="var(--line)" stroke-width="1"/>`;

  // One line per substance: solid within the typical duration of action (or
  // always, without one), dashed outside it. A curve starts at the baseline
  // at the dose and is cut once it has fallen below the "cleared" share.
  const grid = [];
  for (let i = 0; i <= 240; i++) grid.push(tFrom + ((tTo - tFrom) * i) / 240);
  const series = [];
  let maxLevel = 0;
  for (const pid of substanceIds(settings)) {
    const d = doses(live, settings, pid);
    if (!d.length) continue;
    const win = effectWindow(settings, profiles, pid);
    const spans = workingIntervals(d, win);
    const times = [...grid, ...d.map(([t]) => t).filter(inRange)].sort((a, b) => a - b);
    const values = times.map((t) => {
      const v = levelAt(d, t, settings, profiles, pid);
      maxLevel = Math.max(maxLevel, v);
      return [t, v, !win || spans.some(([a, b]) => t >= a && t <= b)];
    });
    series.push([pid, d, values]);
  }
  const fullScale = scale || Math.max(LEVEL_SCALE, maxLevel * 1.05);
  const yOf = (v) => base - Math.min(1.02, v / fullScale) * usable;
  for (const [pid, d, values] of series) {
    const color = substanceColor(settings, pid);
    const name = esc(substanceLabel(settings, profiles, pid));
    // Runs of points with the same style; neighbours share a point so lines join.
    let run = null;
    const runs = [];
    values.forEach(([t, v, inside], i) => {
      const rising = (values[i + 1]?.[1] ?? 0) > v;
      if (v < negligible && !rising) { run = null; return; }
      const pt = [x(t), yOf(v)];
      if (!run || run.inside !== inside) {
        const prev = run?.pts[run.pts.length - 1];
        run = { inside, pts: prev ? [prev] : [] };
        runs.push(run);
      }
      run.pts.push(pt);
    });
    for (const r of runs) {
      if (r.pts.length < 2) continue;
      const dd = r.pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
      o += r.inside
        ? `<path data-curve="${pid}" d="${dd}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`
        : `<path data-curve="${pid}" d="${dd}" fill="none" stroke="${color}" stroke-width="1.5" stroke-dasharray="4 3" stroke-linecap="round"/>`;
      // A wider, invisible copy that's easy to point at.
      if (mgScales) o += `<path data-sub="${pid}" d="${dd}" fill="none" stroke="transparent" stroke-width="12" pointer-events="stroke"><title>${name}</title></path>`;
    }
    if (mgScales) o += mgScale({ pid, settings, profiles, fullScale, x0, base, usable });
  }

  // Bottom lanes: what you felt, then what you took.
  for (const e of live) {
    if (!inRange(e.start)) continue;
    const draft = e.status === "draft" ? ' opacity=".45"' : "";
    if (e.kind === "intake") {
      const amount = e.value?.amount != null ? ` · ${e.value.amount} ${esc(e.value.unit || "")}` : "";
      o += `<rect x="${x(e.start) - 2.5}" y="${intakeLane}" width="5" height="${laneH}" rx="2" fill="${intakeColor(settings, e.item)}"${draft}${hit(e, interactive)}><title>${esc(itemName(settings, e.kind, e.item))} ${fmtTime(e.start)}${amount}</title></rect>`;
    } else if (e.kind === "state") {
      o += `<rect x="${x(e.start) - 2.5}" y="${stateLane}" width="5" height="${laneH}" rx="2" fill="${stateColor(settings, e.item)}"${draft}${hit(e, interactive)}><title>${esc(itemName(settings, e.kind, e.item))} ${fmtTime(e.start)}${e.note ? ` · ${esc(e.note)}` : ""}</title></rect>`;
    } else if (e.kind === "note") {
      o += `<rect x="${x(e.start) - 2.5}" y="${stateLane}" width="5" height="${laneH}" rx="2" fill="none" stroke="${NOTE_COLOR}" stroke-width="1.5"${hit(e, interactive)}><title>${esc(e.note || "Note")}</title></rect>`;
    }
  }
  return o;
}

/**
 * The mg scale of one substance on the timeline's left edge, hidden until
 * its curve or legend entry is hovered. Height is shared by all substances,
 * so each gets its own ticks: level 1.0 is the peak of one usual dose.
 */
function mgScale({ pid, settings, profiles, fullScale, x0, base, usable }) {
  const [p, hl, tm] = profileParams(settings, profiles, pid);
  const peakAmount = singleDosePeak(p, hl, tm) * referenceAmount(settings, pid);
  const top = fullScale * peakAmount;
  if (!(top > 0)) return "";
  const raw = top / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw);
  const unit = esc(unitOf(settings, pid) || "mg");
  let o = `<g class="mgscale" data-scale="${pid}" style="display:none">`;
  o += `<rect x="0" y="${base - usable - 6}" width="${x0 - 2}" height="${usable + 9}" fill="var(--card)"/>`;
  for (let v = 0; v <= top + 1e-9; v += step) {
    const yy = base - (v / top) * usable;
    o += `<line x1="${x0 - 3}" x2="${x0}" y1="${yy}" y2="${yy}" stroke="var(--muted)"/>`;
    o += `<text x="${x0 - 5}" y="${yy + 4}" text-anchor="end" class="tick">${+v.toFixed(1)}</text>`;
  }
  o += `<text x="${x0 - 5}" y="${base - usable - 8}" text-anchor="end" class="tick">${unit}</text>`;
  return o + "</g>";
}

function hit(e, interactive) {
  return interactive ? ` data-action="edit:${e.id}" style="cursor:pointer"` : "";
}

export function hourAxis({ tFrom, tTo, x0, w, y, y2, labeler, step = 3 }) {
  let o = "";
  const startH = Math.ceil(tFrom / HOUR / step) * step;
  for (let hh = startH; hh * HOUR <= tTo; hh += step) {
    const t = hh * HOUR;
    const xx = x0 + ((t - tFrom) / (tTo - tFrom)) * w;
    o += `<line x1="${xx}" x2="${xx}" y1="${y + 6}" y2="${y2}" stroke="var(--line)" stroke-width="1"/>`;
    o += `<text x="${xx}" y="${y}" text-anchor="middle" class="tick">${labeler(t)}</text>`;
  }
  return o;
}

export function clockLabel(t) {
  return fmtTime(t);
}

/** Horizontal stacked bars of state shares, one per group. */
export function stackedBars(groups, settings, { width = 600, minN = 1 } = {}) {
  const rowH = 46;
  let o = "";
  groups.forEach((g, i) => {
    const y = i * rowH;
    const n = Object.values(g.counts).reduce((a, b) => a + b, 0);
    o += `<text x="0" y="${y + 13}" class="lbl">${esc(g.label)} <tspan class="muted">· ${n} check-in${n === 1 ? "" : "s"}</tspan></text>`;
    if (n < minN) {
      o += `<rect x="0" y="${y + 19}" width="${width}" height="18" rx="4" fill="none" stroke="var(--line)" stroke-dasharray="4 3"/>`;
      o += `<text x="${width / 2}" y="${y + 32}" text-anchor="middle" class="muted">Needs more check-ins (${n} of ${minN})</text>`;
      return;
    }
    let xx = 0;
    for (const s of settings.states) {
      const c = g.counts[s.id] || 0;
      if (!c) continue;
      const sw = (c / n) * width;
      o += `<rect x="${xx}" y="${y + 19}" width="${Math.max(0, sw - 2)}" height="18" rx="3" fill="${s.color}"><title>${esc(s.name)}: ${c} (${Math.round((c / n) * 100)}%)</title></rect>`;
      if (sw > 34) o += `<text x="${xx + 5}" y="${y + 32}" class="onbar">${Math.round((c / n) * 100)}%</text>`;
      xx += sw;
    }
  });
  return { svg: o, height: groups.length * rowH };
}

/**
 * Reference curves: one dose of each substance, as a share of its own peak.
 * Same style as the timeline: solid within the typical duration of action (or always, if
 * there's no effect window), dashed after, and it ends with a dot once it's
 * cleared (below `negligible`). Labels live outside the chart.
 */
export function substanceChart(entries, { width = 900, height = 260, hours = 24, negligible = 0.1 } = {}) {
  const x0 = 38, y0 = 10, w = width - x0 - 12, h = height - 36;
  const x = (t) => x0 + (t / hours) * w;
  const y = (v) => y0 + h - v * h;
  let o = "";
  for (let v = 0; v <= 1.0001; v += 0.25) {
    o += `<line x1="${x0}" x2="${x0 + w}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)" stroke-width="1"/>`;
    o += `<text x="${x0 - 6}" y="${y(v) + 4}" text-anchor="end" class="tick">${Math.round(v * 100)}%</text>`;
  }
  o += `<line x1="${x0}" x2="${x0 + w}" y1="${y(negligible)}" y2="${y(negligible)}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="1 3"/>`;
  for (let t = 0; t <= hours; t += 3) o += `<text x="${x(t)}" y="${y0 + h + 18}" text-anchor="middle" class="tick">${t} h</text>`;
  for (const { profile, color, hl, tm, name, win } of entries) {
    const label = esc(name || profile.name);
    const peak = singleDosePeak(profile, hl, tm);
    const gone = hoursUntilBelow(profile, negligible, hl, tm);
    const end = Math.min(hours, gone || hours);
    const runs = [];
    let run = null;
    for (let i = 0; i <= 288; i++) {
      const t = (hours * i) / 288;
      if (t > end) break;
      const working = !win || (t >= win[0] && t <= win[1]);
      const pt = `${x(t).toFixed(1)},${y(amountFraction(t, profile, hl, tm) / peak).toFixed(1)}`;
      if (!run || run.working !== working) {
        const prev = run?.pts[run.pts.length - 1];
        run = { working, pts: prev ? [prev] : [] };
        runs.push(run);
      }
      run.pts.push(pt);
    }
    for (const r of runs) {
      if (r.pts.length < 2) continue;
      o += r.working
        ? `<path d="M${r.pts.join(" L")}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"><title>${label}</title></path>`
        : `<path d="M${r.pts.join(" L")}" fill="none" stroke="${color}" stroke-width="1.6" stroke-dasharray="5 4" stroke-linecap="round"><title>${label}: outside its typical duration of action</title></path>`;
    }
    if (gone && gone <= hours) o += `<circle cx="${x(gone)}" cy="${y(negligible)}" r="4" fill="${color}"><title>${label}: cleared after ${fmtHours(gone)}</title></circle>`;
  }
  return o;
}
