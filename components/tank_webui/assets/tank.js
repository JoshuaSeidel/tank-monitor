// Tank Monitor web UI.
//
// ESPHome's page is literally `<esp-app></esp-app>` plus one script tag.
// Setting web_server's js_url to "" suppresses its CDN bundle, so whatever
// defines `esp-app` here IS the interface. Everything is served from the
// device's own flash: no internet, no Home Assistant, no CDN.
//
// State arrives on /events (server-sent events); control goes back over
// the REST endpoints web_server already exposes.

// web_server reports an entity as "<domain>/[<device>/]<Display Name>" --
// a slash, and the display name, not the object id the REST routes use.
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
  calV7: "sensor-cal_ph_7_voltage",
  calV4: "sensor-cal_ph_4_voltage",
  calSlope: "sensor-cal_ph_slope",
  heatRelay: "binary_sensor-heater",
  fanRelay: "binary_sensor-fan",
  fault: "binary_sensor-temperature_fault",
  learn: "switch-adaptive_learning",
  light: "light-display_backlight",
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
              <button id="dn">&minus;</button>
              <div class="n" id="target">--.-</div>
              <button id="up">+</button>
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
                <input type="number" id="std" min="1" max="2000" step="1"></div>
              <div class="fld"><span class="sub">Reading now</span>
                <div class="val" id="cal_now">--</div></div>
              <div class="fld"><span class="sub">K factor</span>
                <div class="val" id="cal_k">--</div></div>
              <div class="fld"><button class="btn" id="b_cal_tds">Calibrate</button></div>
            </div>
            <div class="note">Stand the probe in the standard, wait for the reading
              to settle, then press. <b>Bring the standard to tank temperature first</b>
              &mdash; conductivity moves about 2%/&deg;C, so a cold bottle bakes several
              percent of error into K permanently.</div>
          </div>

          <div class="calsec" id="calph" style="display:none">
            <span class="lbl">pH &mdash; two point</span>
            <div class="cal">
              <div class="fld"><span class="sub">Probe now</span>
                <div class="val" id="cal_phv">--</div></div>
              <div class="fld"><span class="sub">Slope</span>
                <div class="val" id="cal_slope">--</div></div>
              <div class="fld"><button class="btn" id="b_ph7">Capture 7.00</button></div>
              <div class="fld"><button class="btn" id="b_ph4">Capture 4.00</button></div>
            </div>
            <div class="note">Rinse in distilled water and <b>blot</b> dry &mdash; never
              wipe the glass bulb, it holds a static charge and the reading wanders for
              minutes. Two minutes in each buffer before capturing. A healthy electrode
              sits near <b>0.177 V/pH</b>; much less and it is tired.</div>
          </div>

          <div class="calsec">
            <span class="lbl">Temperature</span>
            <div class="cal">
              <div class="fld"><span class="sub">Offset (&deg;F)</span>
                <input type="number" id="off" min="-5" max="5" step="0.1"></div>
              <div class="fld"><span class="sub">Reads now</span>
                <div class="val" id="cal_temp">--</div></div>
            </div>
            <div class="note">Against a reference thermometer. This probe is the only
              one the control loop has &mdash; if it reads low the heater will cook the
              tank while reporting the target, and nothing will notice.</div>
          </div>
        </div>

        <div class="card span">
          <div class="tog"><span>Adaptive learning</span><button class="sw" id="sw_learn"></button></div>
          <div class="tog"><span>Display backlight</span><button class="sw" id="sw_light"></button></div>
          <div class="tog"><span>Device</span><span>
            <button class="btn" id="b_restart">Restart</button>
            <button class="btn warn" id="b_reset">Reset learning</button>
          </span></div>
        </div>
      </div>
    </div>`;
  }

  post(path) { fetch(path, { method: "POST" }); }

  // Domains disagree about how they report a boolean: binary_sensor and
  // switch send true/false, but light sends the string "ON"/"OFF" -- and
  // "OFF" is truthy, so a plain !! left the backlight toggle stuck on.
  static on(v) { return v === true || v === 1 || v === "ON" || v === "on"; }

  wire() {
    const nudge = (d) => {
      const v = parseFloat(this.$("target").textContent);
      if (!isNaN(v)) this.post(`/number/target_temperature/set?value=${(v + d).toFixed(1)}`);
    };
    this.$("up").onclick = () => nudge(0.5);
    this.$("dn").onclick = () => nudge(-0.5);
    this.$("sw_learn").onclick = () => this.post("/switch/adaptive_learning/toggle");
    this.$("sw_light").onclick = () => this.post("/light/display_backlight/toggle");
    this.$("b_restart").onclick = () => confirm("Restart the controller?") && this.post("/button/restart/press");
    this.$("b_reset").onclick = () =>
      confirm("Discard everything the model has learned about this tank?") &&
      this.post("/button/reset_learning/press");

    // Calibration. Every one of these overwrites a stored calibration, and
    // a mis-press with the probe in tank water instead of buffer silently
    // corrupts every future reading -- so all three confirm, same as the
    // learning reset does.
    const setNum = (el, entity) => {
      this.$(el).onchange = (e) => {
        const v = parseFloat(e.target.value);
        if (!isNaN(v)) this.post(`/number/${entity}/set?value=${v}`);
      };
    };
    setNum("std", "cal_tds_standard");
    setNum("off", "cal_temperature_offset");

    this.$("b_cal_tds").onclick = () => {
      const std = this.$("std").value;
      confirm(`Set the TDS calibration so the probe reads ${std} ppm right now?`) &&
        this.post("/button/calibrate_tds/press");
    };
    this.$("b_ph7").onclick = () =>
      confirm("Store the current probe voltage as pH 7.00?") &&
      this.post("/button/capture_ph_7_00/press");
    this.$("b_ph4").onclick = () =>
      confirm("Store the current probe voltage as pH 4.00?") &&
      this.post("/button/capture_ph_4_00/press");
  }

  listen() {
    const es = new EventSource("/events");
    es.addEventListener("state", (e) => {
      const d = JSON.parse(e.data);
      this.s[key(d.id)] = d;
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
    if (!isNaN(tds)) q("cal_now").textContent = tds.toFixed(0) + " ppm";
    if (!isNaN(t)) q("cal_temp").textContent = t.toFixed(2) + " °F";

    const slope = this.num(E.calSlope);
    q("calph").style.display = isNaN(slope) ? "none" : "";
    if (!isNaN(slope)) {
      q("cal_slope").textContent = Math.abs(slope).toFixed(3) + " V/pH";
      // Nernst is 0.1773 V/pH at 25 °C. Below ~85% of ideal the electrode is
      // worn out and no amount of recalibrating will make it linear again.
      q("cal_slope").style.color = Math.abs(slope) < 0.150 ? "var(--amber)" : "";
    }
    if (!isNaN(phv)) q("cal_phv").textContent = phv.toFixed(4) + " V";

    // Never clobber a field mid-type: these are inputs, not readouts.
    const fill = (el, k2, dp) => {
      const node = q(el), v = this.num(k2);
      if (!isNaN(v) && document.activeElement !== node) node.value = v.toFixed(dp);
    };
    fill("std", E.calStd, 0);
    fill("off", E.calOff, 1);

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
  }
}
customElements.define("esp-app", TankApp);
