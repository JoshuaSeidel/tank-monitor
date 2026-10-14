#!/usr/bin/env python3
"""Offline check of components/tank_controller's thermal model and control law.

Mirrors TankController::update() / learn_() / rebase_() / project_bounds_()
statement for statement, in float32 (numpy) like the ESP32, and drives them
with a simulated tank:

  * first-order plant  dT/dt = kh*H - kf*F - (T - T_room)/tau + kl*L
  * heater and fan through 900 s slow_pwm windows, as on the boards
  * two DS18B20s (control + cross-check) with offsets, noise and 0.0625 degC
    quantisation
  * room: the 75's office as its Zigbee sensor saw it (2026-10-13/14):
    75.0 degF at 15:10 falling to 71.8 by 21:00, 71.4-72.1 overnight,
    71.4 -> 73.8 between 06:00 and 09:00, 73.2-73.8 midday -- plus a +3 degF
    step on day 10 (the heating season)
  * optional room sensor input modelled on that Zigbee sensor: 0.2 degC
    steps, report-on-change only (worst case: no presence-driven
    republishes), 3 h validity
  * lights 09:00-16:00

Both firmwares are modelled: OLD = bbf4b6f (fixed 24.0 degC reference, plain
clamp, no process noise, fixed health deadband) and NEW = the current
component. Run it after any change to the model's constants or equations:

    python3 tools/thermal_model_sim.py            # full table, ~1-2 min
    python3 tools/thermal_model_sim.py --quick    # 10 day runs

Needs numpy. Nothing here is imported by the firmware.
"""
import argparse
import math
import random

import numpy as np

f32 = np.float32
N = 5

# --- constants shared by both firmwares (tank_controller.cpp) -------------
LEARN_WINDOW_MS = 300000
LAMBDA_OLD = f32(0.9995)
INFO_MIN = f32(5e-5)
P_REINFLATE = f32(1.02)
BIAS_EMA_W = f32(0.2)
STALE_EMA_W = f32(0.02)
STALE_SCALE = f32(0.050)
INTEGRAL_AUTHORITY = f32(0.5)
GUARD_DEADBAND = f32(0.1 * 5 / 9)
THETA_MIN = [f32(v) for v in (0.002, -0.300, -0.200, 0.000, -0.150)]
THETA_MAX = [f32(v) for v in (0.300, -0.002, -0.001, 0.050, 0.150)]
THETA_PRIOR = [f32(v) for v in (0.030, -0.020, -0.015, 0.003, -0.030)]

# --- OLD (bbf4b6f) ---------------------------------------------------------
OLD_TEMP_REF = f32(24.0)
OLD_P_PRIOR = [f32(v) for v in (1e-3, 1e-3, 1e-4, 1e-5, 1e-5)]
OLD_STALE_DEADBAND = f32(0.0125)

# --- NEW -------------------------------------------------------------------
C_TRACK_STEPS = f32(24.0)
Q_C = f32(1.0) / (C_TRACK_STEPS * (C_TRACK_STEPS - f32(1.0)))
Q_KA_SETPOINT = f32(1e-7)
Q_KA_AMBIENT = f32(1e-6)
P_KA_AMBIENT = f32(1e-2)
NEW_P_PRIOR = [f32(1e-3), f32(1e-3), f32(1e-4), f32(1e-5), f32(1.0) / (C_TRACK_STEPS - f32(1.0))]
AMBIENT_SETTLE_MS = 600000
AMBIENT_FILTER_MIN = f32(20.0)
AMBIENT_MIN_F, AMBIENT_MAX_F = 40.0, 100.0
SUBMERGED_BAND = f32(0.2 * 5 / 9)
SUBMERGED_MS = 3 * 3600 * 1000
PAIR_RATE_TOL = f32(0.125)
HEALTH_Z = f32(4.0)
QUANT_RATE_SIGMA = f32(0.0625) / f32(2.449490) / f32(5.0)
QUANT_RATE_SIGMA_PAIR = QUANT_RATE_SIGMA / f32(1.414214)
STALE_DEADBAND_MAX = f32(0.0125)
REF_SETPOINT, REF_AMBIENT = 0, 1

