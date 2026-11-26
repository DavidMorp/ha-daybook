// SVG renderers shared by the views.
import {
  HOUR, doses, levelAt, profilesInUse, substanceColor, substanceLabel, amountFraction,
  singleDosePeak, hoursUntilBelow,
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
  return h ? `${h} h ${m % 60} min` : `${m} min`;
}

export function fmtHours(h) {
  return fmtDuration(h * 3600);
}

export function itemName(settings, kind, item) {
  if (kind === "state") return settings.states.find((s) => s.id === item)?.name || item;
  if (kind === "intake") return settings.items.find((s) => s.id === item)?.name || item;
  if (kind === "sleep") return "Sleep";
  if (kind === "note") return "Note";
  return item || kind;
}

export function stateColor(settings, id) {
  return settings.states.find((s) => s.id === id)?.color || "#888780";
}

export function intakeColor(settings, itemId) {
  const item = settings.items.find((i) => i.id === itemId);
  return item ? substanceColor(settings, item.profile) : "#888780";
}

const LEVEL_SCALE = 1.4; // relative level at full curve height

/**
 * One timeline row for [tFrom, tTo] mapped to [x0, x0 + w].
 * Curves in the upper part, marks for check-ins and intakes on two lanes at
 * the bottom. `entries` should include ~1.5 days before tFrom for carry-over.
 */
export function timelineRow({ entries, tFrom, tTo, x0, w, y, h, settings, profiles, interactive = true, scale = null }) {
  const x = (t) => x0 + ((t - tFrom) / (tTo - tFrom)) * w;
  const inRange = (t) => t >= tFrom && t <= tTo;
  const live = entries.filter((e) => e.status !== "rejected" && !e.deleted);
  const laneH = 11;
  const stateLane = y + h - 2 * laneH - 3;
  const intakeLane = y + h - laneH;
  const base = stateLane - 3;
  const top = y + 4;
  const usable = base - top;
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

  // Curves: one per substance, cut where it's effectively gone.
  const steps = 160;
  const series = [];
  let maxLevel = 0;
  for (const pid of profilesInUse(settings)) {
    const d = doses(live, settings, pid);
    if (!d.length) continue;
    const values = [];
    for (let i = 0; i <= steps; i++) {
      const t = tFrom + ((tTo - tFrom) * i) / steps;
      const v = levelAt(d, t, settings, profiles, pid);
      values.push([t, v]);
      maxLevel = Math.max(maxLevel, v);
    }
    series.push([pid, values]);
  }
  const fullScale = scale || Math.max(LEVEL_SCALE, maxLevel * 1.08);
  for (const [pid, values] of series) {
    const color = substanceColor(settings, pid);
    let seg = [];
    const segs = [];
    for (const [t, v] of values) {
      if (v >= negligible) seg.push([x(t), base - Math.min(1.02, v / fullScale) * usable]);
      else if (seg.length) { segs.push(seg); seg = []; }
    }
    if (seg.length) segs.push(seg);
    for (const s of segs) {
      const line = s.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L");
      o += `<path d="M${s[0][0].toFixed(1)},${base} L${line} L${s[s.length - 1][0].toFixed(1)},${base} Z" fill="${color}" opacity=".14"/>`;
      o += `<path d="M${line}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round"><title>${esc(substanceLabel(settings, profiles, pid))}</title></path>`;
    }
  }

  // Bottom lanes: what you felt, then what you took.
  for (const e of live) {
    if (!inRange(e.start)) continue;
    const draft = e.status === "draft" ? ' opacity=".45"' : "";
    if (e.kind === "state") {
      o += `<rect x="${x(e.start) - 2.5}" y="${stateLane}" width="5" height="${laneH}" rx="2" fill="${stateColor(settings, e.item)}"${draft}${hit(e, interactive)}><title>${esc(itemName(settings, e.kind, e.item))} ${fmtTime(e.start)}${e.note ? ` · ${esc(e.note)}` : ""}</title></rect>`;
    } else if (e.kind === "note") {
      o += `<rect x="${x(e.start) - 2.5}" y="${stateLane}" width="5" height="${laneH}" rx="2" fill="none" stroke="${NOTE_COLOR}" stroke-width="1.5"${hit(e, interactive)}><title>${esc(e.note || "Note")}</title></rect>`;
    } else if (e.kind === "intake") {
      const amount = e.value?.amount != null ? ` · ${e.value.amount} ${esc(e.value.unit || "")}` : "";
      o += `<rect x="${x(e.start) - 2.5}" y="${intakeLane}" width="5" height="${laneH}" rx="2" fill="${intakeColor(settings, e.item)}"${draft}${hit(e, interactive)}><title>${esc(itemName(settings, e.kind, e.item))} ${fmtTime(e.start)}${amount}</title></rect>`;
    }
  }
  return o;
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
 * Solid while it matters; faint once below `negligible` of the peak.
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
  o += `<rect x="${x0}" y="${y(negligible)}" width="${w}" height="${h - (y(negligible) - y0)}" fill="var(--line)" opacity=".35"/>`;
  o += `<text x="${x0 + w - 4}" y="${y(negligible) - 4}" text-anchor="end" class="tick">Below ${Math.round(negligible * 100)}%: effectively gone</text>`;
  for (let t = 0; t <= hours; t += 3) o += `<text x="${x(t)}" y="${y0 + h + 18}" text-anchor="middle" class="tick">${t} h</text>`;
  for (const { profile, color, hl, tm } of entries) {
    const peak = singleDosePeak(profile, hl, tm);
    const solid = [], faint = [];
    for (let i = 0; i <= 288; i++) {
      const t = (hours * i) / 288;
      const v = amountFraction(t, profile, hl, tm) / peak;
      const pt = `${x(t).toFixed(1)},${y(v).toFixed(1)}`;
      const after = t > profile.tmax_h && v < negligible;
      (after ? faint : solid).push(pt);
      if (!after && faint.length === 0 && i === 288) faint.push(pt);
    }
    if (faint.length && solid.length) faint.unshift(solid[solid.length - 1]);
    const dash = profile.verified ? "" : ' stroke-dasharray="6 4"';
    o += `<path d="M${solid.join(" L")}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"${dash}><title>${esc(profile.name)}</title></path>`;
    if (faint.length > 1) o += `<path d="M${faint.join(" L")}" fill="none" stroke="${color}" stroke-width="1.4" opacity=".35" stroke-dasharray="2 4"/>`;
    const gone = hoursUntilBelow(profile, negligible, hl, tm);
    if (gone && gone <= hours) o += `<circle cx="${x(gone)}" cy="${y(negligible)}" r="4" fill="${color}"><title>${esc(profile.name)}: effectively gone after ${fmtHours(gone)}</title></circle>`;
  }
  return o;
}
