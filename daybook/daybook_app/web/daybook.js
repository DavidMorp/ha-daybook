// Daybook panel. Plain web component, no build step, no external requests.
import {
  HOUR, doses, levelAt, amountAt, profilesInUse, substanceColor, substanceLabel, profileParams,
  singleDosePeak, hoursUntilBelow, referenceAmount,
} from "./pk.js";
import {
  SPORT_COLOR, SLEEP_COLOR, esc, fmtTime, fmtDuration, fmtHours, itemName, stateColor, intakeColor,
  timelineRow, hourAxis, clockLabel, stackedBars, substanceChart,
} from "./charts.js";

const DAY = 24 * HOUR;
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const PALETTE = ["#d4537e", "#534ab7", "#0f6e56", "#2a78d6", "#993c1d", "#eb6834", "#1baf7a", "#eda100"];
const VIEWS = [
  ["today", "Day"],
  ["week", "Week"],
  ["patterns", "Patterns"],
  ["substances", "Substances"],
  ["settings", "Settings"],
];

const pad = (n) => String(n).padStart(2, "0");
const toInput = (ts) => {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const fromInput = (v) => (v ? new Date(v).getTime() / 1000 : null);
const slug = (s) => (s.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "item");
const clone = (o) => JSON.parse(JSON.stringify(o));
const sum = (o) => Object.values(o || {}).reduce((a, b) => a + b, 0);
const round1 = (v) => Math.round(v * 10) / 10;

/** WebSocket connection to the Daybook app, with request ids and reconnects. */
export class Connection {
  constructor(url) {
    this._url = url;
    this._id = 1;
    this._pending = new Map();
    this._subs = new Map();
    this._open();
  }

  _open() {
    this.ready = new Promise((resolve) => (this._resolveReady = resolve));
    const ws = new WebSocket(this._url);
    this._ws = ws;
    ws.onopen = () => {
      this._resolveReady();
      for (const [id, sub] of this._subs) ws.send(JSON.stringify({ ...sub.msg, id }));
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "event") this._subs.get(msg.id)?.cb(msg.event);
      if (msg.type !== "result") return;
      const p = this._pending.get(msg.id);
      if (!p) return;
      this._pending.delete(msg.id);
      if (msg.success) p.resolve(msg.result);
      else p.reject(new Error(msg.error?.message || "Request failed"));
    };
    ws.onclose = () => {
      for (const p of this._pending.values()) p.reject(new Error("Connection lost, retrying…"));
      this._pending.clear();
      setTimeout(() => this._open(), 2000);
    };
  }

  async call(msg) {
    await this.ready;
    const id = this._id++;
    return new Promise((resolve, reject) => {
      this._pending.set(id, { resolve, reject });
      this._ws.send(JSON.stringify({ ...msg, id }));
    });
  }

  async subscribe(cb, msg) {
    const id = this._id++;
    this._subs.set(id, { cb, msg });
    await this.ready;
    this._ws.send(JSON.stringify({ ...msg, id }));
  }
}