F = lambda c: float(c) * 9 / 5 + 32
C = lambda f: (f - 32) * 5 / 9
CMIN_TO_FH = 108.0


def clampf(v, lo, hi):
    if math.isnan(v):
        return lo
    return lo if v < lo else (hi if v > hi else v)


class Controller:
    """TankController, either firmware. Temperatures degC, rates degC/min."""

    def __init__(self, new, setpoint_f, max_tau, fan_available=True, cross=True, ambient=False, ambient_timeout_min=180,
                 full_scale_lux=3000.0, response_time=20.0, fan_deadband_f=0.25, disagree_band_f=8.0):
        self.new = new
        self.ka_min = f32(1.0 / max_tau)
        self.p_prior = NEW_P_PRIOR if new else OLD_P_PRIOR
        self.fan_available = fan_available
        self.has_cross = cross
        self.has_ambient = ambient
        self.full_scale_lux = f32(full_scale_lux)
        self.rt = f32(response_time)
        self.fan_db = f32(fan_deadband_f * 5 / 9)
        self.disagree_band = f32(disagree_band_f * 5 / 9)
        self.setpoint = f32(C(setpoint_f))
        self.load_prior()
        self.bias = f32(0); self.stale = f32(0)
        self.resid_var = QUANT_RATE_SIGMA * QUANT_RATE_SIGMA
        self.integral = f32(0); self.heater = f32(0); self.fan = f32(0)
        self.predicted = float('nan')
        self.light_slot = [f32(0)] * 96; self.light_w = [f32(0)] * 96; self.last_slot = -1
        self.anchor_t = float('nan'); self.anchor_x = float('nan'); self.anchor_ms = 0
        self.acc = [f32(0)] * 4; self.acc_n = 0
        self.amb_last_ms = 0; self.amb_ok_since = 0; self.amb_close_since = 0
        self.ticks = 0; self.amb_mode_ticks = 0
        self.amb_timeout_ms = ambient_timeout_min * 60000
        self.amb_filt = float('nan'); self.amb_filt_ms = 0
        self.bound_hits = 0

    # -- model ------------------------------------------------------------
    def theta_prior(self, i):
        # NEW: ka's prior is a fifteenth of the board's ceiling (1000 min ->
        # 66.7 min, the old fixed prior, on every board that keeps the default)
        if self.new and i == 2:
            return -f32(15.0) * self.ka_min
        return THETA_PRIOR[i]

    def load_prior(self):
        self.theta = [self.theta_prior(i) for i in range(N)]
        self.P = [[self.p_prior[i] if i == j else f32(0) for j in range(N)] for i in range(N)]
        self.updates = 0
        self.t_ref = float('nan') if self.new else OLD_TEMP_REF
        self.ref_mode = REF_SETPOINT

    def migrate_from(self, old):
        """setup()'s v3 -> v4 migration: theta + updates kept, P to prior,
        declared at LEGACY_TEMP_REF, re-centred by sync_reference_()."""
        self.theta = [f32(v) for v in old.theta]
        self.P = [[self.p_prior[i] if i == j else f32(0) for j in range(N)] for i in range(N)]
        self.updates = old.updates
        self.t_ref = OLD_TEMP_REF
        self.ref_mode = REF_SETPOINT
        self.clamp_model()
        self.sync_reference(0, float('nan'), float('nan'))
        for i in range(N):
            if self.theta[i] <= THETA_MIN[i] or self.theta[i] >= self.theta_max(i):
                self.theta[i] = self.theta_prior(i)
        self.integral = old.integral; self.heater = old.heater; self.fan = old.fan
        self.light_slot = old.light_slot; self.light_w = old.light_w

    def prior(self, i):
        if self.new and i == 2 and self.ref_mode == REF_AMBIENT:
            return P_KA_AMBIENT
        return self.p_prior[i]

    def set_ka_variance(self, target):
        P = self.P
        if P[2][2] <= 0:
            P[2][2] = f32(target)
            return
        sc = f32(math.sqrt(float(target / P[2][2])))
        for j in range(N):
            if j != 2:
                P[2][j] = f32(P[2][j] * sc); P[j][2] = P[2][j]
        P[2][2] = f32(target)

    def theta_max(self, i):
        return -self.ka_min if i == 2 else THETA_MAX[i]

    def clamp_model(self):
        for i in range(N):
            self.theta[i] = f32(clampf(self.theta[i], THETA_MIN[i], self.theta_max(i)))
            if self.P[i][i] > self.prior(i) * f32(10):
                self.P[i][i] = self.prior(i) * f32(10)
            if self.P[i][i] < 0:
                self.P[i][i] = self.prior(i) * f32(1e-3)

    def project_bounds(self):
        active = False
        P, th = self.P, self.theta
        for i in range(N):
            lo, hi = THETA_MIN[i], self.theta_max(i)
            ti = th[i]
            if lo <= ti <= hi:
                continue
            active = True
            bound = lo if ti < lo else hi
            pii = P[i][i]
            if pii > 1e-20:
                d = f32(bound - ti)
                col = [P[j][i] for j in range(N)]
                for j in range(N):
                    if j != i:
                        th[j] = f32(th[j] + col[j] / pii * d)
                for j in range(N):
                    for k in range(N):
                        if j != i and k != i:
                            P[j][k] = f32(P[j][k] - col[j] * col[k] / pii)
                for j in range(N):
                    if j != i:
                        P[i][j] = P[j][i] = f32(0)
            th[i] = bound
        return active

    def rebase(self, new_ref):
        old = self.t_ref
        if math.isnan(old):
            self.t_ref = f32(new_ref)
            return
        d = f32(new_ref - old)
        if d == 0:
            return
        P = self.P
        self.theta[4] = f32(self.theta[4] + self.theta[2] * d)
        p42, p22 = P[4][2], P[2][2]
        P[4][4] = f32(P[4][4] + f32(2) * d * p42 + d * d * p22)
        for j in range(N):
            if j == 4:
                continue
            P[4][j] = f32(P[4][j] + d * P[2][j])
            P[j][4] = P[4][j]
        self.acc[2] = f32(self.acc[2] - self.acc_n * d)
        self.t_ref = f32(new_ref)
        self.clamp_model()

    def ambient_usable(self, now, amb, t):
        ok = self.has_ambient and self.amb_last_ms != 0 and now - self.amb_last_ms <= self.amb_timeout_ms
        if ok:
            ok = not math.isnan(amb) and C(AMBIENT_MIN_F) <= amb <= C(AMBIENT_MAX_F)
        if ok and not math.isnan(t):
            if abs(t - amb) <= SUBMERGED_BAND:
                if self.amb_close_since == 0:
                    self.amb_close_since = now
                if now - self.amb_close_since >= SUBMERGED_MS:
                    ok = False
            else:
                self.amb_close_since = 0
        if not ok:
            self.amb_ok_since = 0
            self.amb_filt = float('nan')
            return False
        if math.isnan(self.amb_filt) or self.amb_filt_ms == 0:
            self.amb_filt = f32(amb)
        else:
            dt = f32((now - self.amb_filt_ms) / 60000.0)
            self.amb_filt = f32(self.amb_filt + (amb - self.amb_filt) * (dt / (AMBIENT_FILTER_MIN + dt)))
        self.amb_filt_ms = now
        if self.amb_ok_since == 0:
            self.amb_ok_since = now or 1
        if self.ref_mode == REF_AMBIENT:
            return True
        return now - self.amb_ok_since >= AMBIENT_SETTLE_MS

    def sync_reference(self, now, amb, t):
        self.ticks = getattr(self, 'ticks', 0) + 1
        if not self.new:
            return
        if self.ref_mode == REF_AMBIENT:
            self.amb_mode_ticks = getattr(self, 'amb_mode_ticks', 0) + 1
        if self.ambient_usable(now, amb, t):
            amb = self.amb_filt
            if self.ref_mode != REF_AMBIENT:
                self.rebase(amb)
                self.ref_mode = REF_AMBIENT
                if self.P[2][2] < P_KA_AMBIENT:
                    self.set_ka_variance(P_KA_AMBIENT)
            else:
                self.t_ref = f32(amb)
            return
        sp = self.setpoint
        if self.ref_mode == REF_AMBIENT:
            self.ref_mode = REF_SETPOINT
            if self.P[2][2] > self.p_prior[2]:
                self.set_ka_variance(self.p_prior[2])
            self.rebase(sp)
            return
        if math.isnan(self.t_ref) or self.t_ref != sp:
            self.rebase(sp)

    def deadband(self):
        if not self.new:
            return OLD_STALE_DEADBAND
        sigma = f32(math.sqrt(max(float(self.resid_var), 0.0)))
        if sigma < QUANT_RATE_SIGMA_PAIR:
            sigma = QUANT_RATE_SIGMA_PAIR
        ema = sigma * f32(math.sqrt(float(STALE_EMA_W / (f32(2) - STALE_EMA_W))))
        return min(HEALTH_Z * ema, STALE_DEADBAND_MAX)

    def health(self):
        e = abs(self.stale)
        db = self.deadband()
        if e <= db:
            return 1.0
        return clampf(float(1 - (e - db) / STALE_SCALE), 0.0, 1.0)

    def confidence(self):
        return clampf(100.0 * self.updates / 288.0, 0.0, 100.0)

    def tau(self):
        return 1.0 / -float(self.theta[2])

    def at_bound(self):
        return [self.theta[i] <= THETA_MIN[i] or self.theta[i] >= self.theta_max(i) for i in range(N)]

    def learn(self, rate):
        phi = [self.acc[0], self.acc[1], self.acc[2], self.acc[3], f32(1)]
        th, P = self.theta, self.P
        pred = f32(0)
        for i in range(N):
            pred = f32(pred + th[i] * phi[i])
        err = f32(rate - pred)
        if abs(err) > 0.5:
            return
        pphi = [f32(0)] * N
        for i in range(N):
            for j in range(N):
                pphi[i] = f32(pphi[i] + P[i][j] * phi[j])
        info = f32(0)
        for i in range(N):
            info = f32(info + phi[i] * pphi[i])
        if self.new:
            gate = f32(0)
            for i in range(4):
                for j in range(4):
                    gate = f32(gate + phi[i] * P[i][j] * phi[j])
        else:
            gate = info
        informative = gate > INFO_MIN
        lam = f32(1) if self.new else (LAMBDA_OLD if informative else f32(1))
        den = f32(lam + info)
        for i in range(N):
            th[i] = f32(th[i] + (pphi[i] / den) * err)
        for i in range(N):
            for j in range(N):
                P[i][j] = f32((P[i][j] - (pphi[i] * pphi[j]) / den) / lam)
        for i in range(N):
            for j in range(i + 1, N):
                a = f32(f32(0.5) * (P[i][j] + P[j][i]))
                P[i][j] = P[j][i] = a
        if self.new:
            if self.project_bounds():
                self.bound_hits += 1
                post = f32(0)
                for i in range(N):
                    post = f32(post + th[i] * phi[i])
                want = f32(err * lam / den)
                refit = f32((rate - post) - want)
                c = f32(th[4] + refit)
                if THETA_MIN[4] <= c <= THETA_MAX[4]:
                    th[4] = c
            P[4][4] = f32(P[4][4] + Q_C)
            P[2][2] = f32(P[2][2] + (Q_KA_AMBIENT if self.ref_mode == REF_AMBIENT else Q_KA_SETPOINT))
        else:
            if any(th[i] < THETA_MIN[i] or th[i] > self.theta_max(i) for i in range(N)):
                self.bound_hits += 1
        self.clamp_model()
        self.updates += 1
        self.bias = f32((1 - BIAS_EMA_W) * self.bias + BIAS_EMA_W * err)
        self.stale = f32((1 - STALE_EMA_W) * self.stale + STALE_EMA_W * err)
        dev = f32(err - self.stale)
        self.resid_var = f32((1 - STALE_EMA_W) * self.resid_var + STALE_EMA_W * dev * dev)
        if informative and self.health() < 1.0:
            for i in range(N):
                lim = self.prior(i)
                if P[i][i] < lim:
                    P[i][i] = f32(min(P[i][i] * P_REINFLATE, lim))

    # -- one 30 s tick of update() ---------------------------------------
    def update(self, now, minute_of_day, t, cross, lux, amb, amb_reported=False):
        dt = f32(0.5)
        if self.has_ambient and amb_reported:
            self.amb_last_ms = now
        self.sync_reference(now, amb, t)
        lux_norm = f32(clampf(lux / float(self.full_scale_lux), 0.0, 1.5))
        slot = int(minute_of_day) // 15
        first = slot != self.last_slot
        self.last_slot = slot
        w = self.light_w[slot]
        alpha = f32(1) if w < 1 else f32(0.15)
        self.light_slot[slot] = f32(self.light_slot[slot] * (1 - alpha) + lux_norm * alpha)
        if first and w < 30:
            self.light_w[slot] = f32(w + 1)

        ref_now = self.t_ref if self.new else OLD_TEMP_REF
        self.acc[0] = f32(self.acc[0] + self.heater)
        self.acc[1] = f32(self.acc[1] + self.fan)
        self.acc[3] = f32(self.acc[3] + lux_norm)
        self.acc[2] = f32(self.acc[2] + (t - ref_now))
        self.acc_n += 1
        x = float('nan')
        if self.new and self.has_cross and not math.isnan(cross) and abs(t - cross) <= self.disagree_band:
            x = cross
        if math.isnan(self.anchor_t):
            self.acc = [f32(0)] * 4; self.acc_n = 0
            self.anchor_t = t; self.anchor_x = x; self.anchor_ms = now
        elif now - self.anchor_ms >= LEARN_WINDOW_MS and self.acc_n > 0:
            wmin = f32((now - self.anchor_ms) / 60000.0)
            da = f32(t - self.anchor_t)
            delta = da
            if not math.isnan(x) and not math.isnan(self.anchor_x):
                db = f32(x - self.anchor_x)
                if abs(db - da) <= PAIR_RATE_TOL:
                    delta = f32(f32(0.5) * (da + db))
            rate = f32(delta / wmin)
            self.acc = [f32(a / self.acc_n) for a in self.acc]
            self.learn(rate)
            self.acc = [f32(0)] * 4; self.acc_n = 0
            self.anchor_t = t; self.anchor_x = x; self.anchor_ms = now

        th = self.theta
        kh = th[0]; kf = -th[1]
        pslot = int((minute_of_day + float(self.rt)) % 1440) // 15
        pl = self.light_slot[pslot] if self.light_w[pslot] >= 2 else lux_norm
        ref_now = self.t_ref if self.new else OLD_TEMP_REF
        passive_raw = f32(th[2] * (t - ref_now) + th[3] * pl + th[4])
        trust = f32(clampf(self.confidence() / 100, 0, 1) * self.health())
        passive = f32(passive_raw * trust)
        error = f32(self.setpoint - t)
        desired = f32(clampf(float(error / self.rt), -0.15, 0.15))
        ki = f32(1) / (self.rt * self.rt)
        self.integral = f32(self.integral + error * dt * ki)
        imh = INTEGRAL_AUTHORITY * (kh if kh > 1e-4 else THETA_PRIOR[0])
        imc = INTEGRAL_AUTHORITY * (kf if kf > 1e-4 else -THETA_PRIOR[1])
        self.integral = f32(clampf(self.integral, -imc, imh))
        net = f32(desired + self.integral - passive)
        h = f = f32(0)
        if net > 0:
            h = net / kh if kh > 1e-4 else f32(0)
        elif net < 0:
            if self.fan_available and kf > 1e-4:
                f = -net / kf
        if error < -GUARD_DEADBAND and h > 0:
            h = f32(0)
        elif error > GUARD_DEADBAND and f > 0:
            f = f32(0)
        elif f > 0 and error > -self.fan_db:
            f = f32(0)
        if (h >= 1 and error > 0) or (f >= 1 and error < 0):
            self.integral = f32(self.integral - error * dt * ki)
        if self.fan_available and error > -self.fan_db and self.integral < 0:
            self.integral = f32(0)
        if error < -GUARD_DEADBAND and self.integral > 0:
            self.integral = f32(0)
        self.heater = f32(clampf(float(h), 0, 1))
        self.fan = f32(clampf(float(f), 0, 1)) if self.fan_available else f32(0)
        rate_now = kh * self.heater + th[1] * self.fan + passive_raw
        self.predicted = float(t + rate_now * 15)


