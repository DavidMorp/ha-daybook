// SVG renderers shared by the Today, Week and Patterns views.
import { HOUR, caffeineAt, caffeineDoses, medDoses, medLevel, amountFraction, singleDosePeak } from "./pk.js";

export const CAFFEINE_COLOR = "#eda100";
export const SPORT_COLOR = "#0ca30c";
export const SLEEP_COLOR = "#888780";

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

const CAFFEINE_SCALE = 250; // mg at full row height
const MED_SCALE = 1.3; // relative level at full row height

export function itemName(settings, kind, item) {
  const group = { state: "states", caffeine: "drinks", med: "meds" }[kind];
  const found = group && settings[group].find((x) => x.id === item);
  if (found) return found.name;
  if (kind === "sleep") return "Sleep";
  if (kind === "note") return "Note";
  return item || kind;
}

export function stateColor(settings, id) {
  return settings.states.find((s) => s.id === id)?.color || "#888780";
}

/**
 * One timeline row for a period [tFrom, tTo] mapped to [x0, x0 + w].
 * `entries` should include up to ~36 h before tFrom so curves carry over.
 */
export function timelineRow({ entries, tFrom, tTo, x0, w, y, h, settings, profiles, interactive = true }) {
  const x = (t) => x0 + ((t - tFrom) / (tTo - tFrom)) * w;
  const inRange = (t) => t >= tFrom && t <= tTo;
  const live = entries.filter((e) => e.status !== "rejected" && !e.deleted);
  const base = y + h - 6;
  const top = y + 8;
  const usable = base - top;
  let o = "";

  for (const e of live) {
    if (e.kind === "sleep" && e.end) {
      const a = Math.max(tFrom, e.start), b = Math.min(tTo, e.end);
      if (b > a) o += `<rect x="${x(a)}" y="${base - 2}" width="${x(b) - x(a)}" height="4" rx="2" fill="${SLEEP_COLOR}" opacity=".45"${hit(e, interactive)}><title>Sleep ${fmtTime(e.start)}–${fmtTime(e.end)}</title></rect>`;
    }
    if (e.kind === "sport") {
      const end = e.end || e.start + 3600;
      const a = Math.max(tFrom, e.start), b = Math.min(tTo, end);
      if (b > a) {
        const draft = e.status === "draft";
        o += `<rect x="${x(a)}" y="${y + 2}" width="${Math.max(2, x(b) - x(a))}" height="${h - 6}" rx="4" fill="${SPORT_COLOR}" opacity="${draft ? 0.08 : 0.16}"${draft ? ` stroke="${SPORT_COLOR}" stroke-dasharray="3 3"` : ""}${hit(e, interactive)}><title>${esc(e.item || "Sport")} ${fmtTime(e.start)}–${fmtTime(end)}${draft ? " (draft)" : ""}</title></rect>`;
      }
    }
  }

  const steps = 120;
  const caf = caffeineDoses(live);
  if (caf.length) {
    const pts = [];
    for (let i = 0; i <= steps; i++) {
      const t = tFrom + ((tTo - tFrom) * i) / steps;
      const v = caffeineAt(caf, t, profiles, settings);
      pts.push([x(t), base - Math.min(1.1, v / CAFFEINE_SCALE) * usable]);
    }
    const line = pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L");
    o += `<path d="M${x0},${base} L${line} L${x0 + w},${base} Z" fill="${CAFFEINE_COLOR}" opacity=".22"/>`;
    o += `<path d="M${line}" fill="none" stroke="${CAFFEINE_COLOR}" stroke-width="1.5"/>`;
  }

  for (const med of settings.meds) {
    const doses = medDoses(live, med.id);
    if (!doses.length) continue;
    const pts = [];
    for (let i = 0; i <= steps; i++) {
      const t = tFrom + ((tTo - tFrom) * i) / steps;
      pts.push([x(t), base - Math.min(1.1, medLevel(doses, t, med, profiles) / MED_SCALE) * usable]);
    }
    o += `<path d="M${pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L")}" fill="none" stroke="${med.color}" stroke-width="1.8" stroke-linejoin="round"/>`;
  }

  for (const e of live) {
    if (!inRange(e.start)) continue;
    const draft = e.status === "draft" ? ' opacity=".5"' : "";
    if (e.kind === "caffeine") {
      o += `<rect x="${x(e.start) - 2}" y="${base - 1}" width="4" height="7" rx="1" fill="${CAFFEINE_COLOR}"${draft}${hit(e, interactive)}><title>${esc(itemName(settings, e.kind, e.item))} ${fmtTime(e.start)} · ${Math.round(e.value?.mg || 0)} mg</title></rect>`;
    } else if (e.kind === "med") {
      const med = settings.meds.find((m) => m.id === e.item);
      const color = med?.color || "#d4537e";
      const skipped = e.value?.status === "skipped";
      o += skipped
        ? `<circle cx="${x(e.start)}" cy="${y + 6}" r="4.5" fill="var(--card-background-color, #fff)" stroke="${color}" stroke-width="1.6"${draft}${hit(e, interactive)}><title>${esc(med?.name || e.item)} skipped</title></circle>`
        : `<circle cx="${x(e.start)}" cy="${y + 6}" r="5" fill="${color}"${draft}${hit(e, interactive)}><title>${esc(med?.name || e.item)} ${fmtTime(e.start)}${e.value?.dose ? ` · ${e.value.dose} ${esc(e.value.unit || "")}` : ""}</title></circle>`;
    } else if (e.kind === "note") {
      o += `<rect x="${x(e.start) - 4}" y="${y + 2}" width="8" height="8" rx="2" fill="var(--secondary-text-color, #888)"${hit(e, interactive)}><title>${esc(e.note || "Note")}</title></rect>`;
    }
  }
  for (const e of live) {
    if (e.kind !== "state" || !inRange(e.start)) continue;
    const draft = e.status === "draft" ? ' opacity=".5"' : "";
    o += `<circle cx="${x(e.start)}" cy="${y + h / 2}" r="6.5" fill="${stateColor(settings, e.item)}" stroke="var(--card-background-color, #fff)" stroke-width="2"${draft}${hit(e, interactive)}><title>${esc(itemName(settings, e.kind, e.item))} ${fmtTime(e.start)}${e.note ? ` · ${esc(e.note)}` : ""}</title></circle>`;
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
    o += `<line x1="${xx}" x2="${xx}" y1="${y + 6}" y2="${y2}" stroke="var(--divider-color, #e1e0d9)" stroke-width="1"/>`;
    o += `<text x="${xx}" y="${y}" text-anchor="middle" class="tick">${labeler(t)}</text>`;
  }
  return o;
}