class DaybookApp extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._view = "today";
    this._entries = [];
    this._weekDays = 7;
    this._weekAlign = "clock";
    this._patternDays = 56;
    this._shownSubstances = null;
    this._dialog = null;
    this._toast = null;
    this._ha = { connected: false, mqtt: false, entities: {}, notify: [] };
  }

  set connection(conn) {
    this._conn = conn;
    this._init();
  }

  // -- setup ----------------------------------------------------------
  async _init() {
    this._shell();
    try {
      const [s, subs] = await Promise.all([this._ws({ type: "daybook/settings/get" }), this._ws({ type: "daybook/substances" })]);
      this._settings = s.settings;
      this._profiles = subs.profiles;
      this._disclaimer = subs.disclaimer;
      this._dayStart = this._journalDayStart(Date.now() / 1000);
      this._conn.subscribe((ev) => this._onChange(ev), { type: "daybook/subscribe" });
      await this._load();
    } catch (err) {
      this._main.innerHTML = `<div class="card error">${esc(err.message || err)}</div>`;
    }
  }

  _shell() {
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <div class="toolbar"><div class="title">Daybook</div>
        <nav>${VIEWS.map(([id, label]) => `<button class="tab" data-action="tab:${id}">${label}</button>`).join("")}</nav></div>
      <main></main><div class="overlay"></div><div class="toast"></div>`;
    this._main = this.shadowRoot.querySelector("main");
    this._overlay = this.shadowRoot.querySelector(".overlay");
    this._toastEl = this.shadowRoot.querySelector(".toast");
    this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
    this.shadowRoot.addEventListener("change", (e) => this._onField(e));
    this.shadowRoot.addEventListener("input", (e) => this._onField(e, true));
    this._markTab();
  }

  get _narrow() {
    return this.getBoundingClientRect().width < 700;
  }

  _markTab() {
    this.shadowRoot.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.action === `tab:${this._view}`));
  }

  _ws(msg) {
    return this._conn.call(msg);
  }

  _onChange(ev) {
    if (ev.changed === "settings") {
      this._ws({ type: "daybook/settings/get" }).then((s) => (this._settings = s.settings));
      if (this._view === "settings") return;
    }
    clearTimeout(this._reloadTimer);
    this._reloadTimer = setTimeout(() => this._load(), 250);
  }

  _journalDayStart(ts) {
    const dsh = this._settings.day_start_hour;
    const d = new Date((ts - dsh * HOUR) * 1000);
    return new Date(d.getFullYear(), d.getMonth(), d.getDate(), dsh).getTime() / 1000;
  }

  _shiftDay(ts, n) {
    const d = new Date(ts * 1000);
    return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, d.getHours()).getTime() / 1000;
  }

  _midnight(dayStart) {
    const d = new Date(dayStart * 1000);
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000;
  }

  _isToday() {
    return this._dayStart === this._journalDayStart(Date.now() / 1000);
  }

  _label(pid) {
    return substanceLabel(this._settings, this._profiles, pid);
  }

  /** For use inside sentences: your own names as written, generic names in lower case. */
  _noun(pid) {
    const own = this._settings.substances?.[pid]?.label;
    return own || (this._profiles[pid]?.name || pid).toLowerCase();
  }

  // -- loading --------------------------------------------------------
  async _load() {
    if (!this._settings) return;
    try {
      if (this._view === "today") {
        const end = this._shiftDay(this._dayStart, 1);
        this._entries = await this._ws({ type: "daybook/entries/list", start: this._dayStart - 1.5 * DAY, end });
      } else if (this._view === "week") {
        const first = this._shiftDay(this._dayStart, -(this._weekDays - 1));
        const end = this._shiftDay(this._dayStart, 1);
        this._entries = await this._ws({ type: "daybook/entries/list", start: first - 1.5 * DAY, end });
      } else if (this._view === "patterns") {
        this._insights = await this._ws({ type: "daybook/insights", days: this._patternDays });
      } else if (this._view === "settings") {
        this._ha = await this._ws({ type: "daybook/ha" });
        if (!this._draft) this._draft = clone(this._settings);
      }
    } catch (err) {
      this._showToast(err.message || String(err));
    }
    this._render();
  }

  _render() {
    this._markTab();
    const views = {
      today: () => this._renderToday(),
      week: () => this._renderWeek(),
      patterns: () => this._renderPatterns(),
      substances: () => this._renderSubstances(),
      settings: () => this._renderSettings(),
    };
    this._main.innerHTML = views[this._view]();
    this._renderDialog();
  }

  _legend() {
    const s = this._settings;
    return `<div class="legend">
      ${s.states.map((st) => `<span><i class="sw mark" style="background:${st.color}"></i>${esc(st.name)}</span>`).join("")}
      ${profilesInUse(s).map((pid) => `<span><i class="sw line" style="background:${substanceColor(s, pid)}"></i>${esc(this._label(pid))}</span>`).join("")}
      <span><i class="sw" style="background:${SPORT_COLOR};opacity:.35"></i>Sport</span>
      <span><i class="sw" style="background:${SLEEP_COLOR};opacity:.3"></i>Sleep</span></div>`;
  }

  _laneLabels(svgY, h, x) {
    const laneH = 11;
    const stateLane = svgY + h - 2 * laneH - 3;
    const intakeLane = svgY + h - laneH;
    return `<text x="${x}" y="${stateLane + 9}" class="tick" text-anchor="end">Felt</text>
      <text x="${x}" y="${intakeLane + 9}" class="tick" text-anchor="end">Took</text>`;
  }

  // -- Day view -------------------------------------------------------
  _dayEntries() {
    const end = this._shiftDay(this._dayStart, 1);
    return this._entries.filter((e) => e.start >= this._dayStart && e.start < end);
  }

  _renderToday() {
    const s = this._settings;
    const day = this._dayEntries();
    const label = new Date(this._dayStart * 1000).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
    const now = Date.now() / 1000;
    const drafts = day.filter((e) => e.status === "draft");

    const inBody = this._isToday()
      ? profilesInUse(s).map((pid) => {
          const d = doses(this._entries, s, pid);
          if (!d.length) return "";
          const level = levelAt(d, now, s, this._profiles, pid);
          if (level < s.negligible_share) return "";
          const unit = s.items.find((i) => i.profile === pid)?.unit || "";
          const amount = amountAt(d, now, s, this._profiles, pid);
          return `<span><i class="sw line" style="background:${substanceColor(s, pid)}"></i>${esc(this._label(pid))} ≈ ${Math.round(amount)} ${esc(unit)}</span>`;
        }).join("")
      : "";

    const counts = {};
    for (const e of day) if (e.kind === "intake" && e.status === "confirmed") counts[e.item] = (counts[e.item] || 0) + 1;
    const tookToday = Object.entries(counts).map(([id, n]) => `${esc(itemName(s, "intake", id))}${n > 1 ? ` ×${n}` : ""}`).join(", ");

    const mid = this._midnight(this._dayStart);
    const tFrom = mid + s.axis_start_hour * HOUR;
    const tTo = mid + s.axis_end_hour * HOUR;
    const W = 680, x0 = 34, w = W - x0 - 6, H = 150;

    return `
      <div class="daynav">
        <button class="icon" data-action="day:-1" aria-label="Previous day">‹</button>
        <h2>${esc(label)}</h2>
        <button class="icon" data-action="day:1" aria-label="Next day" ${this._isToday() ? "disabled" : ""}>›</button>
        ${this._isToday() ? "" : `<button class="ghost" data-action="day:today">Today</button>`}
      </div>
      <div class="grid">
        <section class="card log">
          <h3>${this._isToday() ? "Log now" : "Add to this day"}</h3>
          <div class="group"><div class="glabel">How are you?</div><div class="chips">
            ${s.states.map((st) => `<button class="chip state" style="--c:${st.color}" data-action="quick:state:${st.id}"><span class="dot"></span>${esc(st.name)}</button>`).join("")}
          </div></div>
          <div class="group"><div class="glabel">Took</div><div class="chips">
            ${s.items.map((it) => `<button class="chip" data-action="quick:intake:${it.id}"><span class="dot" style="background:${substanceColor(s, it.profile)}"></span>${esc(it.name)}${it.amount != null ? ` <span class="sub">${round1(it.amount)} ${esc(it.unit)}</span>` : ""}</button>`).join("")}
            ${s.items.length ? "" : `<span class="muted">Add coffee, meds and more in <a href="#" data-action="tab:settings">Settings</a>.</span>`}
          </div>${tookToday ? `<div class="muted small took">So far: ${tookToday}</div>` : ""}</div>
          <div class="group"><div class="glabel">Other</div><div class="chips">
            <button class="chip" data-action="new:sport">Sport</button>
            <button class="chip" data-action="new:sleep">Sleep</button>
            <button class="chip" data-action="new:note">Note</button>
          </div></div>
        </section>
        <section class="card">
          <h3>Timeline</h3>
          ${inBody ? `<div class="legend now">Now: ${inBody}</div>` : ""}
          ${this._legend()}
          <svg viewBox="0 0 ${W} ${H + 22}" class="strip" role="img" aria-label="Timeline of the day">
            ${hourAxis({ tFrom, tTo, x0, w, y: 12, y2: H + 20, labeler: clockLabel })}
            ${timelineRow({ entries: this._entries, tFrom, tTo, x0, w, y: 20, h: H, settings: s, profiles: this._profiles })}
            ${this._laneLabels(20, H, x0 - 4)}
            ${this._isToday() && now > tFrom && now < tTo ? `<line x1="${x0 + ((now - tFrom) / (tTo - tFrom)) * w}" x2="${x0 + ((now - tFrom) / (tTo - tFrom)) * w}" y1="18" y2="${H + 20}" stroke="var(--accent)" stroke-width="1.5"/>` : ""}
          </svg>
          ${drafts.length ? `<div class="drafts">${drafts.map((e) => `<div class="draft"><span>Suggested: ${esc(itemName(s, e.kind, e.item))} ${fmtTime(e.start)}${e.end ? `–${fmtTime(e.end)}` : ""}</span>
              <button data-action="confirm:${e.id}">Confirm</button><button class="ghost" data-action="edit:${e.id}">Edit</button><button class="ghost" data-action="reject:${e.id}">Dismiss</button></div>`).join("")}</div>` : ""}
          <ul class="entries">
            ${day.filter((e) => e.status !== "rejected").map((e) => this._entryRow(e)).join("") || `<li class="empty">Nothing logged ${this._isToday() ? "yet today" : "on this day"}.</li>`}
          </ul>
        </section>
      </div>`;
  }

  _entryRow(e) {
    const s = this._settings;
    let color = "var(--muted)";
    let detail = "";
    if (e.kind === "state") color = stateColor(s, e.item);
    if (e.kind === "intake") {
      color = intakeColor(s, e.item);
      detail = e.value?.amount != null ? `${round1(e.value.amount)} ${esc(e.value.unit || "")}` : "";
    }
    if (e.kind === "sport") { color = SPORT_COLOR; detail = e.end ? fmtDuration(e.end - e.start) : ""; }
    if (e.kind === "sleep") detail = e.end ? fmtDuration(e.end - e.start) : "";
    const time = e.end ? `${fmtTime(e.start)}–${fmtTime(e.end)}` : fmtTime(e.start);
    return `<li data-action="edit:${e.id}" class="${e.status}">
      <span class="time">${time}</span><span class="dot" style="background:${color}"></span>
      <span class="what">${esc(itemName(s, e.kind, e.item))}${e.note ? `<span class="note">${esc(e.note)}</span>` : ""}</span>
      <span class="detail">${detail}${e.status === "draft" ? ' <span class="badge">Suggested</span>' : ""}</span></li>`;
  }

  // -- Week view ------------------------------------------------------
  _renderWeek() {
    const s = this._settings;
    const narrow = this._narrow;
    const days = [];
    for (let i = this._weekDays - 1; i >= 0; i--) days.push(this._shiftDay(this._dayStart, -i));
    const inUse = profilesInUse(s);
    if (this._weekAlign !== "clock" && !inUse.includes(this._weekAlign)) this._weekAlign = "clock";
    const W = narrow ? 420 : 680, L = narrow ? 46 : 64, w = W - L - 4, RH = this._weekDays > 7 ? 46 : 62, TOP = 24;
    const height = TOP + days.length * RH + 6;
    let rows = "";
    let axis;
    if (this._weekAlign === "clock") {
      const mid = this._midnight(days[0]);
      axis = hourAxis({ tFrom: mid + s.axis_start_hour * HOUR, tTo: mid + s.axis_end_hour * HOUR, x0: L, w, y: 12, y2: height, labeler: clockLabel, step: narrow ? 6 : 3 });
    } else {
      axis = hourAxis({ tFrom: -3 * HOUR, tTo: 15 * HOUR, x0: L, w, y: 12, y2: height, labeler: (t) => `${t > 0 ? "+" : ""}${Math.round(t / HOUR)} h`, step: narrow ? 6 : 3 });
    }
    days.forEach((ds, i) => {
      const y = TOP + i * RH;
      const end = this._shiftDay(ds, 1);
      const d = new Date(ds * 1000);
      rows += `<g data-action="goto:${ds}" class="daylabel"><text x="0" y="${y + RH / 2}" class="lbl">${WEEKDAYS[(d.getDay() + 6) % 7]} ${d.getDate()}</text></g>`;
      let tFrom, tTo;
      if (this._weekAlign === "clock") {
        const mid = this._midnight(ds);
        tFrom = mid + s.axis_start_hour * HOUR;
        tTo = mid + s.axis_end_hour * HOUR;
      } else {
        const first = doses(this._entries, s, this._weekAlign).map(([t]) => t).filter((t) => t >= ds && t < end).sort((a, b) => a - b)[0];
        if (first === undefined) {
          rows += `<text x="${L + w / 2}" y="${y + RH / 2 + 4}" text-anchor="middle" class="muted">No ${esc(this._noun(this._weekAlign))} this day</text>`;
          return;
        }
        tFrom = first - 3 * HOUR;
        tTo = first + 15 * HOUR;
      }
      rows += `<line x1="${L}" x2="${L + w}" y1="${y + RH}" y2="${y + RH}" stroke="var(--line)" stroke-width=".5"/>`;
      rows += timelineRow({ entries: this._entries, tFrom, tTo, x0: L, w, y, h: RH - 4, settings: s, profiles: this._profiles, scale: 2.0 });
    });
    const first = new Date(days[0] * 1000), last = new Date(days[days.length - 1] * 1000);
    const fmt = (d) => d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
    const atLatest = this._dayStart >= this._journalDayStart(Date.now() / 1000);
    return `
      <div class="daynav">
        <button class="icon" data-action="week:-1" aria-label="Earlier">‹</button><h2>${fmt(first)} – ${fmt(last)}</h2>
        <button class="icon" data-action="week:1" aria-label="Later" ${atLatest ? "disabled" : ""}>›</button>
      </div>
      <section class="card">
        <div class="controls">
          <div class="seg">${[7, 14].map((n) => `<button class="${this._weekDays === n ? "on" : ""}" data-action="weekdays:${n}">${n} days</button>`).join("")}</div>
          <label>Line days up by <select data-field="align">
            <option value="clock" ${this._weekAlign === "clock" ? "selected" : ""}>Time of day</option>
            ${inUse.map((pid) => `<option value="${pid}" ${this._weekAlign === pid ? "selected" : ""}>First ${esc(this._noun(pid))}</option>`).join("")}
          </select></label>
        </div>
        ${this._legend()}
        <svg viewBox="0 0 ${W} ${height}" class="week" role="img" aria-label="Days side by side">${axis}${rows}</svg>
        <p class="hint">Marks at the bottom of each day: how you felt (upper) and what you took (lower). Click a day to open it.</p>
      </section>`;
  }

  // -- Patterns view --------------------------------------------------
  _renderPatterns() {
    const s = this._settings;
    const r = this._insights;
    if (!r) return `<div class="card">Loading…</div>`;
    const minN = s.min_samples;
    const stateName = (id) => s.states.find((x) => x.id === id)?.name || id;

    let grid = "";
    r.band_labels.forEach((band, j) => (grid += `<text x="${70 + j * 102 + 48}" y="12" text-anchor="middle" class="tick">${band}</text>`));
    r.weekday_grid.forEach((row, i) => {
      grid += `<text x="0" y="${36 + i * 30}" class="lbl">${WEEKDAYS[i]}</text>`;
      row.forEach((cell, j) => {
        const n = sum(cell);
        const x = 70 + j * 102, y = 22 + i * 30;
        if (n < 2) {
          grid += `<rect x="${x}" y="${y}" width="96" height="24" rx="5" fill="none" stroke="var(--line)"/>`;
          return;
        }
        const sorted = Object.entries(cell).sort((a, b) => b[1] - a[1]);
        const [top, c] = sorted[0];
        const name = stateName(top);
        const short = name.length > 10 ? `${name.slice(0, 9)}…` : name;
        grid += `<rect x="${x}" y="${y}" width="96" height="24" rx="5" fill="${stateColor(s, top)}" opacity="${(0.35 + 0.65 * (c / n)).toFixed(2)}"><title>${WEEKDAYS[i]} ${r.band_labels[j]}: ${esc(sorted.map(([k, v]) => `${stateName(k)} ${v}`).join(", "))}</title></rect>`;
        grid += `<text x="${x + 8}" y="${y + 16}" class="onbar">${esc(short)} ${Math.round((c / n) * 100)}%</text>`;
      });
    });

    const comps = stackedBars(r.comparisons.map((c) => ({ label: c.name, counts: c.counts })), s, { minN });

    const substanceCards = profilesInUse(s).map((pid) => {
      const ww = r.with_without[pid];
      const sf = r.since_first[pid];
      const label = this._label(pid);
      if (!ww) return "";
      const bars = stackedBars([
        { label: `Days with ${this._noun(pid)} (${ww.days_with})`, counts: ww.with },
        { label: `Days without (${ww.days_without})`, counts: ww.without },
      ], s, { minN });
      let cols = "";
      const bw = 66;
      r.since_bins.forEach((lo, i) => {
        const hi = r.since_bins[i + 1];
        const counts = sf?.[i] || {};
        const n = sum(counts);
        const x = 10 + i * (bw + 8);
        cols += `<text x="${x + bw / 2}" y="188" text-anchor="middle" class="tick">${hi ? `${lo}–${hi} h` : `${lo} h+`}</text>`;
        cols += `<text x="${x + bw / 2}" y="202" text-anchor="middle" class="tick">${n}</text>`;
        if (n < Math.max(2, Math.ceil(minN / 2))) {
          cols += `<rect x="${x}" y="10" width="${bw}" height="164" rx="4" fill="none" stroke="var(--line)" stroke-dasharray="4 3"/>`;
          return;
        }
        let y = 174;
        for (const st of s.states) {
          const c = counts[st.id] || 0;
          if (!c) continue;
          const hh = (c / n) * 164;
          y -= hh;
          cols += `<rect x="${x}" y="${y + 1}" width="${bw}" height="${Math.max(0, hh - 2)}" rx="3" fill="${st.color}"><title>${esc(st.name)} ${c} (${Math.round((c / n) * 100)}%)</title></rect>`;
        }
      });
      return `<section class="card"><h3><i class="sw line" style="background:${substanceColor(s, pid)}"></i> ${esc(label)}</h3>
        <div class="sub2">How you felt, by hours since your first ${esc(this._noun(pid))} of the day (numbers are check-ins)</div>
        <svg viewBox="0 0 600 206" class="chart">${cols}</svg>
        <div class="sub2">Days with ${esc(this._noun(pid))} compared with days without</div>
        <svg viewBox="0 0 600 ${bars.height}" class="chart">${bars.svg}</svg></section>`;
    }).join("");

    let energy = "";
    const hours = r.energy_by_hour;
    if (hours.length) {
      const h0 = Math.min(...hours.map((h) => h.hour)), h1 = Math.max(...hours.map((h) => h.hour));
      const bw = 560 / Math.max(1, h1 - h0 + 1);
      hours.forEach((h) => {
        const share = h.n ? h.high / h.n : 0;
        const x = 30 + (h.hour - h0) * bw;
        energy += `<rect x="${x + 1}" y="${10 + (1 - share) * 120}" width="${Math.max(1, bw - 3)}" height="${share * 120}" rx="3" fill="#1baf7a"${h.n < 3 ? ' opacity=".35"' : ""}><title>${pad(h.hour % 24)}:00 · ${Math.round(share * 100)}% high energy · ${h.n} check-ins</title></rect>`;
        energy += `<text x="${x + bw / 2}" y="146" text-anchor="middle" class="tick">${pad(h.hour % 24)}</text>`;
      });
      energy += `<text x="0" y="16" class="tick">100%</text><text x="0" y="132" class="tick">0%</text>`;
    }

    // Sleep, in plain words.
    const sp = r.sleep_profile;
    const spNoun = this._noun(sp);
    const [prof, hl, tm] = profileParams(s, this._profiles, sp);
    const unit = s.items.find((i) => i.profile === sp)?.unit || "";
    const split = r.sleep_split;
    let sleepRows = "";
    if (split) {
      const usual = Math.round(split.median_level * singleDosePeak(prof, hl, tm) * referenceAmount(s, sp));
      const maxH = Math.max(1, split.less.avg_hours || 0, split.more.avg_hours || 0);
      const row = (label, g) => `<div class="sleeprow"><div class="sl-label">${label}</div>
        <div class="sl-bar">${g.avg_hours ? `<span style="width:${(g.avg_hours / maxH) * 100}%"></span>` : ""}</div>
        <div class="sl-val">${g.avg_hours ? `${fmtHours(g.avg_hours)} <span class="muted">· ${g.nights} night${g.nights === 1 ? "" : "s"}</span>` : '<span class="muted">no nights</span>'}</div></div>`;
      sleepRows = `<p class="sub2">On a typical night you go to bed with about ${usual} ${esc(unit)} of ${esc(spNoun)} still in your body.</p>
        ${row(`Less than that`, split.less)}${row(`More than that`, split.more)}`;
    }

    return `
      <div class="daynav"><h2>Patterns</h2>
        <div class="seg">${[[28, "4 weeks"], [56, "8 weeks"], [182, "6 months"], [365, "1 year"]].map(([n, l]) => `<button class="${this._patternDays === n ? "on" : ""}" data-action="pdays:${n}">${l}</button>`).join("")}</div></div>
      <p class="hint">${r.n_states} check-ins over ${r.n_days} days. These show what tends to go together, not what causes what: you may reach for coffee because you already feel tired.</p>
      <div class="grid">
        <section class="card"><h3>How you felt, depending on what you'd had</h3>
          <div class="sub2">Each line counts the check-ins that fit its description. <a href="#" data-action="goto-settings:comparisons">Change these lines</a></div>
          ${r.comparisons.length ? `<svg viewBox="0 0 600 ${comps.height}" class="chart">${comps.svg}</svg>` : `<p class="muted">No lines yet.</p>`}</section>
        <section class="card"><h3>Your typical week</h3><div class="sub2">Most common state by weekday and time of day</div>
          <svg viewBox="0 0 580 234" class="chart">${grid}</svg></section>
        ${substanceCards}
        <section class="card"><h3>Energy through the day</h3><div class="sub2">Share of check-ins with a high-energy state, by hour</div>
          ${energy ? `<svg viewBox="0 0 600 152" class="chart">${energy}</svg>` : `<p class="muted">No check-ins yet.</p>`}</section>
        <section class="card"><h3>Sleep and ${esc(spNoun)}</h3>
          <div class="sub2">How long you slept on average</div>
          ${sleepRows || `<p class="muted">Log sleep on at least two nights (Day view, Other, Sleep) to see this.</p>`}</section>
      </div>`;
  }

  // -- Substances view ------------------------------------------------
  _renderSubstances() {
    const s = this._settings;
    const ids = Object.keys(this._profiles).filter((id) => id !== "custom");
    if (!this._shownSubstances) {
      const mine = profilesInUse(s).filter((p) => p !== "custom");
      this._shownSubstances = [...new Set(["caffeine", ...mine])];
      if (this._shownSubstances.length < 3) this._shownSubstances.push(...["mph_ir", "lisdexamfetamine"].filter((x) => !this._shownSubstances.includes(x)));
    }
    const colors = {};
    ids.forEach((id, i) => (colors[id] = s.substances[id]?.color || PALETTE[i % PALETTE.length]));
    const neg = s.negligible_share;
    const shown = this._shownSubstances.filter((id) => this._profiles[id]);
    const chartEntries = shown.map((id) => {
      const [profile, hl, tm] = profileParams(s, this._profiles, id);
      return { profile, color: colors[id], hl, tm };
    });
    const rows = ids.map((id) => {
      const [p, hl, tm] = profileParams(s, this._profiles, id);
      const half = hoursUntilBelow(p, 0.5, hl, tm);
      const gone = hoursUntilBelow(p, neg, hl, tm);
      const custom = hl || tm ? ' <span class="badge">Your settings</span>' : "";
      return `<label class="subst ${shown.includes(id) ? "on" : ""}">
        <input type="checkbox" data-field="subst:${id}" ${shown.includes(id) ? "checked" : ""}>
        <i class="sw line" style="background:${colors[id]}"></i>
        <span><b>${esc(p.name)}</b> <span class="muted">${esc(p.examples)}</span>${custom}${p.verified ? "" : ' <span class="badge">Estimate</span>'}
        <span class="facts">Peaks after ${fmtHours(tm || p.tmax_h)} · half-life ${round1(hl || p.half_life_h)} h${p.half_life_range_h ? ` (people vary: ${p.half_life_range_h[0]}–${p.half_life_range_h[1]} h)` : ""}</span>
        <span class="facts">${half ? `Half gone after ${fmtHours(half)}` : ""}${gone ? ` · effectively gone after ${fmtHours(gone)}` : ""}</span>
        ${p.notes ? `<span class="facts">${esc(p.notes)}</span>` : ""}
        ${p.sources.length ? `<span class="facts">${p.sources.map((u, i) => `<a href="${esc(u)}" target="_blank" rel="noreferrer">Source ${i + 1}</a>`).join(" · ")}</span>` : ""}</span></label>`;
    }).join("");
    return `
      <div class="daynav"><h2>How long things stay in your body</h2></div>
      <section class="card wide">
        <div class="sub2">One dose of each, as a share of its own peak. The dot marks when it drops below ${Math.round(neg * 100)}% of its peak, which Daybook treats as gone. Your body clears the rest slowly, so the faint tail is real but small. Dashed lines are rougher estimates.</div>
        <div class="legend">${shown.map((id) => `<span><i class="sw line" style="background:${colors[id]}"></i>${esc(this._profiles[id].name)}</span>`).join("")}</div>
        <svg viewBox="0 0 900 260" class="chart">${substanceChart(chartEntries, { negligible: neg })}</svg>
        <p class="disclaimer">${esc(this._disclaimer)}</p>
      </section>
      <div class="substs">${rows}</div>`;
  }

  // -- Settings view --------------------------------------------------
  _ensureSubstances() {
    const d = this._draft;
    profilesInUse(d).forEach((pid, i) => {
      if (!d.substances[pid]) {
        const firstItem = d.items.find((it) => it.profile === pid);
        d.substances[pid] = { color: PALETTE[(Object.keys(d.substances).length + i) % PALETTE.length], label: pid === "caffeine" ? "" : firstItem?.name || "", half_life_h: null, tmax_h: null };
      }
    });
  }

  _renderSettings() {
    const d = this._draft;
    if (!d) return "";
    this._ensureSubstances();
    const ents = this._ha.entities || {};
    const of = (domain) => Object.keys(ents).filter((e) => e.startsWith(`${domain}.`));
    const zones = of("zone"), persons = [...of("person"), ...of("device_tracker")], schedules = of("schedule");
    const name = (id) => esc(ents[id] || id);
    const opt = (v, cur, label = v) => `<option value="${esc(v)}" ${String(v) === String(cur) ? "selected" : ""}>${label}</option>`;
    const num = (path, v, attrs = "") => `<input type="number" data-path="${path}" data-type="number" value="${v ?? ""}" ${attrs}>`;
    const txt = (path, v, attrs = "") => `<input type="text" data-path="${path}" value="${esc(v ?? "")}" ${attrs}>`;
    const inUse = profilesInUse(d);
    const profileOpts = (cur) => Object.entries(this._profiles).map(([id, p]) => opt(id, cur, `${esc(p.name)}${p.examples && id !== "custom" ? ` (${esc(p.examples)})` : ""}`)).join("");
    const usedOpts = (cur) => inUse.map((pid) => opt(pid, cur, esc(d.substances[pid]?.label || this._profiles[pid]?.name || pid))).join("");

    const states = d.states.map((st, i) => `<div class="row">
        <input type="color" data-path="states.${i}.color" value="${st.color}" aria-label="Colour">
        ${txt(`states.${i}.name`, st.name, 'aria-label="Name"')}
        <select data-path="states.${i}.energy" aria-label="Energy">${opt("high", st.energy, "High energy")}${opt("low", st.energy, "Low energy")}${opt("neutral", st.energy, "Neutral")}</select>
        <button class="icon ghost" data-action="remove:states:${i}" aria-label="Remove">×</button></div>`).join("");

    const items = d.items.map((it, i) => `<div class="block"><div class="row">
        ${txt(`items.${i}.name`, it.name, 'aria-label="Name" placeholder="Coffee"')}
        <span class="unit">${num(`items.${i}.amount`, it.amount, 'min="0" step="any" aria-label="Usual amount" placeholder="Amount"')}${txt(`items.${i}.unit`, it.unit, 'class="short" aria-label="Unit"')}</span>
        <button class="icon ghost" data-action="remove:items:${i}" aria-label="Remove">×</button></div>
        <div class="row"><label>Substance <select data-path="items.${i}.profile">${profileOpts(it.profile)}</select></label></div></div>`).join("");

    const substances = inUse.map((pid) => {
      const sub = d.substances[pid];
      const p = this._profiles[pid];
      return `<div class="block"><div class="row">
          <input type="color" data-path="substances.${pid}.color" value="${sub.color}" aria-label="Colour">
          ${txt(`substances.${pid}.label`, sub.label, `aria-label="Name in charts" placeholder="${esc(p.name)}"`)}</div>
        <div class="row"><span class="muted">${esc(p.name)}</span></div>
        <div class="row"><label>Half-life ${num(`substances.${pid}.half_life_h`, sub.half_life_h, `step="0.1" placeholder="${p.half_life_h}"`)} h</label>
          <label>Time to peak ${num(`substances.${pid}.tmax_h`, sub.tmax_h, `step="0.1" placeholder="${p.tmax_h}"`)} h</label></div>
        <label class="check"><input type="checkbox" data-action="sensor:${pid}" ${d.ha_sensors.includes(pid) ? "checked" : ""}> Show how much is in your body as a Home Assistant sensor</label></div>`;
    }).join("");

    const comparisons = d.comparisons.map((c, i) => `<div class="block">
        <div class="row">${txt(`comparisons.${i}.name`, c.name, 'aria-label="Line name"')}
          <button class="icon ghost" data-action="remove:comparisons:${i}" aria-label="Remove line">×</button></div>
        ${c.conditions.map((cond, j) => `<div class="row cond"><span class="muted lead">${j ? "and" : "Had"}</span>
          <select data-path="comparisons.${i}.conditions.${j}.present" data-type="boolsel" aria-label="Had or not">${opt("true", cond.present, "some")}${opt("false", cond.present, "no")}</select>
          <select data-path="comparisons.${i}.conditions.${j}.profile" aria-label="Substance">${usedOpts(cond.profile)}</select>
          ${num(`comparisons.${i}.conditions.${j}.from_h`, cond.from_h, 'min="0" max="48" step="0.5" class="tiny" aria-label="From hours before"')}<span class="muted">–</span>${num(`comparisons.${i}.conditions.${j}.to_h`, cond.to_h, 'min="0" max="48" step="0.5" class="tiny" aria-label="To hours before"')}<span class="muted">h before</span>
          <button class="icon ghost" data-action="rmcond:${i}:${j}" aria-label="Remove condition">×</button></div>`).join("")}
        <div class="row"><button class="ghost" data-action="addcond:${i}">Add condition</button>${c.conditions.length ? "" : '<span class="muted">No conditions: counts every check-in</span>'}</div></div>`).join("");

    const sport = d.sport_zones.map((z, i) => `<div class="block">
        <div class="row">
          ${txt(`sport_zones.${i}.activity`, z.activity, 'aria-label="Activity" placeholder="Water polo"')}
          <select data-path="sport_zones.${i}.zone" aria-label="Zone">${[...new Set([z.zone, ...zones])].map((zz) => opt(zz, z.zone, name(zz))).join("")}</select>
          <select data-path="sport_zones.${i}.person" aria-label="Person">${[...new Set([z.person, ...persons])].map((p) => opt(p, z.person, name(p))).join("")}</select>
          <button class="icon ghost" data-action="remove:sport_zones:${i}" aria-label="Remove">×</button></div>
        <div class="row"><label>At least ${num(`sport_zones.${i}.min_minutes`, z.min_minutes, 'min="1" max="600"')} min in the zone during</label>
          <select data-path="sport_zones.${i}.schedule" aria-label="Schedule">${opt("", z.schedule, "the times below")}${schedules.map((sc) => opt(sc, z.schedule, `Schedule: ${name(sc)}`)).join("")}</select></div>
        ${z.schedule ? "" : `${z.windows.map((w, j) => `<div class="row window">
            <span class="days">${WEEKDAYS.map((wd, k) => `<button class="day ${w.weekdays.includes(k) ? "on" : ""}" data-action="wday:${i}:${j}:${k}">${wd.slice(0, 2)}</button>`).join("")}</span>
            <input type="time" data-path="sport_zones.${i}.windows.${j}.from" value="${w.from}" aria-label="From"> –
            <input type="time" data-path="sport_zones.${i}.windows.${j}.to" value="${w.to}" aria-label="To">
            <button class="icon ghost" data-action="rmwin:${i}:${j}" aria-label="Remove time">×</button></div>`).join("")}
          <div class="row"><button class="ghost" data-action="addwin:${i}">Add time</button>${z.windows.length ? "" : '<span class="muted">No times: any stay counts</span>'}</div>`}
        </div>`).join("");

    const status = (ok, label) => `<span class="status ${ok ? "ok" : ""}"><i></i>${label}</span>`;

    return `
      <div class="daynav"><h2>Settings</h2><span class="spacer"></span>
        <button class="ghost" data-action="settings:reset">Discard changes</button>
        <button class="primary" data-action="settings:save">Save</button></div>
      ${this._settingsError ? `<div class="card error">${esc(this._settingsError)}</div>` : ""}
      <div class="grid">
        <section class="card"><h3>How you feel</h3><div class="sub2">The buttons you press to check in. High and low energy are used for the energy chart.</div>
          ${states}<button class="ghost" data-action="add:states">Add state</button></section>
        <section class="card"><h3>What you take</h3><div class="sub2">Coffee, tea, meds, anything. Pick the substance so Daybook can draw how long it stays in your body.</div>
          ${items}<button class="ghost" data-action="add:items">Add</button></section>
        <section class="card"><h3>Substances</h3><div class="sub2">How each substance is shown. Leave half-life and time to peak empty to use published averages.</div>
          ${substances || '<p class="muted">Add something you take first.</p>'}
          <div class="row"><label>Treat as gone below ${num("negligible_share", Math.round(d.negligible_share * 100), 'min="1" max="50" data-scale="100"')} % of one usual dose's peak</label></div></section>
        <section class="card" id="comparisons"><h3>Comparison lines</h3><div class="sub2">The lines in "How you felt, depending on what you'd had" on the Patterns tab. Each condition looks at a window before every check-in, for example "had some caffeine 1–4 h before".</div>
          ${comparisons}<button class="ghost" data-action="add:comparisons">Add line</button></section>
        <section class="card"><h3>Sport places</h3>
          <div class="sub2">Uses zones and people from Home Assistant. A stay becomes a suggested sport entry you confirm.</div>
          ${zones.length || d.sport_zones.length ? sport + `<button class="ghost" data-action="add:sport_zones">Add place</button>` : `<p class="muted">No zones found. Create them in Home Assistant under Settings, Areas, labels and zones.</p>`}
          <div class="row"><label>Ask on this phone <select data-path="notify_service">${opt("", d.notify_service, "Don't ask")}${[...new Set([d.notify_service, ...(this._ha.notify || [])].filter(Boolean))].filter((n) => n.startsWith("mobile_app_")).map((n) => opt(n, d.notify_service, n.replace("mobile_app_", ""))).join("")}</select></label></div></section>
        <section class="card"><h3>Days and charts</h3>
          <div class="row"><label>A new day starts at ${num("day_start_hour", d.day_start_hour, 'min="0" max="8"')} :00</label></div>
          <div class="row"><label>Timeline from ${num("axis_start_hour", d.axis_start_hour, 'min="0" max="12"')} :00</label>
            <label>to ${num("axis_end_hour", d.axis_end_hour, 'min="16" max="32"')} :00</label><span class="muted">26 = 02:00</span></div>
          <div class="row"><label>Hide patterns until there are ${num("min_samples", d.min_samples, 'min="1" max="100"')} check-ins</label></div>
          <div class="row"><label>Sleep chart uses <select data-path="sleep_profile">${usedOpts(d.sleep_profile)}</select></label></div></section>
        <section class="card"><h3>Home Assistant</h3>
          <div class="row">${status(this._ha.connected, this._ha.connected ? "Connected to Home Assistant" : "Not connected to Home Assistant")}
            ${status(this._ha.mqtt, this._ha.mqtt ? "Connected to MQTT" : "MQTT not connected")}</div>
          <div class="sub2">Buttons appear in Home Assistant through MQTT. From an automation or an ESPHome device, publish to <code>daybook/log</code>, for example <code>{"kind": "intake", "item": "coffee"}</code>.</div></section>
        <section class="card"><h3>Your data</h3><div class="sub2">Stored only inside this app. It's included in Home Assistant backups.</div>
          <div class="row"><button class="ghost" data-action="export:json">Export JSON</button><button class="ghost" data-action="export:csv">Export CSV</button>
            <button class="ghost" data-action="export:settings">Export settings</button>
            <label class="filebtn">Import settings<input type="file" accept="application/json" data-field="import"></label></div></section>
      </div>`;
  }

  _setPath(path, raw, type, scale) {
    const parts = path.split(".");
    let obj = this._draft;
    for (let i = 0; i < parts.length - 1; i++) obj = obj[parts[i]];
    const key = parts[parts.length - 1];
    let value = raw;
    if (type === "number") value = raw === "" ? null : Number(raw) / (scale || 1);
    if (type === "boolsel") value = raw === "true";
    obj[key] = value;
    // A new entry gets its id from its name; existing ids never change.
    if (key === "name" && obj._new) obj.id = this._uniqueId(parts[0], slug(value), obj);
  }

  _uniqueId(list, base, self) {
    const taken = new Set(this._draft[list].filter((x) => x !== self).map((x) => x.id));
    let id = base, n = 2;
    while (taken.has(id)) id = `${base}_${n++}`;
    return id;
  }

  async _saveSettings() {
    const payload = clone(this._draft);
    for (const list of ["states", "items", "comparisons", "sport_zones"]) payload[list].forEach((x) => delete x._new);
    const used = new Set(profilesInUse(payload));
    for (const pid of Object.keys(payload.substances)) if (!used.has(pid)) delete payload.substances[pid];
    payload.ha_sensors = payload.ha_sensors.filter((p) => used.has(p));
    try {
      const res = await this._ws({ type: "daybook/settings/set", settings: payload });
      this._settings = res.settings;
      this._draft = clone(res.settings);
      this._settingsError = null;
      this._shownSubstances = null;
      this._showToast("Settings saved");
    } catch (err) {
      this._settingsError = err.message || String(err);
    }
    this._render();
  }

  // -- Dialog ---------------------------------------------------------
  _openDialog(entry) {
    this._dialog = clone(entry);
    this._renderDialog();
  }

  _renderDialog() {
    const e = this._dialog;
    if (!e) {
      this._overlay.innerHTML = "";
      this._overlay.classList.remove("open");
      return;
    }
    const s = this._settings;
    const isNew = !e.id;
    const opts = (list, cur) => list.map((x) => `<option value="${x.id}" ${x.id === cur ? "selected" : ""}>${esc(x.name)}</option>`).join("");
    const activities = [...new Set([...s.sport_zones.map((z) => z.activity), ...this._entries.filter((x) => x.kind === "sport" && x.item).map((x) => x.item)])];
    let item = "";
    if (e.kind === "state") item = `<label>How you felt<select id="d-item">${opts(s.states, e.item)}</select></label>`;
    if (e.kind === "intake") {
      const it = s.items.find((x) => x.id === e.item);
      item = `<label>What<select id="d-item">${opts(s.items, e.item)}</select></label>
        <label>Amount<span class="unit"><input id="d-amount" type="number" min="0" step="any" value="${e.value?.amount ?? it?.amount ?? ""}"> ${esc(e.value?.unit || it?.unit || "")}</span></label>`;
    }
    if (e.kind === "sport") item = `<label>Activity<input id="d-item" list="d-acts" value="${esc(e.item || "")}"><datalist id="d-acts">${activities.map((a) => `<option value="${esc(a)}">`).join("")}</datalist></label>`;
    const hasEnd = e.kind === "sport" || e.kind === "sleep";
    const kindName = { state: "check-in", intake: "intake", sport: "sport", sleep: "sleep", note: "note" }[e.kind];
    const title = isNew ? `Add ${kindName}` : `Edit ${itemName(s, e.kind, e.item)}`;
    this._overlay.classList.add("open");
    this._overlay.innerHTML = `<div class="dialog" role="dialog" aria-label="${esc(title)}">
      <h3>${esc(title)}</h3>
      ${item}
      <label>${hasEnd ? "Start" : "Time"}<input id="d-start" type="datetime-local" value="${toInput(e.start)}"></label>
      ${hasEnd ? `<label>End<input id="d-end" type="datetime-local" value="${e.end ? toInput(e.end) : ""}"></label>` : ""}
      ${isNew ? "" : `<label>Status<select id="d-status">${["confirmed", "draft", "rejected"].map((st) => `<option value="${st}" ${st === e.status ? "selected" : ""}>${{ confirmed: "Confirmed", draft: "Suggested, not confirmed", rejected: "Dismissed" }[st]}</option>`).join("")}</select></label>`}
      <label>Note<textarea id="d-note" rows="2">${esc(e.note || "")}</textarea></label>
      ${isNew ? "" : `<p class="muted small">Logged from ${esc(e.source)} at ${fmtTime(e.created)}${e.updated !== e.created ? `, last changed ${new Date(e.updated * 1000).toLocaleString()}` : ""}</p>`}
      <div class="actions">${isNew ? "" : `<button class="danger ghost" data-action="dlg:delete">Delete</button>`}<span class="spacer"></span>
        <button class="ghost" data-action="dlg:cancel">Cancel</button><button class="primary" data-action="dlg:save">Save</button></div></div>`;
  }

  async _saveDialog() {
    const e = this._dialog;
    const $ = (id) => this._overlay.querySelector(id);
    const value = { ...(e.value || {}) };
    if (e.kind === "intake") {
      const raw = $("#d-amount").value;
      if (raw === "") delete value.amount;
      else value.amount = Number(raw);
      const item = s => s.items.find((x) => x.id === $("#d-item").value);
      value.unit = item(this._settings)?.unit || value.unit || "";
    }
    const msg = { start: fromInput($("#d-start").value), note: $("#d-note").value, value };
    if ($("#d-item")) msg.item = $("#d-item").value || null;
    if ($("#d-end")) msg.end = fromInput($("#d-end").value);
    if ($("#d-status")) msg.status = $("#d-status").value;
    if (!msg.start) return this._showToast("Enter a time");
    if (msg.end && msg.end < msg.start) return this._showToast("End is before start");
    try {
      if (e.id) await this._ws({ type: "daybook/entries/update", entry_id: e.id, ...msg });
      else await this._ws({ type: "daybook/entries/create", kind: e.kind, ...msg });
      this._dialog = null;
      this._renderDialog();
      await this._load();
    } catch (err) {
      this._showToast(err.message || String(err));
    }
  }

  // -- Quick logging and toast ---------------------------------------
  async _quick(kind, item) {
    if (!this._isToday()) {
      const noon = this._midnight(this._dayStart) + 12 * HOUR;
      return this._openDialog({ kind, item, start: noon, value: {}, note: "" });
    }
    try {
      const saved = await this._ws({ type: "daybook/entries/create", kind, item, value: {} });
      this._showToast(`${itemName(this._settings, kind, item)} at ${fmtTime(saved.start)}`, saved);
      await this._load();
    } catch (err) {
      this._showToast(err.message || String(err));
    }
  }

  _showToast(text, entry = null, restoreId = null) {
    this._toast = entry;
    clearTimeout(this._toastTimer);
    const buttons = entry
      ? `<button data-action="toast:undo">Undo</button><button data-action="toast:shift">−15 min</button><button data-action="toast:edit">Edit</button>`
      : restoreId ? `<button data-action="restore:${restoreId}">Restore</button>` : "";
    this._toastEl.innerHTML = `<span>${esc(text)}</span>${buttons}`;
    this._toastEl.classList.add("open");
    this._toastTimer = setTimeout(() => this._toastEl.classList.remove("open"), entry || restoreId ? 8000 : 4000);
  }

  async _toastAction(what) {
    const e = this._toast;
    if (!e) return;
    try {
      if (what === "undo") {
        await this._ws({ type: "daybook/entries/delete", entry_id: e.id });
        this._showToast("Removed");
      } else if (what === "shift") {
        const saved = await this._ws({ type: "daybook/entries/update", entry_id: e.id, start: e.start - 15 * 60 });
        this._showToast(`Moved to ${fmtTime(saved.start)}`, saved);
      } else if (what === "edit") {
        this._toastEl.classList.remove("open");
        this._openDialog(e);
        return;
      }
      await this._load();
    } catch (err) {
      this._showToast(err.message || String(err));
    }
  }

  // -- Export / import -----------------------------------------------
  async _export(kind) {
    let blob, name;
    const stamp = new Date().toISOString().slice(0, 10);
    if (kind === "settings") {
      blob = new Blob([JSON.stringify(this._settings, null, 2)], { type: "application/json" });
      name = `daybook-settings-${stamp}.json`;
    } else {
      const all = await this._ws({ type: "daybook/entries/list" });
      if (kind === "json") {
        blob = new Blob([JSON.stringify(all, null, 2)], { type: "application/json" });
        name = `daybook-${stamp}.json`;
      } else {
        const iso = (t) => (t ? new Date(t * 1000).toISOString() : "");
        const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
        const lines = ["id,kind,item,start,end,status,source,note,value"];
        for (const e of all) lines.push([e.id, e.kind, e.item, iso(e.start), iso(e.end), e.status, e.source, e.note, JSON.stringify(e.value)].map(q).join(","));
        blob = new Blob([lines.join("\n")], { type: "text/csv" });
        name = `daybook-${stamp}.csv`;
      }
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  async _import(file) {
    try {
      const parsed = JSON.parse(await file.text());
      this._draft = { ...clone(this._settings), ...parsed };
      this._settingsError = null;
      this._showToast("Settings loaded. Check them, then save.");
    } catch (err) {
      this._settingsError = `Couldn't read that file: ${err.message}`;
    }
    this._render();
  }

  // -- Events ---------------------------------------------------------
  _onField(ev, live = false) {
    const t = ev.target;
    if (t.dataset.path && this._draft) {
      const v = t.dataset.type === "bool" ? t.checked : t.value;
      this._setPath(t.dataset.path, v, t.dataset.type, Number(t.dataset.scale) || 1);
      if (!live && /(\.schedule|\.profile)$/.test(t.dataset.path)) this._render();
      return;
    }
    if (live) return;
    const f = t.dataset.field;
    if (!f) return;
    if (f === "align") { this._weekAlign = t.value; this._render(); }
    if (f.startsWith("subst:")) {
      const id = f.slice(6);
      this._shownSubstances = t.checked ? [...this._shownSubstances, id] : this._shownSubstances.filter((x) => x !== id);
      this._render();
    }
    if (f === "import" && t.files[0]) this._import(t.files[0]);
  }

  _onClick(ev) {
    const el = ev.target.closest("[data-action]");
    if (!el) {
      if (ev.target === this._overlay) { this._dialog = null; this._renderDialog(); }
      return;
    }
    if (el.tagName === "A") ev.preventDefault();
    const [action, a, b, c] = el.dataset.action.split(":");
    const fail = (err) => this._showToast(err.message || String(err));
    const run = {
      tab: () => { this._view = a; if (a === "settings") this._draft = null; this._load(); },
      "goto-settings": () => {
        this._view = "settings"; this._draft = null;
        this._load().then(() => this.shadowRoot.getElementById(a)?.scrollIntoView({ behavior: "smooth" }));
      },
      day: () => {
        this._dayStart = a === "today" ? this._journalDayStart(Date.now() / 1000) : this._shiftDay(this._dayStart, Number(a));
        this._load();
      },
      week: () => {
        const latest = this._journalDayStart(Date.now() / 1000);
        this._dayStart = Math.min(latest, this._shiftDay(this._dayStart, Number(a) * this._weekDays));
        this._load();
      },
      goto: () => { this._dayStart = Number(a); this._view = "today"; this._load(); },
      weekdays: () => { this._weekDays = Number(a); this._load(); },
      pdays: () => { this._patternDays = Number(a); this._load(); },
      quick: () => this._quick(a, b),
      new: () => {
        const now = Date.now() / 1000;
        const start = this._isToday() ? now : this._midnight(this._dayStart) + 12 * HOUR;
        const base = { kind: a, item: null, start, end: null, value: {}, note: "" };
        if (a === "sport") { base.item = this._settings.sport_zones[0]?.activity || "Sport"; base.start = start - HOUR; base.end = start; }
        if (a === "sleep") { const mid = this._midnight(this._dayStart); base.start = mid - HOUR; base.end = mid + 7 * HOUR; }
        this._openDialog(base);
      },
      edit: () => { const e = this._entries.find((x) => x.id === a); if (e) this._openDialog(e); },
      confirm: () => this._ws({ type: "daybook/entries/update", entry_id: a, status: "confirmed" }).then(() => this._load()).catch(fail),
      reject: () => this._ws({ type: "daybook/entries/update", entry_id: a, status: "rejected" }).then(() => this._load()).catch(fail),
      dlg: async () => {
        if (a === "cancel") { this._dialog = null; this._renderDialog(); }
        if (a === "save") await this._saveDialog();
        if (a === "delete") {
          const id = this._dialog.id;
          try {
            await this._ws({ type: "daybook/entries/delete", entry_id: id });
            this._dialog = null;
            this._renderDialog();
            this._showToast("Deleted", null, id);
            await this._load();
          } catch (err) { fail(err); }
        }
      },
      restore: () => this._ws({ type: "daybook/entries/restore", entry_id: a }).then(() => { this._showToast("Restored"); this._load(); }).catch(fail),
      toast: () => this._toastAction(a),
      settings: () => { if (a === "save") this._saveSettings(); else { this._draft = clone(this._settings); this._settingsError = null; this._render(); } },
      sensor: () => {
        const list = this._draft.ha_sensors;
        this._draft.ha_sensors = list.includes(a) ? list.filter((x) => x !== a) : [...list, a];
      },
      add: () => {
        const d = this._draft;
        const firstProfile = profilesInUse(d)[0] || "caffeine";
        const fresh = {
          states: { name: "New state", color: PALETTE[d.states.length % PALETTE.length], energy: "high" },
          items: { name: "New", profile: "custom", amount: null, unit: "mg" },
          comparisons: { name: "New line", conditions: [{ profile: firstProfile, present: true, from_h: 0, to_h: 4 }] },
          sport_zones: {
            activity: "Sport",
            zone: Object.keys(this._ha.entities || {}).find((e) => e.startsWith("zone.") && e !== "zone.home") || "zone.home",
            person: Object.keys(this._ha.entities || {}).find((e) => e.startsWith("person.")) || "person.me",
            min_minutes: 60, windows: [], schedule: "",
          },
        }[a];
        const item = { ...fresh, _new: true };
        item.id = this._uniqueId(a, slug(item.name || item.activity), item);
        d[a].push(item);
        this._render();
      },
      remove: () => { this._draft[a].splice(Number(b), 1); this._render(); },
      addcond: () => {
        this._draft.comparisons[Number(a)].conditions.push({ profile: profilesInUse(this._draft)[0] || "caffeine", present: true, from_h: 0, to_h: 4 });
        this._render();
      },
      rmcond: () => { this._draft.comparisons[Number(a)].conditions.splice(Number(b), 1); this._render(); },
      addwin: () => { this._draft.sport_zones[Number(a)].windows.push({ weekdays: [1, 4], from: "19:00", to: "21:00" }); this._render(); },
      rmwin: () => { this._draft.sport_zones[Number(a)].windows.splice(Number(b), 1); this._render(); },
      wday: () => {
        const w = this._draft.sport_zones[Number(a)].windows[Number(b)];
        const k = Number(c);
        w.weekdays = w.weekdays.includes(k) ? w.weekdays.filter((x) => x !== k) : [...w.weekdays, k].sort();
        this._render();
      },
      export: () => this._export(a).catch(fail),
    }[action];
    if (run) run();
  }
}