def plant_for(kind, tau):
    if kind == '75':
        # 2 x 150 W on ~235 L as learned on the 75: ~4.9 degF/h at 100%.
        return dict(tau=tau, kh=4.9 / CMIN_TO_FH, kf=2.0 / CMIN_TO_FH, kl=0.3 / CMIN_TO_FH,
                    setpoint_f=77.0, max_tau=6000, offset_b=0.15)
    # nano: ~10 gal, one heater
    return dict(tau=tau, kh=8.0 / CMIN_TO_FH, kf=3.0 / CMIN_TO_FH, kl=1.0 / CMIN_TO_FH,
                setpoint_f=76.0, max_tau=1000, offset_b=0.3)


OFFICE_F = ((0, 71.8), (180, 71.6), (360, 71.4), (540, 73.8), (720, 73.5), (910, 75.0),
            (1080, 73.0), (1260, 71.8), (1440, 71.8))


def office_room_f(minute_of_day):
    for (m0, v0), (m1, v1) in zip(OFFICE_F, OFFICE_F[1:]):
        if m0 <= minute_of_day <= m1:
            return v0 + (v1 - v0) * (minute_of_day - m0) / (m1 - m0)
    return OFFICE_F[-1][1]


def simulate(ctrl, plant, days, seed=1, swap_day=None, make_new=None, ambient_probe=False,
             sp_changes=(), room_step_day=10.0, start_day_metrics=2.0):
    rng = random.Random(seed)
    T = C(plant['setpoint_f'])
    off_a = 0.0
    off_b = C(32 + plant['offset_b']) - C(32)
    tick_ms = 30000
    pred_hist = {}
    rec = dict(t=[], health=[], stale=[], db=[], tau=[], bias=[], T=[], heater=[], pred_err=[], at_bound=[], c=[])
    sp = C(plant['setpoint_f'])
    nticks = int(days * 2880)
    last_zb = None
    for k in range(nticks):
        now = (k + 1) * tick_ms
        tmin = now / 60000.0
        day = tmin / 1440
        mod = tmin % 1440
        for (d, f_new) in sp_changes:
            if abs(day - d) < 1e-9 + 0.5 / 2880:
                ctrl.setpoint = f32(C(f_new)); ctrl.integral = f32(0); sp = C(f_new)
        if swap_day is not None and abs(day - swap_day) < 0.5 / 2880:
            ctrl = make_new(ctrl)
        room = C(office_room_f(mod) + (3 if day >= room_step_day else 0))
        light = 1.0 if 540 <= mod < 960 else 0.0
        # 30 s of plant in 5 s substeps, slow_pwm 900 s windows phase-locked at boot
        for s in range(6):
            ts = (now - tick_ms) / 1000.0 + s * 5
            ph = (ts % 900.0) / 900.0
            h_on = 1.0 if ph < float(ctrl.heater) else 0.0
            f_on = 1.0 if ph < float(ctrl.fan) else 0.0
            dT = plant['kh'] * h_on - plant['kf'] * f_on - (T - room) / plant['tau'] + plant['kl'] * light
            T += dT * 5 / 60.0
        q = lambda v: round(v / 0.0625) * 0.0625
        ta = f32(q(T + off_a + rng.gauss(0, 0.01)))
        tb = f32(q(T + off_b + rng.gauss(0, 0.01)))
        reported = False
        if ambient_probe:
            zq = round((room + 0.1 + rng.gauss(0, 0.03)) / 0.2) * 0.2   # 0.2 degC steps, +0.1 C sensor offset
            if zq != last_zb:
                last_zb = zq
                reported = True                                       # report on change only
        amb = f32(last_zb) if (ambient_probe and last_zb is not None) else float('nan')
        ctrl.update(now, mod, ta, tb, light * 3000.0 * 0.9, amb, reported)
        pred_hist[k + 30] = ctrl.predicted
        if k in pred_hist:
            rec['pred_err'].append((day, F(pred_hist.pop(k)) - F(T)))
        if k % 10 == 0:
            rec['t'].append(day); rec['health'].append(ctrl.health()); rec['stale'].append(float(ctrl.stale))
            rec['db'].append(float(ctrl.deadband())); rec['tau'].append(ctrl.tau()); rec['bias'].append(float(ctrl.bias))
            rec['T'].append((day, F(T) - F(sp))); rec['heater'].append(float(ctrl.heater)); rec['at_bound'].append(ctrl.at_bound()[2])
            rec['c'].append(float(ctrl.theta[4]))
    return ctrl, rec