export function clockLabel(t) {
  return fmtTime(t);
}

/** Horizontal stacked bars of state shares, one per group. */
export function stackedBars(groups, settings, { width = 560, minN = 1 } = {}) {
  const rowH = 46;
  const labelW = 0;
  let o = "";
  groups.forEach((g, i) => {
    const y = i * rowH;
    const n = Object.values(g.counts).reduce((a, b) => a + b, 0);
    o += `<text x="0" y="${y + 13}" class="lbl">${esc(g.label)} <tspan class="muted">· n=${n}</tspan></text>`;
    if (n < minN) {
      o += `<rect x="${labelW}" y="${y + 19}" width="${width}" height="18" rx="4" fill="none" stroke="var(--divider-color)" stroke-dasharray="4 3"/>`;
      o += `<text x="${width / 2}" y="${y + 32}" text-anchor="middle" class="muted">Needs more data (${n}/${minN})</text>`;
      return;
    }
    let xx = labelW;
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

/** Reference curves: one dose of each profile, normalised to its own peak. */
export function substanceChart(ids, profiles, colors, { width = 640, height = 220, hours = 24 } = {}) {
  const x0 = 34, y0 = 10, w = width - x0 - 10, h = height - 34;
  const x = (t) => x0 + (t / hours) * w;
  const y = (v) => y0 + h - v * h;
  let o = "";
  for (let v = 0; v <= 1; v += 0.25) {
    o += `<line x1="${x0}" x2="${x0 + w}" y1="${y(v)}" y2="${y(v)}" stroke="var(--divider-color)" stroke-width="1"/>`;
    o += `<text x="${x0 - 6}" y="${y(v) + 4}" text-anchor="end" class="tick">${Math.round(v * 100)}%</text>`;
  }
  for (let t = 0; t <= hours; t += 3) o += `<text x="${x(t)}" y="${y0 + h + 16}" text-anchor="middle" class="tick">${t} h</text>`;
  ids.forEach((id) => {
    const p = profiles[id];
    if (!p) return;
    const peak = singleDosePeak(p);
    const pts = [];
    for (let i = 0; i <= 240; i++) {
      const t = (hours * i) / 240;
      pts.push(`${x(t).toFixed(1)},${y(amountFraction(t, p) / peak).toFixed(1)}`);
    }
    o += `<path d="M${pts.join(" L")}" fill="none" stroke="${colors[id]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"${p.verified ? "" : ' stroke-dasharray="5 4"'}><title>${esc(p.name)}</title></path>`;
  });
  return o;
}

/** Hours after one dose until the level falls below a share of its peak. */
export function hoursBelow(profile, share) {
  const peak = singleDosePeak(profile);
  let peaked = false;
  for (let i = 1; i < 20 * 72; i++) {
    const v = amountFraction(i / 20, profile) / peak;
    if (v > 0.99) peaked = true;
    if (peaked && v < share) return i / 20;
  }
  return null;
}
