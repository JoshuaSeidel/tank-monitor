// Tank Monitor web UI.
//
// ESPHome's page is literally `<esp-app></esp-app>` plus one script tag.
// Pointing web_server's js_url at the device's own /tank.js replaces its
// CDN bundle, so whatever defines `esp-app` here IS the interface. Everything is served from the
// device's own flash: no internet, no Home Assistant, no CDN.
//
// State arrives on /events (server-sent events); control goes back over
// the REST endpoints web_server already exposes, addressed by the id each
// entity arrived with (see act).

// web_server reports an entity as "<domain>/[<device>/]<Display Name>" --
// a slash, and the display name, not the object id. The page's own key is
// a slug of that, so E below reads like the entity and not like a URL.
// Deriving the key from the id itself rather than hard-coding the string
// survives both the optional device segment and any renaming of the
// separator, and needs nothing from the verbose first payload.
const key = (id) => {
  const parts = String(id).split("/");
  const slug = parts[parts.length - 1]
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
  return parts[0] + "-" + slug;
};

// Everything the device publishes is already Fahrenheit -- the one
// Celsius sensor is internal and never reaches the web server.
const E = {
  temp: "sensor-water_temperature",
  target: "number-target_temperature",
  state: "text_sensor-controller_state",
  heat: "sensor-heater_output",
  fan: "sensor-fan_output",
  swing: "sensor-temperature_swing_1h",
  drift: "sensor-temperature_drift_rate",
  conf: "sensor-model_confidence",
  tds: "sensor-tds_1h_mean",
  tdsRaw: "sensor-tds",
  lux: "sensor-tank_light_level",
  ph: "sensor-water_ph",
  phv: "sensor-ph_probe_voltage",
  // Calibration state. These live on the device, in flash, and are applied
  // inside the sensor lambdas -- so every consumer (this page, MQTT, the
  // ESP-NOW panel) gets the corrected value from one place.
  calK: "number-cal_tds_k_factor",
  calStd: "number-cal_tds_standard",
  calOff: "number-cal_temperature_offset",
  // What the two pH buffers actually say -- the pH each capture is stored
  // AS, never an assumed 7.00/4.00.
  calHi: "number-cal_ph_high_value",
  calLo: "number-cal_ph_low_value",
  calSlope: "sensor-cal_ph_slope",
  calTds: "button-calibrate_tds",
  capHi: "button-capture_high_point",
  capLo: "button-capture_low_point",
  heatRelay: "binary_sensor-heater",
  fanRelay: "binary_sensor-fan",
  fault: "binary_sensor-probe_not_responding",
  learn: "switch-adaptive_learning",
  light: "light-display_backlight",
  restart: "button-restart",
  reset: "button-reset_learning",
};

// Same ladder as both panels, offsets from setpoint in °F.
const BANDS = [
  [-1.95, "#2F80FF", "TOO COLD"],
  [-1.25, "#7FC4FF", "COLD"],
  [-0.25, "#3ECFB0", "COOL"],
  [0.55, "#3ECF6E", "STEADY"],
  [1.45, "#FFB020", "WARM"],
  [Infinity, "#FF4438", "TOO WARM"],
];

class TankApp extends HTMLElement {
  connectedCallback() {
    this.s = {};
    this.ids = {};
    this.pending = {};
    this.innerHTML = this.template();
    this.$ = (id) => this.querySelector("#" + id);
    this.wire();
    this.listen();
  }