def summarize(rec, days, step_day=10.0, start=2.0):
    idx = [i for i, t in enumerate(rec['t']) if t >= start]
    after_step = [i for i in idx if not (step_day <= rec['t'][i] < step_day + 0.5)]
    h = [rec['health'][i] for i in after_step]
    within = sum(1 for i in idx if abs(rec['stale'][i]) <= rec['db'][i]) / max(1, len(idx))
    # recovery: first time after the step that health is back >= 95 % and stays for 2 h
    rec_h = float('nan')
    step_idx = [i for i, t in enumerate(rec['t']) if t >= step_day]
    dipped = any(rec['health'][i] < 0.95 for i in step_idx[: 20 * 12])
    if not dipped:
        rec_h = 0.0
    else:
        seen_dip = False
        for n, i in enumerate(step_idx):
            if rec['health'][i] < 0.95:
                seen_dip = True
            elif seen_dip and all(rec['health'][j] >= 0.95 for j in step_idx[n:n + 24]):
                rec_h = (rec['t'][i] - step_day) * 24
                break
    pe = [e for (d, e) in rec['pred_err'] if d >= start]
    terr = [e for (d, e) in rec['T'] if d >= start]
    last = [i for i, t in enumerate(rec['t']) if t >= days - 5]
    return dict(
        health_min=100 * min(h), health_mean=100 * sum(h) / len(h),
        within_db=100 * within,
        recover_h=rec_h,
        pred_rms=math.sqrt(sum(e * e for e in pe) / len(pe)),
        ctrl_rms=math.sqrt(sum(e * e for e in terr) / len(terr)),
        ctrl_mean=sum(terr) / len(terr),
        stale_end=rec['stale'][-1] * CMIN_TO_FH, db_end=rec['db'][-1] * CMIN_TO_FH,
        bias_last5=sum(rec['bias'][i] for i in last) / len(last) * CMIN_TO_FH,
        tau_end=rec['tau'][-1],
        ka_pinned_pct=100 * sum(1 for i in last if rec['at_bound'][i]) / len(last),
    )


