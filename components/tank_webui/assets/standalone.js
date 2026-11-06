// The standalone tank site: everything about one tank, from this device,
// for a tank with no Home Assistant.
//
// LAYOUT is prefixed by components/tank_webui/__init__.py from the YAML
// (packages/layout_*.yaml): the same numbers the panel draws its Vessel page
// from, so the page and the glass show the same tank.
//
// Live state arrives on /events (ESPHome web_server's server-sent events);
// controls go back over web_server's REST routes, addressed by the id each
// entity arrived with. History and water tests come from
// components/tank_history (/history.json, /tests.json, POST /tests).
// Nothing is fetched from the internet.

const num = (v, d) => { const f = parseFloat(v); return isNaN(f) ? d : f; };
const LY = {
  title: LAYOUT.title || "Tank",
  w: num(LAYOUT.width_in, 24), h: num(LAYOUT.height_in, 12),
  sponge: String(LAYOUT.sponge_filters) === "true",
  spongeIn: num(LAYOUT.sponge_in, 12), spongeSp: num(LAYOUT.sponge_spacing_in, 4.5),
  heaterIn: num(LAYOUT.heater_in, 4), probeIn: num(LAYOUT.probe_in, 8), fanIn: num(LAYOUT.fan_in, 18),
};

// web_server reports "<domain>/[<device>/]<Display Name>"; the page keys on
// the domain plus a slug of the name. See tank.js for why not the object id.
const key = (id) => {
  const parts = String(id).split("/");
  return parts[0] + "-" + parts[parts.length - 1].toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
};

const E = {
  temp: "sensor-water_temperature", target: "number-target_temperature",
  state: "text_sensor-controller_state", heat: "sensor-heater_output", fan: "sensor-fan_output",
  heatRelay: "binary_sensor-heater", fanRelay: "binary_sensor-fan",
  swing: "sensor-temperature_swing_1h", drift: "sensor-temperature_drift_rate",
  conf: "sensor-model_confidence", health: "sensor-model_health",
  tds: "sensor-tds_1h_mean", tdsRaw: "sensor-tds", ec: "sensor-electrical_conductivity",
  tdsV: "sensor-tds_probe_voltage", lux: "sensor-tank_light_level", ph: "sensor-water_ph",
  predicted: "sensor-predicted_temperature_15_min",
  noProbe: "binary_sensor-probe_not_responding", noHeat: "binary_sensor-heater_not_responding",
  noFan: "binary_sensor-fan_not_responding", paused: "binary_sensor-learning_paused",
  bleLinks: "sensor-ble_links", wifi: "sensor-wi_fi_signal", uptime: "sensor-uptime",
  crash: "text_sensor-last_crash",
  calK: "number-cal_tds_k_factor", calStd: "number-cal_tds_standard", calOff: "number-cal_temperature_offset",
  calTds: "button-calibrate_tds", learn: "switch-adaptive_learning",
  restart: "button-restart", reset: "button-reset_learning", clearCrash: "button-clear_crash_report",
  factory: "button-factory_reset",
  deadband: "number-fan_deadband", vol: "number-tank_volume", water: "number-water_volume",
  power: "number-heater_power", cover: "select-tank_cover", placement: "select-tank_placement",
  co2: "switch-co2", air: "switch-bubbler", co2Sched: "switch-co2_schedule",
  co2On: "time-co2_on_at", co2Off: "time-co2_off_at", airOn: "time-bubbler_on_at",
};

const PAGES = [["tank", "Tank"], ["vessel", "Vessel"], ["history", "History"],
  ["tests", "Water tests"], ["settings", "Settings"], ["archive", "Archive"], ["diag", "Diagnostics"]];

// The panel's colours, as CSS.
const C = { bg: "#070b0f", card: "#1a2028", track: "#1e252e", ink: "#fff", ink2: "#b9c2cc",
  muted: "#6f7b88", blue: "#3987e5", orange: "#d95926", heat: "#ff8a5c", good: "#0ca30c", bad: "#d03b3b" };

const GH_PER_DEG = 17.86;  // ppm CaCO3 per German degree
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const ago = (secs) => {
  if (secs < 3600) return Math.max(0, Math.floor(secs / 60)) + " min ago";
  if (secs < 172800) return Math.floor(secs / 3600) + " h ago";
  return Math.floor(secs / 86400) + " days ago";
};
const fmtTime = (epoch, withDate) => {
  const d = new Date(epoch * 1000);
  const t = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return withDate ? d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + t : t;
};

class TankSite extends HTMLElement {
  connectedCallback() {
    this.s = {}; this.ids = {}; this.order = []; this.pending = {};
    this.logLines = []; this.page = "tank"; this.range = "day"; this.hist = null; this.tests = null;
    document.title = LY.title + " Tank";
    this.innerHTML = `<div class="wrap">
      <header>
        <h1>${esc(LY.title)}</h1>
        <div class="dots">
          <span title="The panel's BLE link to this controller"><i class="dot" id="d_ble"></i>PANEL</span>
          <span title="This page's live connection"><i class="dot" id="d_link"></i>LIVE</span>
          <span class="clock" id="clock">--:--</span>
        </div>
      </header>
      <div class="alert" id="alert"></div>
      <nav id="nav">${PAGES.map(([k, l]) => `<a href="#${k}" data-p="${k}">${l}</a>`).join("")}</nav>
      <main id="main"></main>
    </div>`;
    this.$ = (id) => this.querySelector("#" + id);
    window.addEventListener("hashchange", () => this.go());
    window.addEventListener("resize", () => { if (this.page === "history") this.drawCharts(); });
    setInterval(() => this.tick(), 1000);
    this.listen();
    this.go();
  }

  // ---------------------------------------------------------------- state
  listen() {
    const es = new EventSource("/events");
    es.addEventListener("state", (e) => {
      const d = JSON.parse(e.data);
      const k = key(d.id);
      if (!this.s[k]) this.order.push(k);
      this.s[k] = d; this.ids[k] = d.id;
      delete this.pending[k];
      this.live = Date.now();
      this.dirty = true;
    });
    es.addEventListener("ping", () => { this.live = Date.now(); });
    es.addEventListener("log", (e) => {
      this.logLines.push(e.data);
      if (this.logLines.length > 300) this.logLines.shift();
      if (this.page === "diag") this.drawLog();
    });
    // Render at most a few times a second however fast states arrive: the
    // first burst after connecting is every entity at once.
    setInterval(() => { if (this.dirty) { this.dirty = false; this.render(); } }, 250);
  }

  // A time entity's "HH:MM:SS" as "HH:MM".
  hm(k) { const v = this.s[k]; return v ? String(v.value).slice(0, 5) : "--:--"; }
  n(k) { const v = this.s[k]; return v && v.value !== undefined ? parseFloat(v.value) : NaN; }
  str(k) { const v = this.s[k]; return v ? (v.state !== undefined ? String(v.state) : String(v.value)) : ""; }
  on(k) { const v = this.s[k]; if (!v) return false; const x = v.value; return x === true || x === 1 || x === "ON" || x === "on"; }

  act(k, action, param, value) {
    const id = this.ids[k];
    if (!id) return Promise.resolve();
    if (action === "set") this.pending[k] = true;
    const q = param ? "?" + param + "=" + encodeURIComponent(value) : "";
    return fetch("/" + id.split("/").map(encodeURIComponent).join("/") + "/" + action + q, { method: "POST" });
  }