  template() {
    return `<div class="wrap">
      <header><span class="dot" id="dot"></span><h1>Tank Monitor</h1></header>
      <div class="grid">
        <div class="card span hero">
          <div class="gauge">
            <svg width="150" height="150" viewBox="0 0 150 150">
              <circle class="track" cx="75" cy="75" r="63" stroke-dasharray="297 396"></circle>
              <circle class="ind" id="arc" cx="75" cy="75" r="63"
                      stroke-dasharray="297 396" stroke-dashoffset="297"></circle>
            </svg>
            <div class="mid"><div class="t" id="temp">--.-</div><div class="u">&deg;F</div></div>
          </div>
          <div>
            <span class="pill" id="pill">STARTING</span>
            <div class="lbl" style="margin-top:14px">Target</div>
            <div class="step">
              <button id="dn" disabled>&minus;</button>
              <div class="n" id="target">--.-</div>
              <button id="up" disabled>+</button>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="row"><span class="lbl">Heater</span><span class="sub" id="heatv">0%</span></div>
          <div class="bar heat"><i id="heatb"></i></div>
          <div class="sub" id="heatr">relay off</div>
        </div>
        <div class="card">
          <div class="row"><span class="lbl">Fan</span><span class="sub" id="fanv">0%</span></div>
          <div class="bar fan"><i id="fanb"></i></div>
          <div class="sub" id="fanr">relay off</div>
        </div>

        <div class="card"><div class="lbl">Swing 1h</div><div class="val" id="swing">--</div>
          <div class="sub">peak-to-peak</div></div>
        <div class="card"><div class="lbl">TDS</div><div class="val" id="tds">--</div>
          <div class="sub" id="ec">-- &micro;S/cm</div></div>
        <div class="card" id="phcard" style="display:none"><div class="lbl">pH</div>
          <div class="val" id="ph">--</div><div class="sub" id="phv">-- V</div></div>
        <div class="card"><div class="lbl">Light</div><div class="val" id="lux">--</div>
          <div class="sub">lux</div></div>
        <div class="card"><div class="lbl">Learned</div><div class="val" id="conf">--</div>
          <div class="sub" id="drift">-- &deg;F/h</div></div>

        <div class="card span" id="chemcard" style="display:none">
          <div class="lbl" style="margin-bottom:10px">Water chemistry</div>
          <div class="chem">
            <div><span class="lbl">pH</span><span class="val" id="c_ph">--</span></div>
            <div><span class="lbl">Free NH3</span><span class="val" id="c_nh3">--</span></div>
            <div><span class="lbl">GH</span><span class="val" id="c_gh">--</span></div>
            <div><span class="lbl">KH</span><span class="val" id="c_kh">--</span></div>
            <div><span class="lbl">NO2</span><span class="val" id="c_no2">--</span></div>
            <div><span class="lbl">NO3</span><span class="val" id="c_no3">--</span></div>
          </div>
          <div class="age" id="c_age">from Home Assistant</div>
        </div>

        <div class="card span" id="calcard" style="display:none">
          <div class="lbl" style="margin-bottom:4px">Calibration</div>
          <div class="note" style="margin-bottom:14px">Stored on this device, in flash.
            Applied before anything is published, so Home Assistant and the panel
            get the corrected value too. Survives reboots and OTA updates.</div>

          <div class="calsec">
            <span class="lbl">TDS &mdash; single point</span>
            <div class="cal">
              <div class="fld"><span class="sub">Standard (ppm on the bottle)</span>
                <input type="number" id="std" min="1" max="2000" step="1" disabled></div>
              <div class="fld"><span class="sub">Reading now</span>
                <div class="val" id="cal_now">--</div></div>
              <div class="fld"><span class="sub">K factor</span>
                <div class="val" id="cal_k">--</div></div>
              <div class="fld"><button class="btn" id="b_cal_tds" disabled>Calibrate</button></div>
            </div>
            <div class="note">Stand the probe in the standard, wait for the reading
              to settle, then press. <b>Bring the standard to tank temperature first</b>
              &mdash; conductivity moves about 2%/&deg;C, so a cold bottle bakes several
              percent of error into K permanently.</div>
          </div>

          <div class="calsec" id="calph" style="display:none">
            <span class="lbl">pH &mdash; two point</span>
            <div class="cal">
              <div class="fld"><span class="sub">High value (pH on the bottle)</span>
                <input type="number" id="ph_hi" min="6" max="11" step="0.01" disabled></div>
              <div class="fld"><span class="sub">Low value (pH on the bottle)</span>
                <input type="number" id="ph_lo" min="3" max="8" step="0.01" disabled></div>
              <div class="fld"><span class="sub">Probe now</span>
                <div class="val" id="cal_phv">--</div></div>
              <div class="fld"><span class="sub">Slope</span>
                <div class="val" id="cal_slope">--</div></div>
            </div>
            <div class="cal" style="margin-top:12px">
              <div class="fld"><button class="btn" id="b_ph_hi" disabled>Capture high</button></div>
              <div class="fld"><button class="btn" id="b_ph_lo" disabled>Capture low</button></div>
            </div>
            <div class="note">Set both values to what the bottles say, and pick a high and
              a low that <b>bracket the tank</b> &mdash; 9.18 and 6.86 for a tank at 7.x,
              not 6.86 and 4.00, or every reading is extrapolated past the top point.
              Rinse in distilled water and <b>blot</b> dry &mdash; never wipe the glass
              bulb, it holds a static charge and the reading wanders for minutes. Two
              minutes in each buffer before capturing, then <b>check in a third</b> (e.g.
              4.00): within ~0.1 means the electrode is linear. Never calibrate on the
              check buffer. A healthy electrode sits near <b>0.177 V/pH</b> (Home Assistant
              shows it negative: more volts, lower pH); much less and it is tired.</div>
          </div>

          <div class="calsec">
            <span class="lbl">Temperature</span>
            <div class="cal">
              <div class="fld"><span class="sub">Offset (&deg;F)</span>
                <input type="number" id="off" min="-5" max="5" step="0.1" disabled></div>
              <div class="fld"><span class="sub">Reads now</span>
                <div class="val" id="cal_temp">--</div></div>
            </div>
            <div class="note">Against a reference thermometer. This probe is the only
              one the control loop has &mdash; if it reads low the heater will cook the
              tank while reporting the target, and nothing will notice.</div>
          </div>
        </div>

        <div class="card span">
          <div class="tog"><span>Adaptive learning</span><button class="sw" id="sw_learn" disabled></button></div>
          <div class="tog" id="row_light"><span>Display backlight</span><button class="sw" id="sw_light" disabled></button></div>
          <div class="tog"><span>Device</span><span>
            <button class="btn" id="b_restart" disabled>Restart</button>
            <button class="btn warn" id="b_reset" disabled>Reset learning</button>
          </span></div>
        </div>
      </div>
    </div>`;
  }