def row(label, s):
    print(f"{label:30s} {s['health_min']:6.0f} {s['health_mean']:6.1f} {s['within_db']:6.0f} {s['recover_h']:7.1f}"
          f" {s['pred_rms']:7.3f} {s['ctrl_rms']:7.3f} {s['ctrl_mean']:+7.3f} {s['bias_last5']:+7.2f}"
          f" {s['tau_end']:7.0f} {s['ka_pinned_pct']:5.0f}")


HEADER_NOTE = "room: office profile (3.5 degF daily swing) + 3 degF step on day 10"
HEADER = ("scenario                       hMin%  hMean%  |st|<db%  rec(h)  pred15  ctrlRMS ctrlMean  bias5d"
          "   tau   ka@bnd%\n"
          "                               (after day 2, excl. 12 h after step)  degF    degF    degF   degF/h"
          "   min   last5d")


def selftest():
    """rebase_() must not change the prediction at any temperature."""
    c = Controller(True, 77.0, 6000)
    c.t_ref = f32(24.0)
    c.theta = [f32(0.04), f32(-0.02), f32(-0.0008), f32(0.003), f32(-0.01)]
    before = [c.theta[2] * (T - c.t_ref) + c.theta[4] for T in (f32(22.0), f32(25.0), f32(28.0))]
    c.rebase(f32(25.0))
    after = [c.theta[2] * (T - c.t_ref) + c.theta[4] for T in (f32(22.0), f32(25.0), f32(28.0))]
    assert all(abs(float(a - b)) < 1e-7 for a, b in zip(before, after)), (before, after)
    # bounded projection: pinned parameter decoupled, prediction direction kept
    c.theta[2] = f32(-0.00001)
    c.P[2][4] = c.P[4][2] = f32(-5e-5)
    c.project_bounds()
    assert c.theta[2] == -c.ka_min and c.P[2][4] == 0 and c.P[4][2] == 0
    print("selftest: rebase invariant, projection decouples the pinned parameter -- ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--days', type=float, default=30.0)
    a = ap.parse_args()
    days = 10.0 if a.quick else a.days
    selftest()
    print(HEADER_NOTE)
    print(HEADER)
    for kind, taus in (('75', (300, 1000, 3000)), ('nano', (60, 120, 200))):
        for tau in taus:
            p = plant_for(kind, tau)
            for new in (False, True):
                ctrl = Controller(new, p['setpoint_f'], p['max_tau'])
                _, rec = simulate(ctrl, p, days)
                row(f"{kind} tau={tau} {'NEW' if new else 'OLD'}", summarize(rec, days))
    # the 75's real history: old firmware for 10 days, then this firmware
    # flashed over it (v3 -> v4 migration), room step on day 15
    p = plant_for('75', 1000)
    def flash(old):
        n = Controller(True, p['setpoint_f'], p['max_tau'])
        n.migrate_from(old)
        n.anchor_t = float('nan')
        return n
    _, rec = simulate(Controller(False, p['setpoint_f'], p['max_tau']), p, days + 10, swap_day=10.0,
                      make_new=flash, room_step_day=15.0)
    s = summarize(rec, days + 10, step_day=15.0, start=12.0)
    row("75 tau=1000 OLD->flash d10", s)
    pre = [rec['bias'][i] for i, t in enumerate(rec['t']) if 9.5 <= t < 10.0]
    hrs = next((t - 10.0) * 24 for i, t in enumerate(rec['t']) if t > 10.0 and abs(rec['stale'][i]) <= rec['db'][i]
               and all(abs(rec['stale'][j]) <= rec['db'][j] for j in range(i, min(i + 24, len(rec['t'])))))
    print(f"    migration: bias before flash {sum(pre)/len(pre)*CMIN_TO_FH:+.2f} degF/h; |stale| inside deadband "
          f"{hrs:.1f} h after the flash")
    # the office Zigbee sensor as the room input
    for kind, tau in (('75', 300), ('75', 1000), ('75', 3000), ('nano', 120)):
        p = plant_for(kind, tau)
        c, rec = simulate(Controller(True, p['setpoint_f'], p['max_tau'], ambient=True), p, days, ambient_probe=True)
        row(f"{kind} tau={tau} NEW+zigbee", summarize(rec, days))
        amb_pct = 100 * c.amb_mode_ticks / max(1, c.ticks)
        print(f"    room in use {amb_pct:.0f}% of ticks")
    # setpoint moves 77 -> 79 -> 77: an excursion ka can learn from
    p = plant_for('75', 1000)
    _, rec = simulate(Controller(True, p['setpoint_f'], p['max_tau']), p, days,
                      sp_changes=((5.0, 79.0), (7.0, 77.0)))
    row("75 tau=1000 NEW sp 77/79/77", summarize(rec, days))


if __name__ == '__main__':
    main()