  tick() {
    const live = this.live && Date.now() - this.live < 15000;
    this.$("d_link").classList.toggle("on", !!live);
    this.$("d_ble").classList.toggle("on", this.n(E.bleLinks) >= 1);
    this.$("clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  go() {
    const p = (location.hash || "#tank").slice(1);
    this.page = PAGES.some(([k]) => k === p) ? p : "tank";
    this.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.p === this.page));
    const m = this.$("main");
    m.innerHTML = this["page_" + this.page]();
    if (this["wire_" + this.page]) this["wire_" + this.page]();
    this.render();
  }

  render() {
    this.renderAlert();
    if (this["draw_" + this.page]) this["draw_" + this.page]();
  }

  // Faults the controller raises, said plainly at the top of every page.
  // Without Home Assistant nothing else will push these to anyone.
  renderAlert() {
    const msgs = [];
    const st = this.str(E.state);
    if (this.on(E.noProbe) || /no probe/.test(st)) msgs.push("The temperature probe is not responding. The heater is off until it reads again.");
    if (/over temperature/.test(st)) msgs.push("The water is over the safe maximum. Heating is stopped.");
    if (/under temperature/.test(st)) msgs.push("The water is under the safe minimum.");
    if (this.on(E.noHeat)) msgs.push("The heater is on but the water is not warming. Check the heater and its plug.");
    if (this.on(E.noFan)) msgs.push("The fan is on but the water is not cooling. Check the fan.");
    const a = this.$("alert");
    a.innerHTML = msgs.map(esc).join("<br>");
    a.classList.toggle("show", msgs.length > 0);
  }

  set(id, text, cls) {
    const el = this.$(id);
    if (!el) return;
    el.textContent = text;
    if (cls !== undefined) el.className = cls;
  }

  // ------------------------------------------------------------- page: tank
  page_tank() {
    return `<div class="grid">
      <div class="card row2 gauge span2" style="grid-row: span 2">
        <svg viewBox="0 0 296 300" id="gauge"></svg>
        <div class="step"><button id="dn" disabled>&minus;</button>
          <span id="sp">Setpoint --</span><button id="up" disabled>+</button></div>
      </div>
      <div class="card"><div class="lbl">Heater duty</div><div class="big heat" id="t_heat">--</div>
        <div class="sub" id="t_heatr">relay --</div></div>
      <div class="card"><div class="lbl">Fan duty</div><div class="big blue" id="t_fan">--</div>
        <div class="sub" id="t_fanr">relay --</div></div>
      <div class="card span2"><div class="lbl">Light</div><div class="big" id="t_lux">--</div>
        <div class="sub">at the sensor</div></div>
      <div class="card span2"><div class="lbl">pH</div><div class="big" id="t_ph">--</div>
        <div class="sub" id="t_phs">no probe fitted &middot; log a test on Water tests</div></div>
      <div class="card span2"><div class="lbl">TDS</div><div class="big" id="t_tds">--</div>
        <div class="sub" id="t_tdss">hour mean</div></div>
      <div class="card span4"><div class="pills">
        <span class="pill heat" id="p_heat"><i></i>HEATER</span>
        <span class="pill fan" id="p_fan"><i></i>FAN</span>
        <span class="pill co2" id="p_co2" style="display:none"><i></i>CO2</span>
        <span class="pill fan" id="p_air" style="display:none"><i></i>AIR</span>
        <span class="sub" id="t_state" style="margin:2px 0 0 8px"></span></div></div>
    </div>`;
  }

  wire_tank() {
    const nudge = (d) => {
      const v = this.n(E.target);
      if (!isNaN(v)) this.act(E.target, "set", "value", (v + d).toFixed(1));
    };
    this.$("up").onclick = () => nudge(0.5);
    this.$("dn").onclick = () => nudge(-0.5);
  }

  draw_tank() {
    const t = this.n(E.temp), sp = this.n(E.target);
    this.$("gauge").innerHTML = this.gaugeSvg(t, sp);
    this.set("sp", isNaN(sp) ? "Setpoint --" : "Setpoint " + sp.toFixed(1) + " °F");
    this.$("up").disabled = this.$("dn").disabled = !this.ids[E.target];
    const h = this.n(E.heat), f = this.n(E.fan);
    this.set("t_heat", isNaN(h) ? "--" : h.toFixed(0) + "%");
    this.set("t_fan", isNaN(f) ? "--" : f.toFixed(0) + "%");
    this.set("t_heatr", "relay " + (this.on(E.heatRelay) ? "closed" : "open"));
    this.set("t_fanr", "relay " + (this.on(E.fanRelay) ? "closed" : "open"));
    const lux = this.n(E.lux);
    this.$("t_lux").innerHTML = isNaN(lux) ? "--" : lux.toFixed(0) + "<small>lx</small>";
    const ph = this.n(E.ph);
    if (!isNaN(ph)) { this.set("t_ph", ph.toFixed(2)); this.set("t_phs", "probe"); }
    const tds = this.n(E.tds), raw = this.n(E.tdsRaw);
    this.$("t_tds").innerHTML = isNaN(tds) ? (isNaN(raw) ? "--" : raw.toFixed(0) + "<small>ppm</small>")
      : tds.toFixed(0) + "<small>ppm</small>";
    this.set("t_tdss", isNaN(tds) ? "single reading -- the hour mean is still filling" : "hour mean · now " + (isNaN(raw) ? "--" : raw.toFixed(0)));
    this.$("p_heat").classList.toggle("on", this.on(E.heatRelay));
    this.$("p_fan").classList.toggle("on", this.on(E.fanRelay));
    for (const [el, k] of [["p_co2", E.co2], ["p_air", E.air]]) {
      this.$(el).style.display = this.ids[k] ? "" : "none";
      this.$(el).classList.toggle("on", this.on(k));
    }
    this.set("t_state", this.str(E.state));
  }

  // The panel's band gauge: 270 degrees spanning setpoint -2..+2 degF,
  // blue through grey to orange, the arc filled to the temperature.
  gaugeSvg(t, sp) {
    const CX = 148, CY = 150, R = 94;
    const lo = isNaN(sp) ? 72 : sp - 2, hi = isNaN(sp) ? 76 : sp + 2;
    const pt = (a) => [CX + R * Math.cos(a * Math.PI / 180), CY + R * Math.sin(a * Math.PI / 180)];
    const arc = (a0, a1) => {
      const [x0, y0] = pt(a0), [x1, y1] = pt(a1);
      return `M${x0.toFixed(1)},${y0.toFixed(1)} A${R},${R} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(1)},${y1.toFixed(1)}`;
    };
    let fill = "";
    if (!isNaN(t)) {
      const frac = Math.max(0, Math.min(1, (t - lo) / (hi - lo)));
      if (frac > 0.002) fill = `<path d="${arc(135, 135 + 270 * frac)}" stroke="url(#gg)" stroke-width="16" fill="none"/>`;
    }
    const st = this.str(E.state);
    const fault = this.on(E.noProbe) || /fault|over temp|under temp/.test(st);
    const [label, col] = fault ? ["SAFETY TRIPPED", C.bad] : this.on(E.heatRelay) ? ["HEATING", C.heat]
      : this.on(E.fanRelay) ? ["COOLING", C.blue] : ["IDLE", C.muted];
    const [tx, ty] = pt(270);
    return `<defs><linearGradient id="gg" x1="0" x2="1"><stop offset="0" stop-color="${C.blue}"/>
        <stop offset=".5" stop-color="#7f8b96"/><stop offset="1" stop-color="${C.orange}"/></linearGradient></defs>
      <path d="${arc(135, 405)}" stroke="${C.track}" stroke-width="16" fill="none"/>${fill}
      <line x1="${tx}" y1="${ty - 12}" x2="${tx}" y2="${ty - 24}" stroke="#fff" stroke-width="2"/>
      <text x="${CX}" y="${CY + 8}" text-anchor="middle" font-size="64" font-weight="600" fill="${isNaN(t) ? C.muted : "#fff"}">${isNaN(t) ? "--.-" : t.toFixed(1)}</text>
      <text x="${CX + 82}" y="${CY - 24}" text-anchor="middle" font-size="17" fill="${C.muted}">F</text>
      <text x="${CX}" y="${CY + 50}" text-anchor="middle" font-size="12" font-weight="700" letter-spacing="1" fill="${col}">${label}</text>`;
  }

  // ----------------------------------------------------------- page: vessel
  page_vessel() {
    return `<div class="vessel">
      <div class="card" style="padding:8px"><svg viewBox="0 30 576 410" id="tankdraw"></svg></div>
      <div class="rail">
        <div class="card"><div class="lbl">Water temperature</div><div class="big" id="v_t">--.-</div>
          <div class="sub" id="v_hs">IDLE</div></div>
        <div class="card"><div class="lbl">Heater duty</div><div class="big heat" id="v_h">--</div></div>
        <div class="card"><div class="lbl">Fan duty</div><div class="big blue" id="v_f">--</div></div>
        <div class="card" id="v_aux" style="display:none"><div class="lbl">CO2 &middot; Bubbler</div>
          <div class="med" id="v_co2">--</div><div class="sub" id="v_sched"></div></div>
      </div></div>`;
  }

  draw_vessel() {
    const t = this.n(E.temp), heating = this.on(E.heatRelay), fanOn = this.on(E.fanRelay);
    this.set("v_t", isNaN(t) ? "--.-" : t.toFixed(1));
    this.set("v_hs", heating ? "HEATING" : "IDLE", "sub " + (heating ? "heat" : ""));
    const h = this.n(E.heat), f = this.n(E.fan);
    this.set("v_h", isNaN(h) ? "--" : h.toFixed(0) + "%");
    this.set("v_f", isNaN(f) ? "--" : f.toFixed(0) + "%");
    this.$("tankdraw").innerHTML = this.tankSvg(t, heating, fanOn);
    if (this.ids[E.co2]) {
      this.$("v_aux").style.display = "";
      this.$("v_co2").innerHTML = `<span class="${this.on(E.co2) ? "aqua" : "muted"}">CO2 ${this.on(E.co2) ? "on" : "off"}</span> &middot; `
        + `<span class="${this.on(E.air) ? "blue" : "muted"}">air ${this.on(E.air) ? "on" : "off"}</span>`;
      this.set("v_sched", this.on(E.co2Sched) ? "CO2 " + this.hm(E.co2On) + "–" + this.hm(E.co2Off) : "CO2 schedule off");
    }
  }

  // The panel's Vessel drawing, from the same arithmetic as the lambda in
  // boards/waveshare-esp32s3-lcd-43.yaml (single-system branch), so a
  // change to one is a change to look for in the other.
  tankSvg(t, heating, fanOn) {
    const FX0 = 24, FX1 = 552, FY1 = 386;
    const FY0 = 386 - Math.min(330, Math.max(150, Math.floor(528 * LY.h / LY.w)));
    const vpy = FY0 + Math.floor((FY1 - FY0) * 120 / 330);
    const BX0 = 130, BX1 = 446;
    const BY0 = vpy + Math.trunc((FY0 - vpy) * 0.6), BY1 = vpy + Math.trunc((FY1 - vpy) * 0.6);
    const vy = (y) => BY0 + Math.trunc((y - 104) * (BY1 - BY0) / 198);
    const fy = (y) => FY0 + Math.trunc((y - 56) * (FY1 - FY0) / 330);
    const fs = (FY1 - FY0) / 330, ppi = (BX1 - BX0) / LY.w;
    const X = (inch) => BX0 + Math.trunc(inch * ppi);
    const r = (x, y, w, h, c, extra = "") => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${c}" ${extra}/>`;
    const poly = (pts, c) => `<polygon points="${pts.map((p) => p.join(",")).join(" ")}" fill="${c}"/>`;
    const SBY = vy(296), SFY = fy(356);
    let s = `<defs>
      <linearGradient id="surf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="rgb(120,200,226)"/><stop offset="1" stop-color="rgb(90,170,200)"/></linearGradient>
      <linearGradient id="wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="rgb(58,144,184)"/><stop offset="1" stop-color="rgb(12,47,71)"/></linearGradient>
      <linearGradient id="sub" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="rgb(53,67,78)"/><stop offset="1" stop-color="rgb(36,36,42)"/></linearGradient>
      <radialGradient id="glow"><stop offset="0" stop-color="rgb(255,122,60)" stop-opacity=".55"/><stop offset="1" stop-color="rgb(255,122,60)" stop-opacity="0"/></radialGradient>
      <clipPath id="wallclip"><rect x="${BX0}" y="${BY0}" width="${BX1 - BX0}" height="${BY1 - BY0}"/></clipPath></defs>`;
    s += poly([[FX0, FY0], [FX1, FY0], [BX1, BY0], [BX0, BY0]], "url(#surf)");
    s += poly([[FX0, FY0], [BX0, BY0], [BX0, BY1], [FX0, FY1]], "rgb(14,44,64)");
    s += poly([[FX1, FY0], [BX1, BY0], [BX1, BY1], [FX1, FY1]], "rgb(14,44,64)");
    s += r(BX0, BY0, BX1 - BX0, BY1 - BY0, "url(#wall)");
    s += poly([[BX0, SBY], [BX1, SBY], [FX1, FY1], [FX0, FY1]], "url(#sub)");
    const sand = Math.trunc(12 * fs), soil = Math.trunc(16 * fs);
    s += r(FX0, SFY, FX1 - FX0, sand, "rgb(38,38,44)") + r(FX0, SFY + sand, FX1 - FX0, soil, "rgb(45,34,24)");

    // Heater, with its glow while the relay is closed.
    const hx = X(LY.heaterIn);
    if (heating) s += `<circle cx="${hx}" cy="${vy(216)}" r="54" fill="url(#glow)" clip-path="url(#wallclip)"/>`;
    s += r(hx - 6, vy(150), 12, vy(258) - vy(150), "rgb(45,77,95)");
    s += r(hx - 4, vy(166), 8, vy(250) - vy(166), heating ? "rgb(232,130,63)" : "rgb(70,86,96)");
    // Probe.
    const px = X(LY.probeIn);
    s += r(px - 4, vy(172), 8, vy(238) - vy(172), "rgb(38,54,63)");
    s += `<circle cx="${px}" cy="${vy(242)}" r="6" fill="rgb(74,163,240)"/>`;
    // Dual sponge filter: two sponges teed into one lift tube.
    if (LY.sponge) {
      const cx = X(LY.spongeIn), off = Math.trunc(LY.spongeSp * ppi / 2), w = Math.max(20, Math.trunc(3 * ppi));
      const top = vy(226), bot = vy(300), tee = top - 14, lift = vy(132);
      s += r(cx + 6, BY0, 2, lift - BY0, "rgb(150,170,180)");
      s += r(cx - 4, lift, 8, tee - lift, "rgb(70,120,140)");
      s += `<g class="bubbles">`;
      for (let y = lift + 8; y < tee - 4; y += 12) s += `<circle cx="${cx}" cy="${y}" r="2" fill="rgb(190,225,240)"/>`;
      s += `</g>` + r(cx - off - 4, tee, 2 * off + 8, 7, "rgb(70,120,140)");
      for (const sx of [cx - off, cx + off]) {
        s += r(sx - 4, tee + 7, 8, top - 6 - tee - 7, "rgb(70,120,140)");
        s += r(sx - w / 2 - 2, top - 6, w + 4, 6, "rgb(40,52,58)");
        s += r(sx - w / 2, top, w, bot - top, "rgb(46,58,54)");
        for (let y = top + 5; y < bot - 2; y += 7)
          for (let x = sx - w / 2 + 4 + ((Math.floor(y / 7) & 1) * 3); x < sx + w / 2 - 2; x += 6)
            s += r(x, y, 2, 2, "rgb(30,38,36)");
      }
      s += r(cx - off - w / 2 - 4, bot, 2 * off + w + 8, 5, "rgb(40,52,58)");
    }
    // Fan on the back rim; the blades turn while its relay is closed.
    const fx = X(LY.fanIn), fyy = BY0 - 30;
    s += r(fx - 3, BY0 - 4, 6, 18, "rgb(40,52,60)") + r(fx - 2, fyy + 10, 4, BY0 - 4 - fyy - 10, "rgb(40,52,60)");
    s += `<circle cx="${fx}" cy="${fyy}" r="15" fill="rgb(40,52,60)"/>
      <circle cx="${fx}" cy="${fyy}" r="12" fill="${fanOn ? "rgb(57,135,229)" : "rgb(70,86,96)"}"/>
      <g class="fanblades${fanOn ? " on" : ""}" style="transform-origin:${fx}px ${fyy}px">`;
    for (let a = 45; a < 405; a += 90) {
      const rad = a * Math.PI / 180;
      s += `<line x1="${fx + 3 * Math.cos(rad)}" y1="${fyy + 3 * Math.sin(rad)}" x2="${fx + 11 * Math.cos(rad)}" y2="${fyy + 11 * Math.sin(rad)}" stroke="rgb(40,52,60)" stroke-width="2"/>`;
    }
    s += `</g><circle cx="${fx}" cy="${fyy}" r="3" fill="rgb(40,52,60)"/>`;
    // Rimless glass.
    const edge = 'stroke="rgb(143,196,220)" stroke-width="1" fill="none"';
    s += `<rect x="${FX0}" y="${FY0}" width="${FX1 - FX0}" height="${FY1 - FY0}" ${edge}/>`;
    for (const [a, b, c, d] of [[FX1, FY0, BX1, BY0], [BX1, BY0, BX1, BY1], [BX1, BY1, FX1, FY1], [FX0, FY0, BX0, BY0],
      [BX0, BY0, BX0, BY1], [BX0, BY1, FX0, FY1], [BX0, BY0, BX1, BY0]])
      s += `<line x1="${a}" y1="${b}" x2="${c}" y2="${d}" ${edge}/>`;
    s += r(282, FY0, 13, BY0 - FY0, "rgb(168,216,236)");
    // The probe's reading over the probe, as on the panel.
    const cy = Math.max(44, FY0 - 40), cxo = px - 42;
    s += `<rect x="${cxo}" y="${cy}" width="84" height="32" rx="8" fill="rgb(6,10,14)" stroke="#2a323c"/>
      <text x="${px}" y="${cy + 23}" text-anchor="middle" font-size="22" font-weight="600" fill="${isNaN(t) ? C.muted : "#fff"}">${isNaN(t) ? "--" : t.toFixed(1)}</text>`;
    // Labels, two rows like the panel.
    const lbl = (x, y, txt) => `<text x="${x}" y="${y}" text-anchor="middle" font-size="12" font-weight="600" fill="${C.muted}">${txt}</text>`;
    s += lbl(hx, 408, "HEATER") + lbl(px, 422, "PROBE") + lbl(fx, 408, "FAN");
    if (LY.sponge) s += lbl(X(LY.spongeIn), 408, "SPONGE FILTER");
    return s;
  }

  // ---------------------------------------------------------- page: history
  page_history() {
    return `<div class="actions" style="margin:0 0 12px">
        <div class="seg"><button data-r="day">24 hours</button><button data-r="month">30 days</button></div>
        <span class="sub" id="h_msg"></span>
        <span style="margin-left:auto"><a class="btn" id="h_dl" download>Download data</a></span></div>
      <div class="grid">
        <div class="card span4"><div class="lbl">Water temperature &deg;F</div>
          <svg class="chart" id="c_temp"></svg>
          <div class="legend"><span><i style="background:#fff"></i>water</span><span><i style="background:${C.muted}"></i>target</span></div></div>
        <div class="card span2"><div class="lbl">TDS ppm</div><svg class="chart" id="c_tds"></svg>
          <div class="legend"><span><i style="background:${C.blue}"></i>hour mean</span><span><i style="background:#596574"></i>single readings</span></div></div>
        <div class="card span2"><div class="lbl">Light lux</div><svg class="chart" id="c_lux"></svg></div>
        <div class="card span4"><div class="lbl">Heater and fan duty %</div><svg class="chart" id="c_duty"></svg>
          <div class="legend"><span><i style="background:${C.heat}"></i>heater</span><span><i style="background:${C.blue}"></i>fan</span></div></div>
        <div class="card span4" id="h_aux" style="display:none"><div class="lbl">CO2 and bubbler, % of the time on</div><svg class="chart" id="c_aux"></svg>
          <div class="legend"><span><i style="background:#199e70"></i>CO2</span><span><i style="background:${C.blue}"></i>bubbler</span></div></div>
      </div>`;
  }

  wire_history() {
    this.querySelectorAll(".seg button").forEach((b) => {
      b.onclick = () => { this.range = b.dataset.r; this.loadHistory(); };
    });
    this.loadHistory();
    clearInterval(this.histTimer);
    this.histTimer = setInterval(() => { if (this.page === "history") this.loadHistory(); }, 60000);
  }

  loadHistory() {
    this.querySelectorAll(".seg button").forEach((b) => b.classList.toggle("on", b.dataset.r === this.range));
    this.$("h_dl").href = "/history.json?range=" + this.range;
    this.$("h_dl").setAttribute("download", "tank-history-" + this.range + ".json");
    fetch("/history.json?range=" + this.range).then((r) => r.json()).then((d) => {
      this.hist = d;
      this.set("h_msg", d.end ? "" : "No history yet -- the first point lands within five minutes of the clock being set.");
      this.drawCharts();
    }).catch(() => this.set("h_msg", "Could not load history from the device."));
  }

  drawCharts() {
    const d = this.hist;
    if (!d || this.page !== "history") return;
    const S = d.series;
    this.chart("c_temp", d, [{ v: S.target, c: C.muted, w: 1.5, dash: "4 4" }, { v: S.temp, c: "#fff", w: 2 }], 1);
    this.chart("c_tds", d, [{ v: S.tdsraw, c: "#596574", w: 1 }, { v: S.tds, c: C.blue, w: 2 }], 0);
    this.chart("c_lux", d, [{ v: S.lux, c: "#e8c547", w: 1.5 }], 0);
    this.chart("c_duty", d, [{ v: S.heat, c: C.heat, w: 1.5 }, { v: S.fan, c: C.blue, w: 1.5 }], 0, [0, 100]);
    if (S.co2) {
      this.$("h_aux").style.display = "";
      this.chart("c_aux", d, [{ v: S.air, c: C.blue, w: 1.5 }, { v: S.co2, c: "#199e70", w: 2 }], 0, [0, 100]);
    }
  }

  // A line chart in plain SVG, sized to its box. null is a gap, never a
  // line drawn across an outage.
  chart(id, d, lines, dp, fixed) {
    const el = this.$(id);
    if (!el) return;
    const W = Math.max(200, el.clientWidth), H = 190, L = 40, R = 8, T = 8, B = 22;
    el.setAttribute("viewBox", `0 0 ${W} ${H}`);
    let lo = Infinity, hi = -Infinity;
    for (const ln of lines) for (const v of ln.v || []) if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    if (fixed) [lo, hi] = fixed;
    if (lo === Infinity) { el.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle">No data yet</text>`; return; }
    if (!fixed) {
      if (hi - lo < (dp ? 0.5 : 5)) { const m = (hi + lo) / 2, half = dp ? 0.25 : 2.5; lo = m - half; hi = m + half; }
      const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
      // Nothing charted here can be negative; padding must not invent it.
      if (lo < 0 && lines.every((ln) => (ln.v || []).every((v) => v === null || v >= 0))) lo = 0;
    }
    const n = d.slots, xs = (i) => L + (W - L - R) * i / (n - 1), ys = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
    let s = "";
    for (let k = 0; k <= 4; k++) {
      const v = lo + (hi - lo) * k / 4, y = ys(v);
      s += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="#1e252e"/><text x="${L - 6}" y="${y + 4}" text-anchor="end">${v.toFixed(dp)}</text>`;
    }
    const start = d.end - (n - 1) * d.step, ticks = W < 520 ? 3 : 6;
    for (let k = 0; k <= ticks; k++) {
      const i = Math.round((n - 1) * k / ticks);
      s += `<text x="${xs(i)}" y="${H - 6}" text-anchor="${k === 0 ? "start" : k === ticks ? "end" : "middle"}">${fmtTime(start + i * d.step, (n - 1) * d.step > 86400)}</text>`;
    }
    for (const ln of lines) {
      let p = "", pen = false;
      (ln.v || []).forEach((v, i) => {
        if (v === null) { pen = false; return; }
        p += (pen ? "L" : "M") + xs(i).toFixed(1) + "," + ys(v).toFixed(1);
        pen = true;
      });
      s += `<path d="${p}" fill="none" stroke="${ln.c}" stroke-width="${ln.w}" ${ln.dash ? `stroke-dasharray="${ln.dash}"` : ""} stroke-linejoin="round"/>`;
    }
    el.innerHTML = s;
  }

  // ------------------------------------------------------------ page: tests
  page_tests() {
    const P = [["ph", "pH", "0.1"], ["nh3", "Ammonia ppm", "0.01"], ["no2", "Nitrite ppm", "0.01"], ["no3", "Nitrate ppm", "1"]];
    return `<div class="grid">
      <div class="card span4"><div class="lbl">Last test</div><div class="grid" id="w_last" style="margin-top:10px"></div>
        <div class="sub" id="w_age"></div></div>
      <div class="card span4"><div class="lbl">Log a test</div>
        <div class="form">
          ${P.map(([k, l, st]) => `<label class="fld"><span class="sub">${l}</span><input type="number" step="${st}" min="0" id="f_${k}"></label>`).join("")}
          <label class="fld"><span class="sub">GH</span><input type="number" step="any" min="0" id="f_gh"></label>
          <label class="fld"><span class="sub">KH</span><input type="number" step="any" min="0" id="f_kh"></label>
          <label class="fld"><span class="sub">GH / KH in</span><select id="f_unit">
            <option value="deg">degrees (drops)</option><option value="ppm">ppm</option></select></label>
          <label class="fld"><span class="sub">Tested at</span><input type="datetime-local" id="f_when"></label>
        </div>
        <div class="actions"><button class="btn primary" id="f_save">Save test</button><span class="msg" id="f_msg"></span></div>
        <div class="note">Leave a box empty for anything you did not test. Drop-count kits (GH/KH) are in degrees:
          one drop is one degree, stored as ppm (&times;17.86). Tests are kept on the controller &mdash; the last 40.</div></div>
      <div class="card span4"><div class="lbl">History</div>
        <div style="overflow:auto"><table id="w_log"></table></div>
        <div class="actions"><a class="btn" href="/tests.json" download="water-tests.json">Download tests</a></div></div>
    </div>`;
  }

  wire_tests() {
    const pad = (x) => String(x).padStart(2, "0");
    const d = new Date();
    this.$("f_when").value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    this.$("f_save").onclick = () => this.saveTest();
    this.loadTests();
  }

  loadTests() {
    fetch("/tests.json").then((r) => r.json()).then((d) => { this.tests = d; this.drawTests(); })
      .catch(() => this.set("w_age", "Could not load tests from the device."));
  }

  saveTest() {
    const q = [];
    const unit = this.$("f_unit").value;
    for (const k of ["ph", "nh3", "no2", "no3", "gh", "kh"]) {
      const raw = this.$("f_" + k).value.trim();
      if (raw === "") continue;
      let v = parseFloat(raw);
      if ((k === "gh" || k === "kh") && unit === "deg") v = Math.round(v * GH_PER_DEG);
      q.push(k + "=" + encodeURIComponent(v));
    }
    const when = this.$("f_when").value;
    if (when) {
      const t = Math.floor(new Date(when).getTime() / 1000);
      // Only send a time that differs from now: the device stamps now itself.
      if (Math.abs(t - Date.now() / 1000) > 120) q.push("t=" + t);
    }
    if (!q.length) { this.set("f_msg", "Enter at least one result.", "msg bad"); return; }
    this.$("f_save").disabled = true;
    fetch("/tests?" + q.join("&"), { method: "POST" }).then(async (r) => {
      const msg = await r.text();
      if (!r.ok) throw new Error(msg);
      this.set("f_msg", "Saved.", "msg good");
      for (const k of ["ph", "nh3", "no2", "no3", "gh", "kh"]) this.$("f_" + k).value = "";
      this.loadTests();
    }).catch((e) => this.set("f_msg", e.message || "Could not save.", "msg bad"))
      .finally(() => { this.$("f_save").disabled = false; });
  }

  drawTests() {
    const d = this.tests;
    if (!d || this.page !== "tests") return;
    const f = (v, dp) => (v === null || v === undefined ? "--" : Number(v).toFixed(dp));
    const deg = (v) => (v === null || v === undefined ? "" : ` <span class="sub">(${(v / GH_PER_DEG).toFixed(1)}&deg;)</span>`);
    const last = d.tests[0];
    const tile = (l, v) => `<div><div class="lbl">${l}</div><div class="med">${v}</div></div>`;
    this.$("w_last").innerHTML = last
      ? tile("pH", f(last.ph, 1)) + tile("Ammonia", f(last.nh3, 2)) + tile("Nitrite", f(last.no2, 2))
        + tile("Nitrate", f(last.no3, 0)) + tile("GH ppm", f(last.gh, 0) + deg(last.gh)) + tile("KH ppm", f(last.kh, 0) + deg(last.kh))
      : `<div class="sub">No tests logged yet.</div>`;
    if (last && d.now) {
      const age = d.now - last.t;
      this.set("w_age", "Tested " + fmtTime(last.t, true) + " · " + ago(age), "sub" + (age > 172800 ? " bad" : ""));
    } else this.set("w_age", "");
    const rows = d.tests.map((x) => `<tr><td>${fmtTime(x.t, true)}</td><td class="v">${f(x.ph, 1)}</td><td class="v">${f(x.nh3, 2)}</td>
        <td class="v">${f(x.no2, 2)}</td><td class="v">${f(x.no3, 0)}</td><td class="v">${f(x.gh, 0)}</td><td class="v">${f(x.kh, 0)}</td>
        <td class="v"><button class="btn warn" data-t="${x.t}" style="padding:3px 10px">Delete</button></td></tr>`).join("");
    this.$("w_log").innerHTML = `<tr><th>When</th><th class="v">pH</th><th class="v">NH3</th><th class="v">NO2</th><th class="v">NO3</th>
        <th class="v">GH</th><th class="v">KH</th><th></th></tr>` + (rows || `<tr><td colspan="8" class="sub">Nothing yet.</td></tr>`);
    this.querySelectorAll("#w_log button[data-t]").forEach((b) => {
      b.onclick = () => {
        if (!confirm("Delete the test from " + fmtTime(+b.dataset.t, true) + "?")) return;
        fetch("/tests/delete?t=" + b.dataset.t, { method: "POST" }).then(() => this.loadTests());
      };
    });
  }

  // --------------------------------------------------------- page: settings
  page_settings() {
    const numF = (id, label, k, step) => `<label class="fld"><span class="sub">${label}</span>
      <input type="number" step="${step}" id="${id}" data-k="${k}" disabled></label>`;
    return `<div class="grid">
      <div class="card span2"><div class="lbl">Temperature control</div>
        <div class="form">
          ${numF("s_target", "Target &deg;F", E.target, "0.1")}
          ${numF("s_deadband", "Fan starts above target by &deg;F", E.deadband, "0.05")}
        </div>
        <div class="tog" style="margin-top:12px"><span>Adaptive learning</span><button class="sw" id="s_learn" disabled></button></div>
        <div class="note">The controller learns how this tank gains and loses heat and plans the heater from that.
          Leave it on.</div></div>
      <div class="card span2"><div class="lbl">The tank</div>
        <div class="form">
          ${numF("s_vol", "Tank size, gal", E.vol, "1")}
          ${numF("s_water", "Water in it, gal", E.water, "0.5")}
          ${numF("s_power", "Heater rating, W", E.power, "5")}
          <label class="fld"><span class="sub">Cover</span><select id="s_cover" data-k="${E.cover}" disabled></select></label>
          <label class="fld"><span class="sub">Placement</span><select id="s_place" data-k="${E.placement}" disabled></select></label>
        </div>
        <div class="note">Read the heater's wattage off its label. These seed the model; it still learns the rest.</div></div>
      <div class="card span4" id="s_aux" style="display:none"><div class="lbl">CO2 and bubbler</div>
        <div class="tog"><span>CO2 schedule<div class="sub">Runs CO2 between the times below, every day.</div></span>
          <button class="sw" id="s_co2sched" disabled></button></div>
        <div class="form">
          <label class="fld"><span class="sub">CO2 on at</span><input type="time" id="s_co2on" data-t="${E.co2On}" disabled></label>
          <label class="fld"><span class="sub">CO2 off at</span><input type="time" id="s_co2off" data-t="${E.co2Off}" disabled></label>
          <label class="fld"><span class="sub">Bubbler back on at</span><input type="time" id="s_airon" data-t="${E.airOn}" disabled></label>
        </div>
        <div class="tog" style="margin-top:8px"><span>CO2 solenoid now</span><button class="sw" id="s_co2" disabled></button></div>
        <div class="tog"><span>Bubbler now</span><button class="sw" id="s_air" disabled></button></div>
        <div class="note">With the schedule on, the bubbler is off from CO2-on until "back on at" so it does not
          blow the gas out, and on the rest of the time. Switching either outlet here overrides the schedule until
          its next change. Failsafes: no clock means CO2 off and air on, and an override left on for 2 hours is put
          back. There is <b>no pH probe</b> on this tank, so nothing measures what the CO2 is doing &mdash; set the
          bubble rate low and watch the fish through the first days.</div></div>
      <div class="card span4"><div class="lbl">Calibration</div>
        <div class="form">
          ${numF("s_std", "TDS standard, ppm (on the bottle)", E.calStd, "1")}
          <div class="fld"><span class="sub">TDS reading now</span><div class="med" id="s_tdsnow">--</div></div>
          <div class="fld"><span class="sub">K factor</span><div class="med" id="s_k">--</div></div>
          <div class="fld" style="justify-content:flex-end"><button class="btn" id="s_caltds" disabled>Calibrate TDS</button></div>
        </div>
        <div class="note">Stand the probe in the standard, wait for the reading to settle, then press. Bring the
          standard to tank temperature first &mdash; conductivity moves about 2% per &deg;C.</div>
        <div class="form" style="margin-top:16px">
          ${numF("s_off", "Temperature offset &deg;F", E.calOff, "0.1")}
          <div class="fld"><span class="sub">Probe reads now</span><div class="med" id="s_tnow">--</div></div>
        </div>
        <div class="note">Against a trusted thermometer. This probe is the only one the heater listens to.</div></div>
      <div class="card span4"><div class="lbl">Device</div>
        <div class="actions"><button class="btn" id="s_restart" disabled>Restart</button>
          <button class="btn warn" id="s_reset" disabled>Reset learning</button>
          <button class="btn warn" id="s_factory" disabled>Factory reset</button></div>
        <div class="note">Factory reset wipes everything stored on this controller &mdash; calibrations, the learned
          heat model, history, water tests, CO2 times and saved Wi-Fi &mdash; and starts over on the defaults. The
          panel's SD card backups can bring settings back afterwards (Archive).</div></div>
    </div>`;
  }

  wire_settings() {
    this.querySelectorAll("input[data-k]").forEach((el) => {
      el.onchange = () => { const v = parseFloat(el.value); if (!isNaN(v)) this.act(el.dataset.k, "set", "value", v); };
    });
    this.querySelectorAll("select[data-k]").forEach((el) => {
      el.onchange = () => this.act(el.dataset.k, "set", "option", el.value);
    });
    this.$("s_learn").onclick = () => this.act(E.learn, "toggle");
    this.$("s_co2sched").onclick = () => {
      if (!this.on(E.co2Sched) && !confirm("Start the CO2 schedule? CO2 will run every day between the times shown.")) return;
      this.act(E.co2Sched, "toggle");
    };
    this.$("s_co2").onclick = () => this.act(E.co2, "toggle");
    this.$("s_air").onclick = () => this.act(E.air, "toggle");
    this.querySelectorAll("input[data-t]").forEach((el) => {
      el.onchange = () => { if (el.value) this.act(el.dataset.t, "set", "value", el.value + ":00"); };
    });
    this.$("s_caltds").onclick = () => {
      if (this.pending[E.calStd]) { alert("The new standard has not reached the device yet. Press again in a moment."); return; }
      if (confirm(`Set the TDS calibration so the probe reads ${this.n(E.calStd).toFixed(0)} ppm right now?`)) this.act(E.calTds, "press");
    };
    this.$("s_restart").onclick = () => confirm("Restart the controller?") && this.act(E.restart, "press");
    this.$("s_reset").onclick = () => confirm("Discard everything the controller has learned about this tank?") && this.act(E.reset, "press");
    this.$("s_factory").onclick = () =>
      confirm("Factory reset: wipe ALL settings, calibrations, history and water tests on this controller?") &&
      confirm("Really? This cannot be undone here. The controller restarts on its defaults.") &&
      this.act(E.factory, "press");
  }

  draw_settings() {
    this.querySelectorAll("input[data-k]").forEach((el) => {
      const k = el.dataset.k, v = this.n(k), st = this.s[k];
      el.disabled = !this.ids[k];
      if (st) { if (st.min_value !== undefined) el.min = st.min_value; if (st.max_value !== undefined) el.max = st.max_value; }
      if (!isNaN(v) && document.activeElement !== el) el.value = v;
    });
    this.querySelectorAll("select[data-k]").forEach((el) => {
      const k = el.dataset.k, st = this.s[k];
      el.disabled = !this.ids[k];
      if (st && st.option && el.options.length !== st.option.length)
        el.innerHTML = st.option.map((o) => `<option>${esc(o)}</option>`).join("");
      if (st && document.activeElement !== el) el.value = st.value;
    });
    this.$("s_aux").style.display = this.ids[E.co2] ? "" : "none";
    for (const [el, k] of [["s_co2sched", E.co2Sched], ["s_co2", E.co2], ["s_air", E.air]]) {
      this.$(el).classList.toggle("on", this.on(k));
      this.$(el).disabled = !this.ids[k];
    }
    this.querySelectorAll("input[data-t]").forEach((el) => {
      el.disabled = !this.ids[el.dataset.t];
      if (document.activeElement !== el && this.s[el.dataset.t]) el.value = this.hm(el.dataset.t);
    });
    this.$("s_learn").classList.toggle("on", this.on(E.learn));
    this.$("s_learn").disabled = !this.ids[E.learn];
    const raw = this.n(E.tdsRaw), k = this.n(E.calK), t = this.n(E.temp);
    this.set("s_tdsnow", isNaN(raw) ? "--" : raw.toFixed(0) + " ppm");
    this.set("s_k", isNaN(k) ? "--" : k.toFixed(2) + "x");
    this.set("s_tnow", isNaN(t) ? "--" : t.toFixed(2) + " °F");
    this.$("s_caltds").disabled = !(this.ids[E.calTds] && !isNaN(this.n(E.calStd)));
    this.$("s_restart").disabled = !this.ids[E.restart];
    this.$("s_reset").disabled = !this.ids[E.reset];
    this.$("s_factory").disabled = !this.ids[E.factory];
  }

  // ---------------------------------------------------------- page: archive
  // Everything on the panel's SD card, reached directly from this page: the
  // panel reports its Wi-Fi address to the controller over BLE (/peer.json)
  // and answers with CORS. A typed-in address is the fallback.
  page_archive() {
    return `<div class="grid">
      <div class="card span4"><div class="lbl">SD card on the panel</div>
        <dl class="kv" id="a_status" style="margin-top:10px"><dt>Panel</dt><dd>looking&hellip;</dd></dl>
        <div class="actions"><button class="btn" id="a_now" disabled>Back up now</button>
          <span class="msg" id="a_msg"></span>
          <span style="margin-left:auto" class="sub">Panel address <input id="a_ip" style="width:150px;display:inline-block" placeholder="auto"></span></div>
        <div class="note">The panel writes a history row every 5 minutes and, every night at 03:00, saves this
          controller's settings, learned heat model and water tests, plus a copy of any firmware it has not seen.
          The two talk over Bluetooth, so all of that carries on through a Wi-Fi outage; only this page needs Wi-Fi
          to reach the panel. The panel reports its address over Bluetooth too.</div></div>
      <div class="card span4"><div class="lbl">History beyond 30 days</div>
        <div class="actions" style="margin-top:6px"><select id="a_month" style="max-width:200px"></select>
          <a class="btn" id="a_csv">Download CSV</a><span class="sub" id="a_hmsg"></span></div>
        <svg class="chart" id="ac_temp"></svg>
        <div class="legend"><span><i style="background:#fff"></i>water &deg;F</span><span><i style="background:${C.muted}"></i>target</span></div>
        <svg class="chart" id="ac_tds"></svg>
        <div class="legend"><span><i style="background:${C.blue}"></i>TDS hour mean</span></div></div>
      <div class="card span4"><div class="lbl">Settings backups</div>
        <div style="overflow:auto;margin-top:6px"><table id="a_backups"></table></div>
        <div class="note">Restore puts this controller back the way it was that night. Choose what to bring back:
          settings (targets, tank details, calibration, CO2 times), the learned heat model, and water tests
          (merged &mdash; nothing logged since is lost).</div></div>
      <div class="card span4"><div class="lbl">Firmware</div>
        <dl class="kv" id="a_slots" style="margin-top:10px"></dl>
        <div class="actions"><button class="btn warn" id="a_rollback" disabled>Roll back to the previous firmware</button>
          <span class="msg" id="a_fmsg"></span></div>
        <div style="overflow:auto;margin-top:12px"><table id="a_fw"></table></div>
        <div class="note">Roll back uses the build this controller ran before its last update &mdash; no SD needed.
          The SD keeps every build ever run; Install puts one of those back. Panel builds install from the panel's
          own page.</div></div>
    </div>`;
  }

  // The panel's base URL, or "" while unknown.
  panelBase() {
    const manual = (localStorage.getItem("panel_ip") || "").trim();
    const ip = manual || this.peerIp || "";
    return ip ? "http://" + ip : "";
  }

  wire_archive() {
    const ipBox = this.$("a_ip");
    ipBox.value = localStorage.getItem("panel_ip") || "";
    ipBox.onchange = () => { localStorage.setItem("panel_ip", ipBox.value.trim()); this.loadArchive(); };
    this.$("a_now").onclick = () => {
      fetch(this.panelBase() + "/sd/backup-now", { method: "POST" })
        .then(() => this.set("a_msg", "Started -- refresh in a minute.", "msg good"))
        .catch(() => this.set("a_msg", "The panel did not answer.", "msg bad"));
    };
    this.$("a_month").onchange = () => this.loadMonth();
    this.$("a_rollback").onclick = () => {
      const p = this.slots && this.slots.previous;
      if (!p || !p.valid) return;
      if (!confirm(`Restart this controller on the previous firmware (built ${p.built})?`)) return;
      fetch("/firmware/rollback", { method: "POST" }).then(async (r) => {
        this.set("a_fmsg", await r.text(), "msg " + (r.ok ? "good" : "bad"));
      });
    };
    fetch("/peer.json").then((r) => r.json()).then((d) => { this.peerIp = d.panel_ip; this.loadArchive(); })
      .catch(() => this.loadArchive());
    fetch("/firmware/slots.json").then((r) => r.json()).then((d) => { this.slots = d; this.drawSlots(); });
  }

  drawSlots() {
    const d = this.slots;
    if (!d || !this.$("a_slots")) return;
    const row = (l, o) => `<dt>${l}</dt><dd>${o && o.valid !== false && o.firmware
      ? esc(o.built + " · " + o.firmware.slice(0, 8)) : "none"}</dd>`;
    this.$("a_slots").innerHTML = row("Running", d.running) + row("Previous", d.previous);
    this.$("a_rollback").disabled = !(d.previous && d.previous.valid && d.previous.firmware);
  }

  loadArchive() {
    const base = this.panelBase();
    if (!base) {
      this.$("a_status").innerHTML = `<dt>Panel</dt><dd class="bad">not found on the network yet &mdash; type its address</dd>`;
      return;
    }
    const get = (path) => fetch(base + path).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
    get("/sd/status.json").then((st) => {
      this.$("a_now").disabled = !st.mounted;
      const kv = (l, v, cls = "") => `<dt>${l}</dt><dd class="${cls}">${esc(v)}</dd>`;
      this.$("a_status").innerHTML = kv("Panel", base.replace("http://", ""))
        + (st.mounted ? kv("Card", `${st.card || "SD"} · ${(st.free_mb / 1024).toFixed(1)} of ${(st.total_mb / 1024).toFixed(1)} GB free`)
          : kv("Card", "not working: " + st.error, "bad"))
        + kv("History rows written", st.rows_written + (st.last_row ? " · last " + fmtTime(st.last_row, true) : ""))
        + kv("Last nightly backup", st.last_backup || "not yet", /failed/.test(st.last_backup) ? "bad" : "");
      if (!st.mounted) return;
      get("/sd/list.json?dir=history").then((d) => {
        const sel = this.$("a_month");
        sel.innerHTML = d.files.filter((f) => f.name.endsWith(".csv"))
          .map((f) => `<option value="${esc(f.name)}">${esc(f.name.replace(".csv", ""))}</option>`).join("");
        this.loadMonth();
      });
      get("/sd/list.json?dir=backups").then((d) => this.drawBackups(d.files));
      get("/sd/list.json?dir=firmware").then((d) => this.drawFirmware(d.files));
    }).catch(() => {
      this.$("a_status").innerHTML = `<dt>Panel</dt><dd class="bad">${esc(base)} did not answer</dd>`;
    });
  }

  loadMonth() {
    const name = this.$("a_month").value, base = this.panelBase();
    if (!name || !base) { this.set("a_hmsg", "No history on the card yet."); return; }
    const url = base + "/sd/file?path=history/" + encodeURIComponent(name);
    this.$("a_csv").href = url + "&dl=1";
    this.set("a_hmsg", "Loading…");
    fetch(url).then((r) => r.text()).then((text) => {
      const lines = text.trim().split("\n");
      const cols = lines.shift().split(",");
      const rows = lines.map((l) => l.split(","));
      if (!rows.length) { this.set("a_hmsg", "Empty month."); return; }
      const ci = (n) => cols.indexOf(n);
      const t0 = +rows[0][0], t1 = +rows[rows.length - 1][0];
      // Bucket a month of 5-minute rows down to ~1000 points per line.
      const n0 = Math.floor((t1 - t0) / 300) + 1, k = Math.max(1, Math.ceil(n0 / 1000)), n = Math.ceil(n0 / k);
      const series = {};
      for (const key of ["temp", "target", "tds"]) {
        const sum = new Array(n).fill(0), cnt = new Array(n).fill(0), c = ci(key);
        if (c < 0) continue;
        for (const r of rows) {
          const v = parseFloat(r[c]);
          if (isNaN(v)) continue;
          const i = Math.floor((+r[0] - t0) / 300 / k);
          sum[i] += v; cnt[i]++;
        }
        series[key] = sum.map((x, i) => (cnt[i] ? x / cnt[i] : null));
      }
      const d = { slots: n, step: 300 * k, end: t0 + (n - 1) * 300 * k, series };
      this.set("a_hmsg", rows.length + " readings");
      this.chart("ac_temp", d, [{ v: series.target, c: C.muted, w: 1.5, dash: "4 4" }, { v: series.temp, c: "#fff", w: 1.5 }], 1);
      this.chart("ac_tds", d, [{ v: series.tds, c: C.blue, w: 1.5 }], 0);
    }).catch(() => this.set("a_hmsg", "Could not read that month."));
  }

  drawBackups(files) {
    const base = this.panelBase();
    const rows = files.filter((f) => f.name.endsWith(".json")).map((f) => {
      const p = "backups/" + encodeURIComponent(f.name);
      return `<tr><td>${esc(f.name.replace(".json", ""))}</td><td class="v sub">${(f.size / 1024).toFixed(1)} KB</td>
        <td class="v"><a class="btn" style="padding:3px 10px" href="${base}/sd/file?path=${p}&dl=1">Download</a>
        <button class="btn" style="padding:3px 10px" data-restore="${esc(f.name)}">Restore&hellip;</button></td></tr>`;
    }).join("");
    this.$("a_backups").innerHTML = `<tr><th>Night</th><th class="v">Size</th><th></th></tr>`
      + (rows || `<tr><td colspan="3" class="sub">None yet &mdash; the first is made at 03:00, or press Back up now.</td></tr>`);
    this.querySelectorAll("[data-restore]").forEach((b) => { b.onclick = () => this.restore(b.dataset.restore); });
  }

  restore(name) {
    const want = [];
    if (confirm(`Restore SETTINGS from ${name}? (targets, tank details, calibration, CO2 times)`)) want.push("settings=1");
    if (confirm(`Restore the learned HEAT MODEL from ${name}?`)) want.push("model=1");
    if (confirm(`Merge the WATER TESTS from ${name}? Nothing logged since is removed.`)) want.push("tests=1");
    if (!want.length) return;
    fetch(this.panelBase() + "/sd/file?path=backups/" + encodeURIComponent(name)).then((r) => r.text())
      .then((body) => fetch("/restore?" + want.join("&"), { method: "POST", headers: { "Content-Type": "application/json" }, body }))
      .then(async (r) => alert((await r.text()) + (r.ok ? " Settings update over the next few seconds." : "")))
      .catch(() => alert("Could not restore: the panel or the controller did not answer."));
  }

  drawFirmware(files) {
    const base = this.panelBase();
    const bins = files.filter((f) => f.name.endsWith(".bin"));
    const rows = bins.map((f) => {
      const who = f.name.startsWith("panel-") ? "panel" : "controller";
      const p = "firmware/" + encodeURIComponent(f.name);
      const running = this.slots && this.slots.running && f.name.includes(this.slots.running.firmware || "--");
      return `<tr><td>${who}${running ? ' <span class="pill" style="padding:1px 8px">running</span>' : ""}</td>
        <td class="sub" data-side="${esc(f.name)}">${esc(f.name.replace(/^\w+-|\.bin$/g, "").slice(0, 8))}</td>
        <td class="v sub">${(f.size / 1048576).toFixed(2)} MB</td>
        <td class="v"><a class="btn" style="padding:3px 10px" href="${base}/sd/file?path=${p}&dl=1">Download</a>
        ${who === "controller" && !running ? `<button class="btn" style="padding:3px 10px" data-install="${esc(f.name)}">Install</button>` : ""}
        ${running ? "" : `<button class="btn warn" style="padding:3px 10px" data-del="${esc(f.name)}">Delete</button>`}</td></tr>`;
    }).join("");
    this.$("a_fw").innerHTML = `<tr><th>For</th><th>Build</th><th class="v">Size</th><th></th></tr>`
      + (rows || `<tr><td colspan="4" class="sub">None yet &mdash; each build is copied on the first night it runs.</td></tr>`);
    // The build date lives in each .bin's sidecar .json.
    bins.forEach((f) => {
      fetch(base + "/sd/file?path=firmware/" + encodeURIComponent(f.name.replace(/\.bin$/, ".json")))
        .then((r) => r.json()).then((j) => {
          const cell = this.querySelector(`[data-side="${CSS.escape(f.name)}"]`);
          if (cell && j.running) cell.textContent = j.running.built + " · " + String(j.running.firmware).slice(0, 8);
        }).catch(() => {});
    });
    this.querySelectorAll("[data-install]").forEach((b) => { b.onclick = () => this.installFromSd(b.dataset.install); });
    this.querySelectorAll("[data-del]").forEach((b) => {
      b.onclick = () => confirm("Delete " + b.dataset.del + " from the SD card?")
        && fetch(base + "/sd/delete?path=firmware/" + encodeURIComponent(b.dataset.del), { method: "POST" }).then(() => this.loadArchive());
    });
  }

  installFromSd(name) {
    if (!confirm(`Install ${name} on this controller and restart it?`)) return;
    this.set("a_fmsg", "Fetching from the SD card…", "msg");
    fetch(this.panelBase() + "/sd/file?path=firmware/" + encodeURIComponent(name)).then((r) => r.blob()).then((blob) => {
      const fd = new FormData();
      fd.append("update", blob, name);
      const x = new XMLHttpRequest();
      x.upload.onprogress = (e) => { if (e.lengthComputable) this.set("a_fmsg", "Installing " + Math.round(100 * e.loaded / e.total) + "%", "msg"); };
      x.onload = () => this.set("a_fmsg", x.status === 200 ? "Done -- restarting." : "Failed: " + x.responseText, "msg " + (x.status === 200 ? "good" : "bad"));
      x.onerror = () => this.set("a_fmsg", "Install failed.", "msg bad");
      x.open("POST", "/update");
      x.send(fd);
    }).catch(() => this.set("a_fmsg", "Could not read it from the SD card.", "msg bad"));
  }

  // ------------------------------------------------------------- page: diag
  page_diag() {
    return `<div class="grid">
      <div class="card span2"><div class="lbl">Device</div><dl class="kv" id="g_dev"></dl></div>
      <div class="card span2"><div class="lbl">Controller</div><dl class="kv" id="g_ctl"></dl></div>
      <div class="card span4"><div class="lbl">Last crash</div><div class="sub" id="g_crash" style="overflow-wrap:anywhere">--</div>
        <div class="actions"><button class="btn" id="g_clear" disabled>Clear crash report</button></div></div>
      <div class="card span4"><div class="lbl">Update firmware</div>
        <div class="actions"><input type="file" id="u_file" accept=".bin" style="max-width:340px">
          <button class="btn primary" id="u_go" disabled>Upload</button><span class="msg" id="u_msg"></span></div>
        <div class="note">Build this tank's firmware in ESPHome (Install &rarr; Manual download &rarr; the OTA .bin),
          then upload it here. The controller restarts on the new firmware. History, tests and calibration are kept.</div></div>
      <div class="card span4"><div class="lbl">Live log</div><div class="log" id="g_log"></div></div>
      <div class="card span4"><div class="lbl">Every entity</div><div style="overflow:auto"><table id="g_all"></table></div></div>
    </div>`;
  }

  wire_diag() {
    this.$("g_clear").onclick = () => confirm("Clear the stored crash report?") && this.act(E.clearCrash, "press");
    const file = this.$("u_file"), go = this.$("u_go");
    file.onchange = () => { go.disabled = !file.files.length; };
    go.onclick = () => {
      if (!confirm("Upload " + file.files[0].name + " and restart the controller on it?")) return;
      const fd = new FormData();
      fd.append("update", file.files[0]);
      const x = new XMLHttpRequest();
      go.disabled = true;
      x.upload.onprogress = (e) => { if (e.lengthComputable) this.set("u_msg", "Uploading " + Math.round(100 * e.loaded / e.total) + "%", "msg"); };
      x.onload = () => this.set("u_msg", x.status === 200 ? "Done -- restarting. This page reconnects by itself." : "Failed: " + x.responseText, "msg " + (x.status === 200 ? "good" : "bad"));
      x.onerror = () => this.set("u_msg", "Upload failed.", "msg bad");
      x.open("POST", "/update");
      x.send(fd);
    };
    this.drawLog();
  }

  drawLog() {
    const el = this.$("g_log");
    if (!el) return;
    const atEnd = el.scrollTop + el.clientHeight >= el.scrollHeight - 20;
    el.innerHTML = this.logLines.map((l) => {
      const cls = /\[[EW]\]/.test(l) ? (/\[E\]/.test(l) ? "e" : "w") : "";
      return `<div class="${cls}">${esc(l.replace(/\x1b\[[0-9;]*m/g, ""))}</div>`;
    }).join("");
    if (atEnd) el.scrollTop = el.scrollHeight;
  }

  draw_diag() {
    const kv = (rows) => rows.map(([l, v]) => `<dt>${l}</dt><dd>${esc(v === "" || v === undefined ? "--" : v)}</dd>`).join("");
    const sv = (k) => { const v = this.s[k]; return v ? (v.state !== undefined ? v.state : v.value) : ""; };
    this.$("g_dev").innerHTML = kv([
      ["IP address", sv("text_sensor-ip_address")], ["Wi-Fi signal", sv(E.wifi)], ["Uptime", sv(E.uptime)],
      ["Firmware", sv("text_sensor-firmware_build")], ["Reset reason", sv("text_sensor-reset_reason")],
      ["Heap free", sv("sensor-heap_free")], ["Loop time", sv("sensor-loop_time")],
      ["BLE MAC (for the panel)", sv("text_sensor-controller_ble_mac")], ["BLE links", sv(E.bleLinks)],
      ["BLE advertising restarts", sv("sensor-ble_advertising_restarts")]]);
    this.$("g_ctl").innerHTML = kv([
      ["State", sv(E.state)], ["Model health", sv(E.health)], ["Confidence", sv(E.conf)],
      ["Predicted in 15 min", sv(E.predicted)], ["Swing (1 h)", sv(E.swing)], ["Drift", sv(E.drift)],
      ["Time constant", sv("sensor-tank_time_constant")], ["Expected", sv("sensor-expected_time_constant")],
      ["Learned heater power", sv("sensor-learned_heater_power")], ["Seed", sv("text_sensor-seed_status")],
      ["TDS probe voltage", sv(E.tdsV)], ["Panel payload", sv("text_sensor-link_payload")]]);
    const crash = this.str(E.crash), bt = this.str("text_sensor-last_crash_backtrace");
    this.$("g_crash").textContent = (crash || "--") + (bt && bt !== "none recorded" ? "\n" + bt : "");
    this.$("g_clear").disabled = !this.ids[E.clearCrash];
    const rows = this.order.slice().sort().map((k) => {
      const d = this.s[k], dom = k.split("-")[0];
      return `<tr><td class="sub">${esc(dom)}</td><td>${esc(String(d.id).split("/").pop())}</td><td class="v">${esc(sv(k))}</td></tr>`;
    }).join("");
    this.$("g_all").innerHTML = `<tr><th>Type</th><th>Name</th><th class="v">State</th></tr>` + rows;
  }
}
customElements.define("esp-app", TankSite);