  // Every control goes through here, addressed by the id its entity
  // arrived with on /events -- never a URL spelled out in this file. Since
  // ESPHome 2026.7 web_server matches a POST by display name (plus the
  // device segment, when there is one) and answers the old object-id form
  // with a 404, which is how every control on this page went dead without
  // a single visible error. Each segment is escaped on its own: the
  // slashes are structure, the spaces in "Cal pH High Value" are not. An
  // entity that has not reported has no address, so nothing is sent --
  // render() keeps its control disabled until it does. A set stays
  // pending until the entity reports back (the device republishes at once),
  // which is what lets the calibrations refuse to run on an unstored value.
  act(k, action, value) {
    const id = this.ids[k];
    if (!id) return;
    if (action === "set") this.pending[k] = true;
    const q = value === undefined ? "" : "?value=" + encodeURIComponent(value);
    fetch("/" + id.split("/").map(encodeURIComponent).join("/") + "/" + action + q, { method: "POST" });
  }

  // Domains disagree about how they report a boolean: binary_sensor and
  // switch send true/false, but light sends the string "ON"/"OFF" -- and
  // "OFF" is truthy, so a plain !! left the backlight toggle stuck on.
  static on(v) { return v === true || v === 1 || v === "ON" || v === "on"; }

  wire() {
    const nudge = (d) => {
      const v = parseFloat(this.$("target").textContent);
      if (!isNaN(v)) this.act(E.target, "set", (v + d).toFixed(1));
    };
    this.$("up").onclick = () => nudge(0.5);
    this.$("dn").onclick = () => nudge(-0.5);
    this.$("sw_learn").onclick = () => this.act(E.learn, "toggle");
    this.$("sw_light").onclick = () => this.act(E.light, "toggle");
    this.$("b_restart").onclick = () => confirm("Restart the controller?") && this.act(E.restart, "press");
    this.$("b_reset").onclick = () =>
      confirm("Discard everything the model has learned about this tank?") &&
      this.act(E.reset, "press");

    // Calibration. Every one of these overwrites a stored calibration, and
    // a mis-press with the probe in tank water instead of buffer silently
    // corrupts every future reading -- so all three confirm, same as the
    // learning reset does.
    const setNum = (el, k) => {
      this.$(el).onchange = (e) => {
        const v = parseFloat(e.target.value);
        if (!isNaN(v)) this.act(k, "set", v);
      };
    };
    setNum("std", E.calStd);
    setNum("off", E.calOff);
    setNum("ph_hi", E.calHi);
    setNum("ph_lo", E.calLo);

    // Each of these solves against whatever the DEVICE holds -- the TDS
    // standard, or that point's pH -- so the question names the device's
    // value, not the field's: a bottle that disagrees with the prompt is the
    // mistake caught before it is stored. render() keeps them disabled until
    // that value has arrived, so the prompt never asks about NaN.
    //
    // Clicking the button blurs the field first, and the blur sends the
    // field's new value before this handler runs -- so a value typed and
    // clicked in one motion is already on its way while the device still
    // reports the old one. Asking then would name the old value and store
    // against the new, hiding exactly the typo the question exists to catch.
    // Refuse until the device has reported the new value back.
    const stored = (k, what) => {
      if (!this.pending[k]) return true;
      alert(`The new ${what} has not come back from the device yet. Press again in a moment.`);
      return false;
    };
    this.$("b_cal_tds").onclick = () =>
      stored(E.calStd, "standard") &&
      confirm(`Set the TDS calibration so the probe reads ${this.num(E.calStd).toFixed(0)} ppm right now?`) &&
      this.act(E.calTds, "press");
    this.$("b_ph_hi").onclick = () =>
      stored(E.calHi, "high value") &&
      confirm(`Store the current probe voltage as the high point, pH ${this.num(E.calHi).toFixed(2)}?`) &&
      this.act(E.capHi, "press");
    this.$("b_ph_lo").onclick = () =>
      stored(E.calLo, "low value") &&
      confirm(`Store the current probe voltage as the low point, pH ${this.num(E.calLo).toFixed(2)}?`) &&
      this.act(E.capLo, "press");
  }

