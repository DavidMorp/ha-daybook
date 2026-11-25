// Daybook panel. Plain web component, no build step, no external requests.
import { HOUR, caffeineAt, caffeineDoses, medLevel, medDoses } from "./pk.js";
import {
  CAFFEINE_COLOR, SPORT_COLOR, esc, fmtTime, fmtDuration, itemName, stateColor,
  timelineRow, hourAxis, clockLabel, stackedBars, substanceChart, hoursBelow,
} from "./charts.js";

const DAY = 24 * HOUR;
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MED_COLORS = ["#d4537e", "#534ab7", "#0f6e56", "#993c1d"];
const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const VIEWS = [
  ["today", "Day"],
  ["week", "Week"],
  ["patterns", "Patterns"],
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

class DaybookPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._view = "today";
    this._dayStart = null; // epoch seconds, start of the journal day on view
    this._entries = [];
    this._weekDays = 7;
    this._weekAlign = "clock";
    this._weekMed = null;
    this._patternDays = 56;
    this._shownSubstances = null;
    this._dialog = null;
    this._toast = null;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    if (first) this._init();
  }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menu) this._menu.narrow = narrow;
    this.toggleAttribute("narrow", !!narrow);
  }

  set panel(_p) {}

  disconnectedCallback() {
    if (this._unsub) this._unsub.then((u) => u()).catch(() => {});
    this._unsub = null;
    this._ready = false;
  }

  connectedCallback() {
    if (this._hass && !this._ready) this._init();
  }

  // -- setup ----------------------------------------------------------
  async _init() {
    if (this._ready) return;
    this._ready = true;
    this._shell();
    try {
      const [s, subs] = await Promise.all([
        this._ws({ type: "daybook/settings/get" }),
        this._ws({ type: "daybook/substances" }),
      ]);
      this._settings = s.settings;
      this._profiles = subs.profiles;
      this._disclaimer = subs.disclaimer;
      this._dayStart = this._journalDayStart(Date.now() / 1000);
      this._unsub = this._hass.connection.subscribeMessage((msg) => this._onChange(msg), { type: "daybook/subscribe" });
      await this._load();
    } catch (err) {
      this._main.innerHTML = `<div class="card error">${esc(err.message || err)}</div>`;
    }
  }

  _shell() {
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <div class="toolbar"><span class="menu"></span><div class="title">Daybook</div>
        <nav>${VIEWS.map(([id, label]) => `<button class="tab" data-action="tab:${id}">${label}</button>`).join("")}</nav></div>
      <main></main><div class="overlay"></div><div class="toast"></div>`;
    this._main = this.shadowRoot.querySelector("main");
    this._overlay = this.shadowRoot.querySelector(".overlay");
    this._toastEl = this.shadowRoot.querySelector(".toast");
    this._menu = document.createElement("ha-menu-button");
    this._menu.hass = this._hass;
    this._menu.narrow = this._narrow;
    this.shadowRoot.querySelector(".menu").appendChild(this._menu);
    this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
    this.shadowRoot.addEventListener("change", (e) => this._onField(e));
    this.shadowRoot.addEventListener("input", (e) => this._onField(e, true));
    this._markTab();
  }

  _markTab() {
    this.shadowRoot.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.action === `tab:${this._view}`));
  }

  async _ws(msg) {
    return this._hass.callWS(msg);
  }

  _onChange(msg) {
    if (msg.changed === "settings" && this._view === "settings") return;
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
      } else if (this._view === "settings" && !this._draft) {
        this._draft = clone(this._settings);
      }
    } catch (err) {
      this._showToast(err.message || String(err));
    }
    this._render();
  }

  _render() {
    this._markTab();
    const views = { today: () => this._renderToday(), week: () => this._renderWeek(), patterns: () => this._renderPatterns(), settings: () => this._renderSettings() };
    this._main.innerHTML = views[this._view]();
    this._renderDialog();
  }

  // -- Day view -------------------------------------------------------
  _dayEntries() {
    const end = this._shiftDay(this._dayStart, 1);
    return this._entries.filter((e) => e.start >= this._dayStart && e.start < end);
  }

  _renderToday() {
    const s = this._settings;
    const day = this._dayEntries();
    const date = new Date(this._dayStart * 1000);
    const label = date.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
    const now = Date.now() / 1000;
    const caffNow = caffeineAt(caffeineDoses(this._entries), now, this._profiles, s);
    const drafts = day.filter((e) => e.status === "draft");

    const medRows = s.meds.length
      ? s.meds.map((m) => {
          const recs = day.filter((e) => e.kind === "med" && e.item === m.id && e.status === "confirmed");
          const taken = recs.filter((e) => (e.value?.status ?? "taken") === "taken");
          const skipped = recs.find((e) => e.value?.status === "skipped");
          const status = taken.length
            ? `Taken ${taken.map((e) => fmtTime(e.start)).join(", ")}`
            : skipped ? "Skipped" : "Not recorded";
          return `<div class="medrow"><span class="dot" style="background:${m.color}"></span>
            <span class="medname">${esc(m.name)}<span class="sub">${status}</span></span>
            <button data-action="quick:med:${m.id}:taken">Taken</button>
            <button class="ghost" data-action="quick:med:${m.id}:skipped">Skipped</button></div>`;
        }).join("")
      : `<p class="muted">Add your meds in <a href="#" data-action="tab:settings">Settings</a> to record doses and skipped days.</p>`;

    const end = this._shiftDay(this._dayStart, 1);
    const mid = this._midnight(this._dayStart);
    const tFrom = mid + s.axis_start_hour * HOUR;
    const tTo = mid + s.axis_end_hour * HOUR;
    const W = 680, x0 = 8, w = W - 16;

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
          <div class="group"><div class="glabel">Caffeine</div><div class="chips">
            ${s.drinks.map((d) => `<button class="chip" data-action="quick:caffeine:${d.id}"><span class="dot" style="background:${CAFFEINE_COLOR}"></span>${esc(d.name)} <span class="sub">${Math.round(d.mg)} mg</span></button>`).join("")}
          </div></div>
          <div class="group"><div class="glabel">Meds</div>${medRows}</div>
          <div class="group"><div class="glabel">Other</div><div class="chips">
            <button class="chip" data-action="new:sport">Sport</button>
            <button class="chip" data-action="new:sleep">Sleep</button>
            <button class="chip" data-action="new:note">Note</button>
          </div></div>
        </section>
        <section class="card">
          <div class="cardhead"><h3>Timeline</h3>${this._isToday() ? `<span class="metric">${Math.round(caffNow)} mg caffeine now</span>` : ""}</div>
          ${this._legend()}
          <svg viewBox="0 0 ${W} 134" class="strip" role="img" aria-label="Timeline of the day">
            ${hourAxis({ tFrom, tTo, x0, w, y: 12, y2: 130, labeler: clockLabel })}
            ${timelineRow({ entries: this._entries, tFrom, tTo, x0, w, y: 22, h: 108, settings: s, profiles: this._profiles })}
            ${this._isToday() && now > tFrom && now < tTo ? `<line x1="${x0 + ((now - tFrom) / (tTo - tFrom)) * w}" x2="${x0 + ((now - tFrom) / (tTo - tFrom)) * w}" y1="18" y2="130" stroke="var(--primary-color)" stroke-width="1.5"/>` : ""}
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
    let color = "var(--secondary-text-color)";
    let detail = "";
    if (e.kind === "state") color = stateColor(s, e.item);
    if (e.kind === "caffeine") { color = CAFFEINE_COLOR; detail = `${Math.round(e.value?.mg || 0)} mg`; }
    if (e.kind === "med") {
      color = s.meds.find((m) => m.id === e.item)?.color || color;
      detail = e.value?.status === "skipped" ? "Skipped" : e.value?.dose ? `${e.value.dose} ${esc(e.value.unit || "")}` : "Taken";
    }
    if (e.kind === "sport") { color = SPORT_COLOR; detail = e.end ? fmtDuration(e.end - e.start) : ""; }
    if (e.kind === "sleep") detail = e.end ? fmtDuration(e.end - e.start) : "";
    const time = e.end ? `${fmtTime(e.start)}–${fmtTime(e.end)}` : fmtTime(e.start);
    return `<li data-action="edit:${e.id}" class="${e.status}">
      <span class="time">${time}</span><span class="dot" style="background:${color}"></span>
      <span class="what">${esc(itemName(s, e.kind, e.item))}${e.note ? `<span class="note">${esc(e.note)}</span>` : ""}</span>
      <span class="detail">${detail}${e.status === "draft" ? ' <span class="badge">Draft</span>' : ""}</span></li>`;
  }

  _legend(extra = "") {
    const s = this._settings;
    return `<div class="legend">
      ${s.states.map((st) => `<span><i class="sw round" style="background:${st.color}"></i>${esc(st.name)}</span>`).join("")}
      <span><i class="sw" style="background:${CAFFEINE_COLOR};opacity:.5"></i>Caffeine</span>
      ${s.meds.map((m) => `<span><i class="sw line" style="background:${m.color}"></i>${esc(m.name)}</span>`).join("")}
      <span><i class="sw" style="background:${SPORT_COLOR};opacity:.35"></i>Sport</span>${extra}</div>`;
  }

  // -- Week view ------------------------------------------------------
  _renderWeek() {
    const s = this._settings;
    const days = [];
    for (let i = this._weekDays - 1; i >= 0; i--) days.push(this._shiftDay(this._dayStart, -i));
    const medId = this._weekMed || s.meds[0]?.id;
    const narrow = !!this._narrow;
    const W = narrow ? 400 : 680, L = narrow ? 50 : 78, R = narrow ? 0 : 64, w = W - L - R, RH = this._weekDays > 7 ? 38 : 50, TOP = 24;
    const height = TOP + days.length * RH + 6;
    let rows = "";
    let axis = "";

    if (this._weekAlign === "clock") {
      const mid = this._midnight(days[0]);
      axis = hourAxis({ tFrom: mid + s.axis_start_hour * HOUR, tTo: mid + s.axis_end_hour * HOUR, x0: L, w, y: 12, y2: height, labeler: clockLabel, step: narrow ? 6 : 3 });
    } else {
      axis = hourAxis({ tFrom: -3 * HOUR, tTo: 15 * HOUR, x0: L, w, y: 12, y2: height, labeler: (t) => `${t > 0 ? "+" : ""}${Math.round(t / HOUR)} h` });
    }

    days.forEach((ds, i) => {
      const y = TOP + i * RH;
      const end = this._shiftDay(ds, 1);
      const dayEntries = this._entries.filter((e) => e.start >= ds && e.start < end && e.status === "confirmed");
      const d = new Date(ds * 1000);
      const caf = Math.round(dayEntries.filter((e) => e.kind === "caffeine").reduce((a, e) => a + (e.value?.mg || 0), 0));
      const medInfo = s.meds.map((m) => {
        const recs = dayEntries.filter((e) => e.kind === "med" && e.item === m.id);
        if (recs.some((e) => (e.value?.status ?? "taken") === "taken")) return `<tspan fill="${m.color}">●</tspan>`;
        if (recs.some((e) => e.value?.status === "skipped")) return `<tspan fill="${m.color}">○</tspan>`;
        return `<tspan class="muted">·</tspan>`;
      }).join(" ");
      rows += `<g data-action="goto:${ds}" class="daylabel"><text x="0" y="${y + RH / 2 - 2}" class="lbl">${WEEKDAYS[(d.getDay() + 6) % 7]} ${d.getDate()}</text>
        <text x="0" y="${y + RH / 2 + 12}" class="tick">${medInfo}</text></g>`;
      if (!narrow) rows += `<text x="${W}" y="${y + RH / 2 + 4}" text-anchor="end" class="tick">${caf ? `${caf} mg` : ""}</text>`;
      let tFrom, tTo;
      if (this._weekAlign === "clock") {
        const mid = this._midnight(ds);
        tFrom = mid + s.axis_start_hour * HOUR;
        tTo = mid + s.axis_end_hour * HOUR;
      } else {
        let ref = null;
        if (this._weekAlign === "med") {
          ref = dayEntries.find((e) => e.kind === "med" && e.item === medId && (e.value?.status ?? "taken") === "taken")?.start ?? null;
        } else {
          ref = dayEntries.find((e) => e.kind === "caffeine")?.start ?? null;
        }
        if (ref === null) {
          rows += `<text x="${L + w / 2}" y="${y + RH / 2 + 4}" text-anchor="middle" class="muted">${this._weekAlign === "med" ? "No dose this day" : "No coffee this day"}</text>`;
          return;
        }
        tFrom = ref - 3 * HOUR;
        tTo = ref + 15 * HOUR;
      }
      rows += `<line x1="${L}" x2="${L + w}" y1="${y + RH}" y2="${y + RH}" stroke="var(--divider-color)" stroke-width=".5"/>`;
      rows += timelineRow({ entries: this._entries, tFrom, tTo, x0: L, w, y, h: RH - 2, settings: s, profiles: this._profiles });
    });

    const first = new Date(days[0] * 1000), last = new Date(days[days.length - 1] * 1000);
    const range = `${first.toLocaleDateString(undefined, { day: "numeric", month: "short" })} – ${last.toLocaleDateString(undefined, { day: "numeric", month: "short" })}`;
    const atLatest = this._dayStart >= this._journalDayStart(Date.now() / 1000);
    return `
      <div class="daynav">
        <button class="icon" data-action="week:-1" aria-label="Earlier">‹</button><h2>${range}</h2>
        <button class="icon" data-action="week:1" aria-label="Later" ${atLatest ? "disabled" : ""}>›</button>
      </div>
      <section class="card">
        <div class="controls">
          <div class="seg">${[7, 14].map((n) => `<button class="${this._weekDays === n ? "on" : ""}" data-action="weekdays:${n}">${n} days</button>`).join("")}</div>
          <div class="seg"><span class="muted">Align by</span>
            ${[["clock", "Clock"], ["med", "Med dose"], ["coffee", "First coffee"]].map(([id, l]) => `<button class="${this._weekAlign === id ? "on" : ""}" data-action="align:${id}" ${id === "med" && !s.meds.length ? "disabled" : ""}>${l}</button>`).join("")}</div>
          ${this._weekAlign === "med" && s.meds.length > 1 ? `<select data-field="weekmed">${s.meds.map((m) => `<option value="${m.id}" ${m.id === medId ? "selected" : ""}>${esc(m.name)}</option>`).join("")}</select>` : ""}
        </div>
        ${this._legend(`<span><i class="sw round" style="background:none;border:1.5px solid currentColor"></i>Skipped dose</span>`)}
        <svg viewBox="0 0 ${W} ${height}" class="week" role="img" aria-label="Days side by side">${axis}${rows}</svg>
        <p class="hint">Click a day to open it. Aligning by med dose or first coffee lines days up so you can compare what happened in the hours after.</p>
      </section>`;
  }

  // -- Patterns view --------------------------------------------------
  _renderPatterns() {
    const s = this._settings;
    const r = this._insights;
    if (!r) return `<div class="card">Loading…</div>`;
    const minN = s.min_samples;
    const stateName = (id) => s.states.find((x) => x.id === id)?.name || id;

    // Weekday x time-of-day grid.
    let grid = "";
    r.band_labels.forEach((band, j) => (grid += `<text x="${70 + j * 102 + 48}" y="12" text-anchor="middle" class="tick">${band}</text>`));
    r.weekday_grid.forEach((row, i) => {
      grid += `<text x="0" y="${34 + i * 30}" class="lbl">${WEEKDAYS[i]}</text>`;
      row.forEach((cell, j) => {
        const n = sum(cell);
        const x = 70 + j * 102, y = 20 + i * 30;
        if (n < 2) {
          grid += `<rect x="${x}" y="${y}" width="96" height="24" rx="5" fill="none" stroke="var(--divider-color)"/>`;
          return;
        }
        const [top, c] = Object.entries(cell).sort((a, b) => b[1] - a[1])[0];
        const tip = Object.entries(cell).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${stateName(k)} ${v}`).join(", ");
        grid += `<rect x="${x}" y="${y}" width="96" height="24" rx="5" fill="${stateColor(s, top)}" opacity="${(0.35 + 0.65 * (c / n)).toFixed(2)}"><title>${esc(WEEKDAYS[i])} ${r.band_labels[j]}: ${esc(tip)}</title></rect>`;
        const short = stateName(top).length > 10 ? `${stateName(top).slice(0, 9)}…` : stateName(top);
        grid += `<text x="${x + 8}" y="${y + 16}" class="onbar">${esc(short)} ${Math.round((c / n) * 100)}%</text>`;
      });
    });

    const ctx = r.contexts;
    const contexts = stackedBars([
      { label: "1–4 h after coffee, meds taken", counts: ctx.med_and_coffee },
      { label: "Meds taken, no coffee in the last 4 h", counts: ctx.med_only },
      { label: "1–4 h after coffee, no meds", counts: ctx.coffee_only },
      { label: "No meds, no coffee in the last 4 h", counts: ctx.neither },
    ], s, { minN });

    const medCards = s.meds.map((m) => {
      const tvs = r.taken_vs_skipped[m.id];
      const sd = r.since_dose[m.id];
      if (!tvs) return `<section class="card"><h3>${esc(m.name)}</h3><p class="muted">No doses recorded in this period.</p></section>`;
      const bars = stackedBars([
        { label: `Days taken (${tvs.days_taken})`, counts: tvs.taken },
        { label: `Days skipped (${tvs.days_skipped})`, counts: tvs.skipped },
      ], s, { minN });
      let cols = "";
      const bw = 66;
      r.dose_bins.forEach((lo, i) => {
        const hi = r.dose_bins[i + 1];
        const counts = sd?.[i] || {};
        const n = sum(counts);
        const x = 10 + i * (bw + 8);
        cols += `<text x="${x + bw / 2}" y="188" text-anchor="middle" class="tick">${hi ? `${lo}–${hi} h` : `${lo} h+`}</text>`;
        cols += `<text x="${x + bw / 2}" y="202" text-anchor="middle" class="tick">n=${n}</text>`;
        if (n < Math.max(2, Math.ceil(minN / 2))) {
          cols += `<rect x="${x}" y="10" width="${bw}" height="164" rx="4" fill="none" stroke="var(--divider-color)" stroke-dasharray="4 3"/>`;
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
      return `<section class="card"><h3>${esc(m.name)}</h3>
        <div class="sub2">How you felt by hours since the first dose of the day</div>
        <svg viewBox="0 0 600 206" class="chart">${cols}</svg>
        <div class="sub2">Days you took it compared with days you skipped it</div>
        <svg viewBox="0 0 600 ${bars.height}" class="chart">${bars.svg}</svg></section>`;
    }).join("");

    // Energy by hour.
    let energy = "";
    const hours = r.energy_by_hour;
    if (hours.length) {
      const h0 = Math.min(...hours.map((h) => h.hour)), h1 = Math.max(...hours.map((h) => h.hour));
      const span = Math.max(1, h1 - h0 + 1), bw = 560 / span;
      hours.forEach((h) => {
        const share = h.n ? h.high / h.n : 0;
        const x = 30 + (h.hour - h0) * bw;
        const faded = h.n < 3 ? ' opacity=".35"' : "";
        energy += `<rect x="${x + 1}" y="${10 + (1 - share) * 120}" width="${Math.max(1, bw - 3)}" height="${share * 120}" rx="3" fill="#1baf7a"${faded}><title>${pad(h.hour % 24)}:00 · ${Math.round(share * 100)}% high energy · n=${h.n}</title></rect>`;
        energy += `<text x="${x + bw / 2}" y="146" text-anchor="middle" class="tick">${pad(h.hour % 24)}</text>`;
      });
      energy += `<text x="0" y="16" class="tick">100%</text><text x="0" y="132" class="tick">0%</text>`;
    }

    const sleep = r.sleep_vs_caffeine;
    let scatter = "";
    if (sleep.length >= 3) {
      const maxC = Math.max(50, ...sleep.map((p) => p.caffeine_mg));
      const durs = sleep.map((p) => p.duration_h);
      const d0 = Math.floor(Math.min(...durs)), d1 = Math.ceil(Math.max(...durs));
      sleep.forEach((p) => {
        const x = 40 + (p.caffeine_mg / maxC) * 540;
        const y = 150 - ((p.duration_h - d0) / Math.max(1, d1 - d0)) * 140;
        scatter += `<circle cx="${x}" cy="${y}" r="5" fill="#2a78d6" opacity=".75"><title>${p.day}: ${p.caffeine_mg} mg at bedtime, slept ${p.duration_h} h</title></circle>`;
      });
      scatter += `<text x="40" y="172" class="tick">0 mg</text><text x="580" y="172" text-anchor="end" class="tick">${Math.round(maxC)} mg at bedtime</text>`;
      scatter += `<text x="0" y="14" class="tick">${d1} h</text><text x="0" y="152" class="tick">${d0} h</text>`;
    }

    return `
      <div class="daynav"><h2>Patterns</h2>
        <div class="seg">${[[28, "4 weeks"], [56, "8 weeks"], [182, "6 months"], [365, "1 year"]].map(([n, l]) => `<button class="${this._patternDays === n ? "on" : ""}" data-action="pdays:${n}">${l}</button>`).join("")}</div></div>
      <p class="hint">${r.n_states} check-ins over ${r.n_days} days. These are patterns, not causes: you may reach for coffee because you already feel tired.</p>
      ${this._substanceCard()}
      <div class="grid">
        <section class="card"><h3>Your typical week</h3><div class="sub2">Most common state by weekday and time of day</div>
          <svg viewBox="0 0 580 232" class="chart">${grid}</svg></section>
        <section class="card"><h3>Coffee and meds</h3><div class="sub2">How you felt, depending on what you'd had</div>
          <svg viewBox="0 0 600 ${contexts.height}" class="chart">${contexts.svg}</svg></section>
        ${medCards}
        <section class="card"><h3>Energy through the day</h3><div class="sub2">Share of check-ins with a high-energy state</div>
          ${energy ? `<svg viewBox="0 0 600 152" class="chart">${energy}</svg>` : `<p class="muted">No check-ins yet.</p>`}</section>
        <section class="card"><h3>Caffeine at bedtime and sleep</h3>
          ${scatter ? `<svg viewBox="0 0 600 178" class="chart">${scatter}</svg>` : `<p class="muted">Needs at least 3 nights with sleep recorded (${sleep.length} so far).</p>`}</section>
      </div>`;
  }

  _substanceCard() {
    const s = this._settings;
    const ids = Object.keys(this._profiles).filter((id) => id !== "custom");
    if (!this._shownSubstances) {
      const mine = s.meds.map((m) => m.profile).filter((p) => p && p !== "custom");
      this._shownSubstances = [...new Set(["caffeine", ...mine])];
      if (this._shownSubstances.length < 3) this._shownSubstances.push(...["mph_ir", "lisdexamfetamine"].filter((x) => !this._shownSubstances.includes(x)));
    }
    const colors = {};
    ids.forEach((id, i) => (colors[id] = SERIES[i % SERIES.length]));
    const shown = this._shownSubstances;
    const rows = ids.map((id) => {
      const p = this._profiles[id];
      const half = hoursBelow(p, 0.5);
      const quarter = hoursBelow(p, 0.25);
      return `<label class="subst ${shown.includes(id) ? "on" : ""}">
        <input type="checkbox" data-field="subst:${id}" ${shown.includes(id) ? "checked" : ""}>
        <i class="sw line" style="background:${colors[id]}"></i>
        <span><b>${esc(p.name)}</b> <span class="muted">${esc(p.examples)}</span>
        <span class="facts">Peak ${p.tmax_h} h · half-life ${p.half_life_h} h${p.half_life_range_h ? ` (${p.half_life_range_h[0]}–${p.half_life_range_h[1]} h)` : ""}${half ? ` · under half after ${Math.round(half * 10) / 10} h` : ""}${quarter ? ` · under a quarter after ${Math.round(quarter * 10) / 10} h` : ""}${p.verified ? "" : ' · <span class="badge">Estimate</span>'}</span>
        ${p.notes ? `<span class="facts">${esc(p.notes)}</span>` : ""}
        ${p.sources.length ? `<span class="facts">${p.sources.map((u, i) => `<a href="${esc(u)}" target="_blank" rel="noreferrer">Source ${i + 1}</a>`).join(" · ")}</span>` : ""}</span></label>`;
    }).join("");
    return `<section class="card wide"><h3>How long things stay in your body</h3>
      <div class="sub2">One dose of each, as a share of its own peak, over 24 hours. Dashed lines are rougher estimates.</div>
      <div class="legend">${shown.map((id) => `<span><i class="sw line" style="background:${colors[id]}"></i>${esc(this._profiles[id].name)} <span class="muted">· half-life ${this._profiles[id].half_life_h} h</span></span>`).join("")}</div>
      <svg viewBox="0 0 900 240" class="chart">${substanceChart(shown, this._profiles, colors, { width: 900, height: 240 })}</svg>
      <p class="disclaimer">${esc(this._disclaimer)}</p>
      <details><summary>Choose substances and see the numbers</summary><div class="substs">${rows}</div></details></section>`;
  }

  // -- Settings view --------------------------------------------------
  _renderSettings() {
    const d = this._draft;
    if (!d) return "";
    const zones = Object.keys(this._hass.states).filter((e) => e.startsWith("zone.")).sort();
    const persons = Object.keys(this._hass.states).filter((e) => e.startsWith("person.") || e.startsWith("device_tracker.")).sort();
    const schedules = Object.keys(this._hass.states).filter((e) => e.startsWith("schedule.")).sort();
    const notifies = Object.keys(this._hass.services.notify || {}).filter((n) => n.startsWith("mobile_app_")).sort();
    const name = (id) => esc(this._hass.states[id]?.attributes?.friendly_name || id);
    const opt = (v, cur, label = v) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${label}</option>`;
    const num = (path, v, attrs = "") => `<input type="number" data-path="${path}" data-type="number" value="${v ?? ""}" ${attrs}>`;
    const txt = (path, v, attrs = "") => `<input type="text" data-path="${path}" value="${esc(v ?? "")}" ${attrs}>`;
    const profileOpts = (cur) => Object.entries(this._profiles).map(([id, p]) => opt(id, cur, `${esc(p.name)}${p.examples && id !== "custom" ? ` (${esc(p.examples)})` : ""}`)).join("");

    const states = d.states.map((st, i) => `<div class="row">
        <input type="color" data-path="states.${i}.color" value="${st.color}" aria-label="Colour">
        ${txt(`states.${i}.name`, st.name, 'aria-label="Name"')}
        <select data-path="states.${i}.energy" aria-label="Energy">${opt("high", st.energy, "High energy")}${opt("low", st.energy, "Low energy")}${opt("neutral", st.energy, "Neutral")}</select>
        <button class="icon ghost" data-action="remove:states:${i}" aria-label="Remove">×</button></div>`).join("");

    const drinks = d.drinks.map((dr, i) => `<div class="row">
        ${txt(`drinks.${i}.name`, dr.name, 'aria-label="Name"')}
        <span class="unit">${num(`drinks.${i}.mg`, dr.mg, 'min="0" max="1000" aria-label="Caffeine"')} mg</span>
        <button class="icon ghost" data-action="remove:drinks:${i}" aria-label="Remove">×</button></div>`).join("");

    const meds = d.meds.map((m, i) => `<div class="block">
        <div class="row">
          <input type="color" data-path="meds.${i}.color" value="${m.color}" aria-label="Colour">
          ${txt(`meds.${i}.name`, m.name, 'aria-label="Name" placeholder="Elvanse"')}
          <span class="unit">${num(`meds.${i}.dose`, m.dose, 'min="0" aria-label="Usual dose" placeholder="Dose"')}${txt(`meds.${i}.unit`, m.unit, 'class="short" aria-label="Unit"')}</span>
          <button class="icon ghost" data-action="remove:meds:${i}" aria-label="Remove">×</button></div>
        <div class="row"><label>Profile <select data-path="meds.${i}.profile">${profileOpts(m.profile)}</select></label></div>
        <div class="row"><label>Half-life ${num(`meds.${i}.half_life_h`, m.half_life_h, `step="0.1" placeholder="${this._profiles[m.profile]?.half_life_h ?? ""}"`)} h</label>
          <label>Time to peak ${num(`meds.${i}.tmax_h`, m.tmax_h, `step="0.1" placeholder="${this._profiles[m.profile]?.tmax_h ?? ""}"`)} h</label>
          <span class="muted">Leave empty to use the profile</span></div></div>`).join("");

    const sport = d.sport_zones.map((z, i) => `<div class="block">
        <div class="row">
          ${txt(`sport_zones.${i}.activity`, z.activity, 'aria-label="Activity" placeholder="Water polo"')}
          <select data-path="sport_zones.${i}.zone" aria-label="Zone">${zones.map((zz) => opt(zz, z.zone, name(zz))).join("")}</select>
          <select data-path="sport_zones.${i}.person" aria-label="Person">${persons.map((p) => opt(p, z.person, name(p))).join("")}</select>
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

    return `
      <div class="daynav"><h2>Settings</h2><span class="spacer"></span>
        <button class="ghost" data-action="settings:reset">Discard changes</button>
        <button class="primary" data-action="settings:save">Save</button></div>
      ${this._settingsError ? `<div class="card error">${esc(this._settingsError)}</div>` : ""}
      <div class="grid">
        <section class="card"><h3>How you feel</h3><div class="sub2">The buttons you press to check in. High and low energy are used for the energy chart.</div>
          ${states}<button class="ghost" data-action="add:states">Add state</button></section>
        <section class="card"><h3>Caffeine</h3>${drinks}<button class="ghost" data-action="add:drinks">Add drink</button>
          <div class="row"><label>Caffeine half-life ${num("caffeine_half_life_h", d.caffeine_half_life_h, 'step="0.5" min="1" max="12"')} h</label>
            <label>Time to peak ${num("caffeine_absorption_min", d.caffeine_absorption_min, 'min="5" max="180"')} min</label></div>
          <p class="muted">About 5 h for most adults; often 1.5–2× longer on the pill, shorter if you smoke.</p>
          <label class="check"><input type="checkbox" data-path="caffeine_sensor" data-type="bool" ${d.caffeine_sensor ? "checked" : ""}> Show a caffeine estimate sensor in Home Assistant</label></section>
        <section class="card"><h3>Meds</h3><div class="sub2">Pick the closest profile so the curves match how the med is released.</div>
          ${meds}<button class="ghost" data-action="add:meds">Add med</button></section>
        <section class="card"><h3>Sport places</h3>
          <div class="sub2">Create zones in Home Assistant first (Settings, Areas, labels and zones). A stay becomes a suggested sport entry you confirm.</div>
          ${zones.length ? sport + `<button class="ghost" data-action="add:sport_zones">Add place</button>` : `<p class="muted">No zones found.</p>`}
          <div class="row"><label>Ask on this phone <select data-path="notify_service">${opt("", d.notify_service, "Don't notify")}${notifies.map((n) => opt(n, d.notify_service, n.replace("mobile_app_", ""))).join("")}</select></label></div></section>
        <section class="card"><h3>Days and charts</h3>
          <div class="row"><label>A new day starts at ${num("day_start_hour", d.day_start_hour, 'min="0" max="8"')} :00</label></div>
          <div class="row"><label>Timeline from ${num("axis_start_hour", d.axis_start_hour, 'min="0" max="12"')} :00</label>
            <label>to ${num("axis_end_hour", d.axis_end_hour, 'min="16" max="32"')} :00</label><span class="muted">26 = 02:00</span></div>
          <div class="row"><label>Hide patterns until there are ${num("min_samples", d.min_samples, 'min="1" max="100"')} check-ins</label></div></section>
        <section class="card"><h3>Your data</h3><div class="sub2">Stored only in daybook.db in your Home Assistant config folder. It's included in Home Assistant backups.</div>
          <div class="row"><button class="ghost" data-action="export:json">Export JSON</button><button class="ghost" data-action="export:csv">Export CSV</button>
            <button class="ghost" data-action="export:settings">Export settings</button>
            <label class="filebtn">Import settings<input type="file" accept="application/json" data-field="import"></label></div></section>
      </div>`;
  }

  _setPath(path, raw, type) {
    const parts = path.split(".");
    let obj = this._draft;
    for (let i = 0; i < parts.length - 1; i++) obj = obj[parts[i]];
    const key = parts[parts.length - 1];
    let value = raw;
    if (type === "number") value = raw === "" ? null : Number(raw);
    obj[key] = value;
    // A changed name gives a new item an id, but never renames an existing one.
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
    for (const list of ["states", "drinks", "meds", "sport_zones"]) payload[list].forEach((x) => delete x._new);
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
    if (e.kind === "state") item = `<label>State<select id="d-item">${opts(s.states, e.item)}</select></label>`;
    if (e.kind === "caffeine") item = `<label>Drink<select id="d-item">${opts(s.drinks, e.item)}</select></label><label>Caffeine<span class="unit"><input id="d-mg" type="number" min="0" max="1000" value="${e.value?.mg ?? ""}"> mg</span></label>`;
    if (e.kind === "med") item = `<label>Med<select id="d-item">${opts(s.meds, e.item)}</select></label>
      <label>Status<select id="d-medstatus"><option value="taken" ${e.value?.status !== "skipped" ? "selected" : ""}>Taken</option><option value="skipped" ${e.value?.status === "skipped" ? "selected" : ""}>Skipped on purpose</option></select></label>
      <label>Dose<span class="unit"><input id="d-dose" type="number" min="0" step="any" value="${e.value?.dose ?? ""}"> ${esc(e.value?.unit || s.meds.find((m) => m.id === e.item)?.unit || "")}</span></label>`;
    if (e.kind === "sport") item = `<label>Activity<input id="d-item" list="d-acts" value="${esc(e.item || "")}"><datalist id="d-acts">${activities.map((a) => `<option value="${esc(a)}">`).join("")}</datalist></label>`;
    const hasEnd = e.kind === "sport" || e.kind === "sleep";
    const title = isNew ? `Add ${{ state: "check-in", caffeine: "caffeine", med: "dose", sport: "sport", sleep: "sleep", note: "note" }[e.kind]}` : `Edit ${itemName(s, e.kind, e.item).toLowerCase()}`;
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
    if (e.kind === "caffeine") value.mg = $("#d-mg").value === "" ? undefined : Number($("#d-mg").value);
    if (e.kind === "med") {
      value.status = $("#d-medstatus").value;
      const dose = $("#d-dose").value;
      if (dose === "" || value.status === "skipped") delete value.dose;
      else value.dose = Number(dose);
    }
    if (value.mg === undefined) delete value.mg;
    const msg = {
      start: fromInput($("#d-start").value),
      note: $("#d-note").value,
      value,
    };
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
  async _quick(kind, item, medStatus) {
    const value = medStatus ? { status: medStatus } : {};
    if (!this._isToday()) {
      const noon = this._midnight(this._dayStart) + 12 * HOUR;
      const def = kind === "caffeine" ? { mg: this._settings.drinks.find((d) => d.id === item)?.mg } : {};
      return this._openDialog({ kind, item, start: noon, value: { ...def, ...value }, note: "" });
    }
    try {
      const saved = await this._ws({ type: "daybook/entries/create", kind, item, value });
      const what = kind === "med" ? `${itemName(this._settings, kind, item)} ${medStatus}` : itemName(this._settings, kind, item);
      this._showToast(`${what} at ${fmtTime(saved.start)}`, saved);
      await this._load();
    } catch (err) {
      this._showToast(err.message || String(err));
    }
  }

  _showToast(text, entry = null) {
    this._toast = entry;
    clearTimeout(this._toastTimer);
    this._toastEl.innerHTML = `<span>${esc(text)}</span>${entry ? `<button data-action="toast:undo">Undo</button><button data-action="toast:shift">−15 min</button><button data-action="toast:edit">Edit</button>` : ""}`;
    this._toastEl.classList.add("open");
    this._toastTimer = setTimeout(() => this._toastEl.classList.remove("open"), entry ? 8000 : 4000);
  }

  async _toastAction(what) {
    const e = this._toast;
    if (!e) return;
    try {
      if (what === "undo") {
        await this._ws({ type: "daybook/entries/delete", entry_id: e.id });
        this._showToast("Removed");
        await this._load();
      } else if (what === "shift") {
        const saved = await this._ws({ type: "daybook/entries/update", entry_id: e.id, start: e.start - 15 * 60 });
        this._showToast(`Moved to ${fmtTime(saved.start)}`, saved);
        await this._load();
      } else if (what === "edit") {
        this._toastEl.classList.remove("open");
        this._openDialog(e);
      }
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
      this._setPath(t.dataset.path, v, t.dataset.type);
      // Re-render when the shape of the form changes.
      if (!live && /(\.schedule|\.profile)$/.test(t.dataset.path)) this._render();
      return;
    }
    if (live) return;
    const f = t.dataset.field;
    if (!f) return;
    if (f === "weekmed") { this._weekMed = t.value; this._render(); }
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
    const run = {
      tab: () => { this._view = a; if (a === "settings") this._draft = null; this._load(); },
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
      align: () => { this._weekAlign = a; this._render(); },
      pdays: () => { this._patternDays = Number(a); this._load(); },
      quick: () => this._quick(a, b, c),
      new: () => {
        const now = Date.now() / 1000;
        const start = this._isToday() ? now : this._midnight(this._dayStart) + 12 * HOUR;
        const base = { kind: a, item: null, start, end: null, value: {}, note: "" };
        if (a === "sport") { base.item = this._settings.sport_zones[0]?.activity || "Sport"; base.start = start - HOUR; base.end = start; }
        if (a === "sleep") { const mid = this._midnight(this._dayStart); base.start = mid - 1 * HOUR; base.end = mid + 7 * HOUR; }
        this._openDialog(base);
      },
      edit: () => { const e = this._entries.find((x) => x.id === a); if (e) this._openDialog(e); },
      confirm: () => this._ws({ type: "daybook/entries/update", entry_id: a, status: "confirmed" }).then(() => this._load()).catch((err) => this._showToast(err.message)),
      reject: () => this._ws({ type: "daybook/entries/update", entry_id: a, status: "rejected" }).then(() => this._load()).catch((err) => this._showToast(err.message)),
      dlg: async () => {
        if (a === "cancel") { this._dialog = null; this._renderDialog(); }
        if (a === "save") await this._saveDialog();
        if (a === "delete") {
          const id = this._dialog.id;
          try {
            await this._ws({ type: "daybook/entries/delete", entry_id: id });
            this._dialog = null;
            this._renderDialog();
            this._toast = null;
            this._toastEl.innerHTML = `<span>Deleted</span><button data-action="restore:${id}">Restore</button>`;
            this._toastEl.classList.add("open");
            clearTimeout(this._toastTimer);
            this._toastTimer = setTimeout(() => this._toastEl.classList.remove("open"), 8000);
            await this._load();
          } catch (err) { this._showToast(err.message); }
        }
      },
      restore: () => this._ws({ type: "daybook/entries/restore", entry_id: a }).then(() => { this._showToast("Restored"); this._load(); }).catch((err) => this._showToast(err.message)),
      toast: () => this._toastAction(a),
      settings: () => { if (a === "save") this._saveSettings(); else { this._draft = clone(this._settings); this._settingsError = null; this._render(); } },
      add: () => {
        const d = this._draft;
        const fresh = {
          states: { name: "New state", color: SERIES[d.states.length % SERIES.length], energy: "high" },
          drinks: { name: "New drink", mg: 80 },
          meds: { name: "New med", dose: null, unit: "mg", profile: "custom", half_life_h: null, tmax_h: null, color: MED_COLORS[d.meds.length % MED_COLORS.length] },
          sport_zones: {
            activity: "Sport",
            zone: Object.keys(this._hass.states).find((e) => e.startsWith("zone.") && e !== "zone.home") || "zone.home",
            person: Object.keys(this._hass.states).find((e) => e.startsWith("person.")) || "",
            min_minutes: 60, windows: [], schedule: "",
          },
        }[a];
        const item = { ...fresh, _new: true };
        item.id = this._uniqueId(a, slug(item.name || item.activity), item);
        d[a].push(item);
        this._render();
      },
      remove: () => { this._draft[a].splice(Number(b), 1); this._render(); },
      addwin: () => { this._draft.sport_zones[Number(a)].windows.push({ weekdays: [1, 4], from: "19:00", to: "21:00" }); this._render(); },
      rmwin: () => { this._draft.sport_zones[Number(a)].windows.splice(Number(b), 1); this._render(); },
      wday: () => {
        const w = this._draft.sport_zones[Number(a)].windows[Number(b)];
        const k = Number(c);
        w.weekdays = w.weekdays.includes(k) ? w.weekdays.filter((x) => x !== k) : [...w.weekdays, k].sort();
        this._render();
      },
      export: () => this._export(a).catch((err) => this._showToast(err.message)),
    }[action];
    if (run) run();
  }
}

const STYLE = `
:host { display:block; min-height:100vh; background:var(--primary-background-color); color:var(--primary-text-color);
  font-family:var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif); --gap:16px; }
.toolbar { display:flex; align-items:center; gap:8px; height:56px; padding:0 12px; background:var(--app-header-background-color, var(--primary-background-color));
  color:var(--app-header-text-color, var(--primary-text-color)); border-bottom:1px solid var(--divider-color); position:sticky; top:0; z-index:2; }
.title { font-size:20px; margin-right:auto; }
nav { display:flex; gap:4px; }
.tab { background:none; border:none; color:inherit; padding:8px 12px; border-radius:18px; font:inherit; cursor:pointer; opacity:.75; }
.tab.active { background:var(--secondary-background-color, rgba(127,127,127,.15)); opacity:1; }
main { max-width:1240px; margin:0 auto; padding:var(--gap); }
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 480px), 1fr)); gap:var(--gap); align-items:start; }
.card { background:var(--card-background-color, #fff); border-radius:var(--ha-card-border-radius, 12px); border:1px solid var(--divider-color);
  padding:16px 18px; margin-bottom:var(--gap); box-sizing:border-box; min-width:0; }
.grid .card { margin-bottom:0; }
.card.wide { margin-bottom:var(--gap); }
.card.error { color:var(--error-color, #d03b3b); }
h2 { font-size:20px; font-weight:500; margin:0; }
h3 { font-size:16px; font-weight:500; margin:0 0 10px; }
.cardhead { display:flex; align-items:baseline; justify-content:space-between; gap:8px; }
.metric { font-size:14px; color:var(--secondary-text-color); }
.sub2, .hint, .muted { color:var(--secondary-text-color); font-size:13px; }
.sub2 { margin:-4px 0 10px; }
.hint { margin:0 0 var(--gap); }
.small { font-size:12px; }
.daynav { display:flex; align-items:center; gap:8px; margin:0 0 var(--gap); flex-wrap:wrap; }
.spacer { flex:1; }
button { font:inherit; font-size:14px; color:var(--primary-text-color); background:var(--card-background-color); border:1px solid var(--divider-color);
  border-radius:18px; padding:6px 14px; cursor:pointer; }
button:hover { border-color:var(--secondary-text-color); }
button:disabled { opacity:.4; cursor:default; }
button.ghost { background:none; }
button.primary { background:var(--primary-color); color:var(--text-primary-color, #fff); border-color:var(--primary-color); }
button.danger { color:var(--error-color, #d03b3b); }
button.icon { width:34px; height:34px; padding:0; font-size:20px; line-height:1; }
.group { margin:14px 0 0; }
.glabel { font-size:12px; color:var(--secondary-text-color); margin-bottom:6px; letter-spacing:.02em; }
.chips { display:flex; flex-wrap:wrap; gap:8px; }
.chip { display:inline-flex; align-items:center; gap:8px; padding:9px 14px; }
.chip.state { border-color:color-mix(in srgb, var(--c) 45%, var(--divider-color)); }
.chip.state:hover { background:color-mix(in srgb, var(--c) 12%, transparent); }
.chip.state .dot { background:var(--c); }
.chip .sub, .medname .sub { color:var(--secondary-text-color); font-size:12px; }
.dot { width:10px; height:10px; border-radius:50%; display:inline-block; flex:none; }
.medrow { display:flex; align-items:center; gap:10px; padding:6px 0; }
.medname { flex:1; display:flex; flex-direction:column; }
svg { width:100%; height:auto; display:block; overflow:visible; }
svg text { font-size:11px; fill:var(--primary-text-color); }
svg .tick, svg .muted { fill:var(--secondary-text-color); font-size:11px; }
svg .lbl { font-size:12px; }
svg .onbar { fill:#fff; font-size:11px; }
.daylabel { cursor:pointer; }
.legend { display:flex; flex-wrap:wrap; gap:6px 14px; font-size:12px; color:var(--secondary-text-color); margin:4px 0 8px; }
.legend span { display:inline-flex; align-items:center; gap:5px; }
.sw { width:12px; height:8px; border-radius:2px; display:inline-block; }
.sw.round { width:9px; height:9px; border-radius:50%; box-sizing:border-box; }
.sw.line { height:3px; width:14px; }
.entries { list-style:none; margin:12px 0 0; padding:0; }
.entries li { display:flex; align-items:center; gap:10px; padding:9px 4px; border-top:1px solid var(--divider-color); cursor:pointer; }
.entries li:hover { background:var(--secondary-background-color, rgba(127,127,127,.08)); }
.entries li.draft { opacity:.7; }
.entries .time { width:92px; flex:none; font-variant-numeric:tabular-nums; color:var(--secondary-text-color); font-size:13px; }
.entries .what { flex:1; display:flex; flex-direction:column; }
.entries .note { font-size:12px; color:var(--secondary-text-color); }
.entries .detail { font-size:13px; color:var(--secondary-text-color); }
.entries .empty { cursor:default; color:var(--secondary-text-color); }
.badge { font-size:11px; padding:1px 7px; border-radius:9px; background:var(--secondary-background-color, rgba(127,127,127,.15)); color:var(--secondary-text-color); }
.drafts { margin:8px 0; display:flex; flex-direction:column; gap:6px; }
.draft { display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding:8px 10px; border-radius:10px; border:1px dashed ${SPORT_COLOR}; }
.draft span { flex:1; font-size:14px; }
.controls { display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin-bottom:6px; }
.seg { display:inline-flex; align-items:center; gap:4px; }
.seg button.on { border-color:var(--primary-color); color:var(--primary-color); }
.chart { margin:4px 0 12px; }
.disclaimer { font-size:12px; color:var(--secondary-text-color); margin:0 0 8px; }
details summary { cursor:pointer; color:var(--primary-color); font-size:14px; }
.substs { display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap:10px; margin-top:10px; }
.subst { display:flex; gap:8px; align-items:flex-start; font-size:13px; padding:8px; border-radius:8px; border:1px solid var(--divider-color); cursor:pointer; }
.subst .sw { margin-top:7px; flex:none; }
.subst > span { display:flex; flex-direction:column; gap:2px; }
.facts { color:var(--secondary-text-color); font-size:12px; }
.facts a { color:var(--primary-color); }
.row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:6px 0; }
.block { border-top:1px solid var(--divider-color); padding:8px 0; }
input, select, textarea { font:inherit; font-size:14px; color:var(--primary-text-color); background:var(--card-background-color);
  border:1px solid var(--divider-color); border-radius:8px; padding:6px 8px; box-sizing:border-box; }
input[type=text] { flex:1; min-width:120px; }
input[type=number] { width:76px; }
input.short { width:56px; flex:none; min-width:0; }
input[type=color] { width:36px; height:32px; padding:2px; }
.unit { display:inline-flex; align-items:center; gap:6px; }
label { display:inline-flex; align-items:center; gap:6px; font-size:14px; }
label.check { margin-top:8px; }
.days { display:inline-flex; gap:3px; }
.day { padding:4px 0; width:32px; font-size:12px; }
.day.on { background:var(--primary-color); color:var(--text-primary-color, #fff); border-color:var(--primary-color); }
.filebtn { border:1px solid var(--divider-color); border-radius:18px; padding:6px 14px; cursor:pointer; }
.filebtn input { display:none; }
.overlay { position:fixed; inset:0; background:rgba(0,0,0,.4); display:none; align-items:center; justify-content:center; z-index:10; padding:16px; }
.overlay.open { display:flex; }
.dialog { background:var(--card-background-color, #fff); border-radius:16px; padding:20px; width:min(440px, 100%); max-height:90vh; overflow:auto;
  display:flex; flex-direction:column; gap:12px; }
.dialog label { display:flex; flex-direction:column; align-items:stretch; gap:4px; font-size:13px; color:var(--secondary-text-color); }
.dialog label .unit { color:var(--primary-text-color); }
.dialog input, .dialog select, .dialog textarea { width:100%; }
.dialog .unit input { width:110px; }
.actions { display:flex; gap:8px; align-items:center; margin-top:4px; }
.toast { position:fixed; left:50%; bottom:24px; transform:translate(-50%, 140%); transition:transform .2s ease, visibility .2s; z-index:11; visibility:hidden;
  background:var(--primary-text-color); color:var(--card-background-color, #fff); border-radius:12px; padding:10px 14px;
  display:flex; gap:10px; align-items:center; font-size:14px; max-width:calc(100% - 32px); }
.toast.open { transform:translate(-50%, 0); visibility:visible; }
.toast button { background:none; color:inherit; border-color:rgba(127,127,127,.6); padding:4px 10px; }
:host([narrow]) .toolbar { padding:0 4px; }
:host([narrow]) .title { display:none; }
:host([narrow]) .tab { padding:8px; }
:host([narrow]) main { padding:12px; --gap:12px; }
`;

customElements.define("daybook-panel", DaybookPanel);