const STYLE = `
:host { --bg:#f7f7f5; --card:#ffffff; --text:#1d1d1b; --muted:#6e6d68; --line:rgba(0,0,0,.1); --accent:#2a78d6; --onaccent:#fff;
  --chip:#f0efec; --danger:#c43c3c; display:block; min-height:100vh; background:var(--bg); color:var(--text);
  font-family:system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; --gap:16px; }
@media (prefers-color-scheme: dark) {
  :host { --bg:#111111; --card:#1b1b1b; --text:#ecebe6; --muted:#9e9d96; --line:rgba(255,255,255,.1); --accent:#4b93e8; --chip:#262626; --danger:#e56b6b; }
}
.toolbar { display:flex; align-items:center; gap:8px; min-height:52px; padding:0 14px; background:var(--card);
  border-bottom:1px solid var(--line); position:sticky; top:0; z-index:2; flex-wrap:wrap; }
.title { font-size:18px; font-weight:500; margin-right:auto; }
nav { display:flex; gap:2px; overflow-x:auto; }
.tab { background:none; border:none; color:inherit; padding:8px 12px; border-radius:18px; font:inherit; font-size:14px; cursor:pointer; color:var(--muted); }
.tab.active { background:var(--chip); color:var(--text); }
main { max-width:1240px; margin:0 auto; padding:var(--gap); }
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 480px), 1fr)); gap:var(--gap); align-items:start; }
.card { background:var(--card); border-radius:14px; border:1px solid var(--line); padding:16px 18px; box-sizing:border-box; min-width:0; }
.card.wide, .card.error { margin-bottom:var(--gap); }
.card.error { color:var(--danger); }
h2 { font-size:20px; font-weight:500; margin:0; }
h3 { font-size:16px; font-weight:500; margin:0 0 10px; display:flex; align-items:center; gap:8px; }
.sub2, .hint, .muted { color:var(--muted); font-size:13px; }
.sub2 { margin:-4px 0 10px; }
.hint { margin:0 0 var(--gap); }
.small { font-size:12px; }
a { color:var(--accent); }
code { font-size:12px; background:var(--chip); padding:1px 5px; border-radius:4px; }
.daynav { display:flex; align-items:center; gap:8px; margin:0 0 var(--gap); flex-wrap:wrap; }
.spacer { flex:1; }
button { font:inherit; font-size:14px; color:var(--text); background:var(--card); border:1px solid var(--line); border-radius:18px; padding:6px 14px; cursor:pointer; }
button:hover { border-color:var(--muted); }
button:disabled { opacity:.4; cursor:default; }
button.ghost { background:none; }
button.primary { background:var(--accent); color:var(--onaccent); border-color:var(--accent); }
button.danger { color:var(--danger); }
button.icon { width:34px; height:34px; padding:0; font-size:20px; line-height:1; flex:none; }
.group { margin:14px 0 0; }
.glabel { font-size:12px; color:var(--muted); margin-bottom:6px; }
.chips { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.chip { display:inline-flex; align-items:center; gap:8px; padding:9px 14px; }
.chip.state { border-color:color-mix(in srgb, var(--c) 45%, var(--line)); }
.chip.state:hover { background:color-mix(in srgb, var(--c) 12%, transparent); }
.chip.state .dot { background:var(--c); }
.chip .sub { color:var(--muted); font-size:12px; }
.took { margin-top:8px; }
.dot { width:10px; height:10px; border-radius:50%; display:inline-block; flex:none; }
svg { width:100%; height:auto; display:block; overflow:visible; }
svg text { font-size:11px; fill:var(--text); }
svg .tick, svg .muted { fill:var(--muted); font-size:11px; }
svg .lbl { font-size:12px; }
svg .onbar { fill:#fff; font-size:11px; }
.daylabel { cursor:pointer; }
.legend { display:flex; flex-wrap:wrap; gap:6px 14px; font-size:12px; color:var(--muted); margin:4px 0 8px; }
.legend.now { color:var(--text); font-size:13px; }
.legend span { display:inline-flex; align-items:center; gap:5px; }
.sw { width:12px; height:8px; border-radius:2px; display:inline-block; flex:none; }
.sw.mark { width:5px; height:11px; border-radius:2px; }
.sw.line { height:3px; width:14px; }
.entries { list-style:none; margin:12px 0 0; padding:0; }
.entries li { display:flex; align-items:center; gap:10px; padding:9px 4px; border-top:1px solid var(--line); cursor:pointer; }
.entries li:hover { background:var(--chip); }
.entries li.draft { opacity:.7; }
.entries .time { width:92px; flex:none; font-variant-numeric:tabular-nums; color:var(--muted); font-size:13px; }
.entries .what { flex:1; display:flex; flex-direction:column; }
.entries .note, .entries .detail { font-size:13px; color:var(--muted); }
.entries .empty { cursor:default; color:var(--muted); }
.badge { font-size:11px; padding:1px 7px; border-radius:9px; background:var(--chip); color:var(--muted); font-weight:400; }
.drafts { margin:8px 0; display:flex; flex-direction:column; gap:6px; }
.draft { display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding:8px 10px; border-radius:10px; border:1px dashed ${SPORT_COLOR}; }
.draft span { flex:1; font-size:14px; }
.controls { display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin-bottom:6px; }
.seg { display:inline-flex; align-items:center; gap:4px; }
.seg button.on { border-color:var(--accent); color:var(--accent); }
.chart { margin:4px 0 12px; }
.disclaimer { font-size:12px; color:var(--muted); margin:8px 0 0; }
.substs { display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap:10px; }
.subst { display:flex; gap:8px; align-items:flex-start; font-size:13px; padding:10px; border-radius:12px; border:1px solid var(--line); background:var(--card); cursor:pointer; }
.subst .sw { margin-top:7px; }
.subst > span { display:flex; flex-direction:column; gap:3px; }
.facts { color:var(--muted); font-size:12px; }
.sleeprow { display:grid; grid-template-columns:minmax(0, 1.3fr) minmax(0, 1fr) minmax(0, 1fr); gap:10px; align-items:center; padding:8px 0; border-top:1px solid var(--line); font-size:14px; }
.sl-bar { height:12px; background:var(--chip); border-radius:6px; overflow:hidden; }
.sl-bar span { display:block; height:100%; background:#2a78d6; border-radius:6px; }
.status { display:inline-flex; align-items:center; gap:6px; font-size:13px; color:var(--muted); }
.status i { width:8px; height:8px; border-radius:50%; background:var(--danger); }
.status.ok i { background:#1baf7a; }
.row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:6px 0; }
.block { border-top:1px solid var(--line); padding:8px 0; }
input, select, textarea { font:inherit; font-size:14px; color:var(--text); background:var(--card); border:1px solid var(--line); border-radius:8px; padding:6px 8px; box-sizing:border-box; }
input[type=text] { flex:1; min-width:120px; }
input[type=number] { width:76px; }
input.tiny { width:56px; }
.row.cond { gap:6px; }
.row.cond .lead { width:30px; }
input.short { width:56px; flex:none; min-width:0; }
input[type=color] { width:36px; height:32px; padding:2px; }
.unit { display:inline-flex; align-items:center; gap:6px; }
label { display:inline-flex; align-items:center; gap:6px; font-size:14px; }
label.check { margin-top:6px; }
.days { display:inline-flex; gap:3px; }
.day { padding:4px 0; width:32px; font-size:12px; }
.day.on { background:var(--accent); color:var(--onaccent); border-color:var(--accent); }
.filebtn { border:1px solid var(--line); border-radius:18px; padding:6px 14px; cursor:pointer; }
.filebtn input { display:none; }
.overlay { position:fixed; inset:0; background:rgba(0,0,0,.4); display:none; align-items:center; justify-content:center; z-index:10; padding:16px; }
.overlay.open { display:flex; }
.dialog { background:var(--card); border-radius:16px; padding:20px; width:min(440px, 100%); max-height:90vh; overflow:auto; display:flex; flex-direction:column; gap:12px; }
.dialog label { display:flex; flex-direction:column; align-items:stretch; gap:4px; font-size:13px; color:var(--muted); }
.dialog label .unit { color:var(--text); }
.dialog input, .dialog select, .dialog textarea { width:100%; }
.dialog .unit input { width:110px; }
.actions { display:flex; gap:8px; align-items:center; margin-top:4px; }
.toast { position:fixed; left:50%; bottom:24px; transform:translate(-50%, 140%); transition:transform .2s ease, visibility .2s; z-index:11; visibility:hidden;
  background:var(--text); color:var(--card); border-radius:12px; padding:10px 14px; display:flex; gap:10px; align-items:center; font-size:14px; max-width:calc(100% - 32px); }
.toast.open { transform:translate(-50%, 0); visibility:visible; }
.toast button { background:none; color:inherit; border-color:rgba(127,127,127,.6); padding:4px 10px; }
@media (max-width: 700px) {
  main { padding:12px; --gap:12px; }
  .tab { padding:8px; }
  .sleeprow { grid-template-columns:1fr; gap:4px; }
}
`;

customElements.define("daybook-app", DaybookApp);