  listen() {
    const es = new EventSource("/events");
    es.addEventListener("state", (e) => {
      const d = JSON.parse(e.data);
      const k = key(d.id);
      this.s[k] = d;
      // Kept verbatim: it is the entity's REST address (see act).
      this.ids[k] = d.id;
      delete this.pending[k];
      this.$("dot").classList.add("on");
      this.render();
    });
    es.onerror = () => this.$("dot").classList.remove("on");
  }

  num(id) { const v = this.s[id]; return v && v.value !== undefined ? parseFloat(v.value) : NaN; }

  render() {
    const q = (id) => this.$(id);
    const t = this.num(E.temp);
    const sp = this.num(E.target);
    const fault = this.s[E.fault] ? this.s[E.fault].value : false;

    if (!isNaN(t)) q("temp").textContent = t.toFixed(1);
    if (!isNaN(sp)) q("target").textContent = sp.toFixed(1);

    let colour = "#3ECF6E", label = "STEADY";
    if (TankApp.on(fault) || isNaN(t)) { colour = "#FF4438"; label = "NO PROBE"; }
    else if (!isNaN(sp)) {
      for (const [off, c, l] of BANDS) { colour = c; label = l; if (t < sp + off) break; }
    }
    const pill = q("pill");
    pill.textContent = label;
    pill.style.background = colour + "22";
    pill.style.color = colour;

    // Arc spans the whole band, same as the panel: nothing wasted at the ends.
    if (!isNaN(t) && !isNaN(sp)) {
      const lo = sp - 1.95, hi = sp + 1.45;
      const pct = Math.max(0, Math.min(1, (t - lo) / (hi - lo)));
      const arc = q("arc");
      arc.style.stroke = colour;
      arc.setAttribute("stroke-dashoffset", (297 * (1 - pct)).toFixed(1));
    }

    const h = this.num(E.heat), f = this.num(E.fan);
    if (!isNaN(h)) { q("heatv").textContent = h.toFixed(0) + "%"; q("heatb").style.width = h + "%"; }
    if (!isNaN(f)) { q("fanv").textContent = f.toFixed(0) + "%"; q("fanb").style.width = f + "%"; }
    const relay = (k, el) => {
      const v = this.s[k];
      if (v) q(el).textContent = "relay " + (TankApp.on(v.value) ? "on" : "off");
    };
    relay(E.heatRelay, "heatr"); relay(E.fanRelay, "fanr");

    const sw = this.num(E.swing);
    if (!isNaN(sw)) q("swing").textContent = sw.toFixed(2) + " °F";
    // The hour mean. Raw only until the first mean lands after a boot --
    // see packages/sensors.yaml for why a single sample is not a reading.
    let tds = this.num(E.tds);
    if (isNaN(tds)) tds = this.num(E.tdsRaw);
    if (!isNaN(tds)) { q("tds").textContent = tds.toFixed(0); q("ec").textContent = (tds * 2).toFixed(0) + " µS/cm"; }
    const lux = this.num(E.lux);
    if (!isNaN(lux)) q("lux").textContent = lux.toFixed(0);
    const cf = this.num(E.conf);
    if (!isNaN(cf)) q("conf").textContent = cf.toFixed(0) + "%";
    const dr = this.num(E.drift);
    if (!isNaN(dr)) q("drift").textContent = (dr >= 0 ? "+" : "") + dr.toFixed(2) + " °F/h";

    // pH exists only on a board that includes packages/ph.yaml.
    const ph = this.num(E.ph), phv = this.num(E.phv);
    q("phcard").style.display = isNaN(ph) ? "none" : "";
    if (!isNaN(ph)) q("ph").textContent = ph.toFixed(2);
    if (!isNaN(phv)) q("phv").textContent = phv.toFixed(3) + " V";

    // --- calibration ---
    const k = this.num(E.calK);
    q("calcard").style.display = isNaN(k) ? "none" : "";
    if (!isNaN(k)) q("cal_k").textContent = k.toFixed(2) + "x";
    // The single sample, not the hour mean: it is what Calibrate TDS solves
    // against, and a mean still full of tank water would take an hour to
    // settle on the standard the probe is standing in.
    const tdsNow = this.num(E.tdsRaw);
    if (!isNaN(tdsNow)) q("cal_now").textContent = tdsNow.toFixed(0) + " ppm";
    if (!isNaN(t)) q("cal_temp").textContent = t.toFixed(2) + " °F";

    // Shown whenever the board has pH, not whenever the calibration is
    // valid: High == Low (half-way through changing buffer pairs) makes the
    // slope NaN, and hiding the section then would hide the very controls
    // that fix it. An invalid slope reads as an amber dash instead.
    const slope = this.num(E.calSlope);
    q("calph").style.display = this.ids[E.calHi] ? "" : "none";
    if (!isNaN(slope)) {
      q("cal_slope").textContent = Math.abs(slope).toFixed(3) + " V/pH";
      // Nernst is 0.1773 V/pH at 25 °C. Below ~85% of ideal the electrode is
      // worn out and no amount of recalibrating will make it linear again.
      q("cal_slope").style.color = Math.abs(slope) < 0.150 ? "var(--amber)" : "";
    } else if (this.s[E.calSlope]) {
      q("cal_slope").textContent = "--";
      q("cal_slope").style.color = "var(--amber)";
    }
    if (!isNaN(phv)) q("cal_phv").textContent = phv.toFixed(4) + " V";
    const phHi = this.num(E.calHi), phLo = this.num(E.calLo);
    if (!isNaN(phHi)) q("b_ph_hi").textContent = "Capture high " + phHi.toFixed(2);
    if (!isNaN(phLo)) q("b_ph_lo").textContent = "Capture low " + phLo.toFixed(2);

    // Never clobber a field mid-type: these are inputs, not readouts.
    const fill = (el, k2, dp) => {
      const node = q(el), v = this.num(k2);
      if (!isNaN(v) && document.activeElement !== node) node.value = v.toFixed(dp);
    };
    fill("std", E.calStd, 0);
    fill("off", E.calOff, 1);
    fill("ph_hi", E.calHi, 2);
    fill("ph_lo", E.calLo, 2);

    const set = (el, k, dp) => {
      const v = this.num(k);
      if (!isNaN(v)) q(el).textContent = v.toFixed(dp);
    };
    set("c_ph", "sensor-chem_ph", 2); set("c_nh3", "sensor-chem_nh3", 3);
    set("c_gh", "sensor-chem_gh", 0); set("c_kh", "sensor-chem_kh", 0);
    set("c_no2", "sensor-chem_no2", 1); set("c_no3", "sensor-chem_no3", 0);

    // Chemistry is mirrored from Home Assistant and only exists on boards
    // that include packages/chemistry.yaml. Hide the card entirely rather
    // than show six dashes on a device that never receives it.
    const anyChem = ["ph", "nh3", "gh", "kh", "no2", "no3"]
      .some((k) => !isNaN(this.num("sensor-chem_" + k)));
    q("chemcard").style.display = anyChem ? "" : "none";
    const age = this.s["text_sensor-chem_age"];
    if (age && age.value) {
      q("c_age").textContent = "from Home Assistant \u00b7 " + age.value;
      q("c_age").classList.toggle("stale", /[hd] ago|never/.test(age.value));
    }

    const on = (k, el) => {
      const v = this.s[k];
      if (v) q(el).classList.toggle("on", TankApp.on(v.value));
    };
    on(E.learn, "sw_learn"); on(E.light, "sw_light");
    // Only the panels have a backlight; a permanently grey toggle on every
    // controller reads as broken, so the row waits for the entity like the
    // pH and chemistry cards do.
    q("row_light").style.display = this.ids[E.light] ? "" : "none";

    // A control is live once its entity has reported, because that report
    // is its address (see act). The three calibrations also wait for the
    // value their confirm names. A board without the entity -- no backlight,
    // no pH -- leaves the control disabled rather than posting into a 404.
    const live = (el, k, ready = true) => { q(el).disabled = !(this.ids[k] && ready); };
    live("up", E.target); live("dn", E.target);
    live("sw_learn", E.learn); live("sw_light", E.light);
    live("b_restart", E.restart); live("b_reset", E.reset);
    live("std", E.calStd); live("off", E.calOff);
    live("ph_hi", E.calHi); live("ph_lo", E.calLo);
    live("b_cal_tds", E.calTds, !isNaN(this.num(E.calStd)));
    // A capture with no probe reading is skipped on the device with only a
    // log line, so do not offer one.
    live("b_ph_hi", E.capHi, !isNaN(phHi) && !isNaN(phv));
    live("b_ph_lo", E.capLo, !isNaN(phLo) && !isNaN(phv));
  }
}
customElements.define("esp-app", TankApp);
