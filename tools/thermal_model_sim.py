#!/usr/bin/env python3
"""Offline check of components/tank_controller's thermal model and control law.

Mirrors TankController::update() / learn_() / rebase_() / project_bounds_() /
apply_physics_() statement for statement, in float32 (numpy) like the ESP32,
and drives them with a simulated tank:

  * first-order plant  dT/dt = kh*H - kf*F - (T - T_air)/tau + kl*L + c0
    where c0 is the tank's own heat (pumps) minus open-surface evaporation,
    which depends on the cover, and T_air is the room -- or, for a tank in a
    closed stand, a cabinet air node between the tank and the room
  * heater and fan through 900 s slow_pwm windows, as on the boards. The 75's
    board (allinone-freenove) restarts the window on every 0 -> >0 edge of
    the heater demand, so the relay delivers far more than the commanded duty
    while the loop is toggling; the nano's (xiao-esp32s3) does not
  * two DS18B20s (control + cross-check) with offsets, noise and 0.0625 degC
    quantisation
  * room: the REAL office the 75 sits in, 17 days of Home Assistant 5 minute
    means (tools/data/75gal_2026-09-27_10-14_5min.csv), looped -- quiet
    afternoons like 2026-10-14's included -- or the synthetic profile
  * optional Zigbee room sensor: 0.2 degC steps, report-on-change only
  * lights 09:00-16:00

Three firmwares:
  OLD  = bbf4b6f  (fixed 24.0 degC reference, plain clamp)
  PREV = 201f2c8  (operating-point reference, projection, random-walk c, Q on
                   ka, ka variance 1e-2 with a room sensor, commanded duty)
  NEW  = this component (tank physics -> ka/kh priors and bounds, delivered
         relay duty as the regressor, ka centred so it only learns from
         excitation, Q on ka = 0)

    python3 tools/thermal_model_sim.py              # full table, a few minutes
    python3 tools/thermal_model_sim.py --quick      # shorter runs
    python3 tools/thermal_model_sim.py --measure    # tau from the real history
    python3 tools/thermal_model_sim.py --replay     # real history through NEW

Needs numpy. Nothing here is imported by the firmware.
"""
import argparse
import math
import os
import random

import numpy as np

f32 = np.float32
N = 5
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data', '75gal_2026-09-27_10-14_5min.csv')

# --- constants shared by every firmware (tank_controller.cpp) -------------
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

OLD_TEMP_REF = f32(24.0)
OLD_P_PRIOR = [f32(v) for v in (1e-3, 1e-3, 1e-4, 1e-5, 1e-5)]
OLD_STALE_DEADBAND = f32(0.0125)

C_TRACK_STEPS = f32(24.0)
Q_C = f32(1.0) / (C_TRACK_STEPS * (C_TRACK_STEPS - f32(1.0)))
PREV_Q_KA_SETPOINT = f32(1e-7)
PREV_Q_KA_AMBIENT = f32(1e-6)
P_KA_AMBIENT = f32(1e-2)
P_PRIOR = [f32(1e-3), f32(1e-3), f32(1e-4), f32(1e-5), f32(1.0) / (C_TRACK_STEPS - f32(1.0))]
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

# --- NEW: tank physics (tank_controller.cpp, "What the tank's size says") --
GAL_TO_L = 3.785411784
FILL_DEFAULT = 0.85
CP_WATER = 4186.0
U_WALL = (3.0, 10.0)
COVER_OPEN, COVER_LID, COVER_EVAP, COVER_UNKNOWN = 0, 1, 2, 3
U_TOP = {COVER_OPEN: (10.0, 25.0), COVER_LID: (3.0, 8.0), COVER_EVAP: (2.0, 5.0), COVER_UNKNOWN: (2.0, 25.0)}
PLACE_ROOM, PLACE_CABINET = 0, 1
CAB_AREA_FACTOR = 2.0
U_CAB = (1.5, 6.0)
BAND_MARGIN = 1.25
KH_BAND = (0.4, 1.5)
KH_REL_SIGMA = 0.02
KA_SIGMA_FRAC = 0.25
P_SIGMA_N = 0.005
KA_CENTRE_MIN = f32(720.0)
P_KL_PHYS = f32(0.2)
KA_EXCITE = f32(0.3 * 5 / 9)

F = lambda c: float(c) * 9 / 5 + 32
C = lambda f: (f - 32) * 5 / 9
CMIN_TO_FH = 108.0


def clampf(v, lo, hi):
    if math.isnan(v):
        return lo
    return lo if v < lo else (hi if v > hi else v)


def physics(tank_gal, water_gal, heater_w, cover, placement):
    """apply_physics_()'s band, in the controller's units (1/min, degC/min)."""
    if not tank_gal or tank_gal <= 0:
        return None
    v = tank_gal * GAL_TO_L / 1000.0
    w = (v / 2.4) ** (1 / 3)
    l, h = 2 * w, 1.2 * w
    a_top = l * w
    a_wall = 2 * (l + w) * h
    water = water_gal if water_gal and water_gal > 0 else FILL_DEFAULT * tank_gal
    cap = water * GAL_TO_L * CP_WATER
    ut = U_TOP[cover]
    lo = a_wall * U_WALL[0] + a_top * ut[0]
    hi = a_wall * U_WALL[1] + a_top * ut[1]
    if placement == PLACE_CABINET:
        a_cab = CAB_AREA_FACTOR * (a_wall + 2 * a_top)
        clo, chi = a_cab * U_CAB[0], a_cab * U_CAB[1]
        lo = 1 / (1 / lo + 1 / clo)
        hi = 1 / (1 / hi + 1 / chi)
    ka_prior = math.sqrt(lo * hi) * 60 / cap
    ka_min = lo / BAND_MARGIN * 60 / cap
    ka_max = hi * BAND_MARGIN * 60 / cap
    kh = heater_w / cap * 60 if heater_w and heater_w > 0 else None
    return dict(ka_prior=ka_prior, ka_min=ka_min, ka_max=ka_max, kh=kh, cap=cap, ua_lo=lo, ua_hi=hi)


class Controller:
    """TankController. Temperatures degC, rates degC/min.

    variant: 'old' (bbf4b6f), 'prev' (201f2c8), 'new' (this component).
    phys: (tank_gal, water_gal, heater_w, cover, placement) or None.
    """

    def __init__(self, variant, setpoint_f, max_tau=None, phys=None, fan_available=True, cross=True,
                 ambient=False, ambient_timeout_min=180, full_scale_lux=3000.0, response_time=20.0,
                 fan_deadband_f=0.25, disagree_band_f=8.0, relay=True, centre=True):
        self.v = variant
        self.new = variant == 'new'
        self.max_tau_cfg = max_tau
        self.phys_in = phys
        self.relay = relay and self.new
        self.centre = centre and self.new
        self.fan_available = fan_available
        self.has_cross = cross
        self.has_ambient = ambient
        self.full_scale_lux = f32(full_scale_lux)
        self.rt = f32(response_time)
        self.fan_db = f32(fan_deadband_f * 5 / 9)
        self.disagree_band = f32(disagree_band_f * 5 / 9)
        self.setpoint = f32(C(setpoint_f))
        self.compute_band()
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
        self.centre_off = f32(0)
        self.centre_init = False
        self.physics_pending = False
        self.last_t = float('nan')
        self.bound_hits = 0
        # delivered on-time accounting (seconds, monotonic) and its 15 min ring
        self.h_on_total = 0.0; self.f_on_total = 0.0
        self.anchor_h_on = 0.0; self.anchor_f_on = 0.0
        self.ring_h = [0.0] * 30; self.ring_f = [0.0] * 30; self.ring_i = 0; self.ring_n = 0

    # -- physics ----------------------------------------------------------
    def compute_band(self):
        p = physics(*self.phys_in) if (self.new and self.phys_in) else None
        self.ph = p
        if p is None:
            mt = self.max_tau_cfg if self.max_tau_cfg else 1000.0
            self.ka_lo = f32(1.0 / mt)
            self.ka_hi = -THETA_MIN[2]
            self.ka_prior = f32(15.0) * self.ka_lo
            self.p_ka = P_PRIOR[2]
            self.kh_prior = THETA_PRIOR[0]; self.kh_lo = THETA_MIN[0]; self.kh_hi = THETA_MAX[0]
            self.p_kh = P_PRIOR[0]
            return
        self.ka_lo = f32(p['ka_min'] if not self.max_tau_cfg else 1.0 / self.max_tau_cfg)
        self.ka_hi = f32(min(p['ka_max'], float(-THETA_MIN[2])))
        self.ka_prior = f32(clampf(p['ka_prior'], float(self.ka_lo), float(self.ka_hi)))
        sig = KA_SIGMA_FRAC * (float(self.ka_hi) - float(self.ka_lo))
        self.p_ka = f32((sig / P_SIGMA_N) ** 2)
        if p['kh']:
            self.kh_prior = f32(p['kh'])
            self.kh_lo = f32(max(KH_BAND[0] * p['kh'], float(THETA_MIN[0])))
            self.kh_hi = f32(min(KH_BAND[1] * p['kh'], float(THETA_MAX[0])))
            self.p_kh = f32((KH_REL_SIGMA * p['kh'] / P_SIGMA_N) ** 2)
        else:
            self.kh_prior = THETA_PRIOR[0]; self.kh_lo = THETA_MIN[0]; self.kh_hi = THETA_MAX[0]
            self.p_kh = P_PRIOR[0]

    def theta_prior(self, i):
        if self.v == 'old':
            return THETA_PRIOR[i]
        if i == 2:
            return -self.ka_prior
        if i == 0:
            return self.kh_prior
        return THETA_PRIOR[i]

    def theta_min(self, i):
        if i == 2:
            return -self.ka_hi
        if i == 0:
            return self.kh_lo
        return THETA_MIN[i]

    def theta_max(self, i):
        if i == 2:
            return -self.ka_lo
        if i == 0:
            return self.kh_hi
        return THETA_MAX[i]

    def prior(self, i):
        if self.v == 'old':
            return OLD_P_PRIOR[i]
        if i == 2:
            if self.ph is None and self.ref_mode == REF_AMBIENT:
                return P_KA_AMBIENT
            return self.p_ka
        if i == 0:
            return self.p_kh
        if i == 3 and self.ph is not None:
            return P_KL_PHYS
        return P_PRIOR[i]

    def load_prior(self):
        self.ref_mode = REF_SETPOINT
        self.theta = [self.theta_prior(i) for i in range(N)]
        self.P = [[self.prior(i) if i == j else f32(0) for j in range(N)] for i in range(N)]
        self.updates = 0
        self.t_ref = float('nan') if self.v != 'old' else OLD_TEMP_REF

    def reset_param(self, i, t_now, u_now):
        """apply_physics_(): move theta[i] to its prior, keep today's prediction
        by remapping c, and decouple + re-open its covariance."""
        old = self.theta[i]
        new = self.theta_prior(i)
        if i == 2 and not math.isnan(self.t_ref) and not math.isnan(t_now):
            self.theta[4] = f32(self.theta[4] + (old - new) * f32(t_now - self.t_ref))
        if i == 0:
            self.theta[4] = f32(self.theta[4] + (old - new) * f32(u_now))
        self.theta[i] = new
        for j in range(N):
            if j != i:
                self.P[i][j] = self.P[j][i] = f32(0)
        self.P[i][i] = self.prior(i)
        self.theta[4] = f32(clampf(self.theta[4], THETA_MIN[4], THETA_MAX[4]))

    def set_physics(self, phys, t_now=float('nan'), reset_ka=True, reset_kh=False):
        """apply_physics_(): new band; reset what it determines."""
        self.phys_in = phys
        self.compute_band()
        u = self.recent_heat()
        if reset_ka:
            self.reset_param(2, t_now, u)
        if reset_kh and self.ph is not None and self.ph['kh']:
            self.reset_param(0, t_now, u)
        self.clamp_model()

    def migrate_prev(self, old):
        """First boot of NEW over a PREV model (201f2c8): theta, t_ref and the
        covariance are kept; physics then resets ka (and kh, with a wattage)."""
        self.theta = [f32(v) for v in old.theta]
        self.P = [[f32(old.P[i][j]) for j in range(N)] for i in range(N)]
        self.updates = old.updates
        self.t_ref = old.t_ref
        self.ref_mode = old.ref_mode
        self.amb_filt = old.amb_filt; self.amb_filt_ms = old.amb_filt_ms
        self.amb_last_ms = old.amb_last_ms; self.amb_ok_since = old.amb_ok_since
        self.clamp_model()
        self.physics_pending = True       # applied on the first valid reading
        self.integral = old.integral; self.heater = old.heater; self.fan = old.fan
        self.light_slot = old.light_slot; self.light_w = old.light_w

    def migrate_from(self, old):
        """bbf4b6f -> PREV (v3 -> v4): theta + updates kept, P to prior,
        declared at LEGACY_TEMP_REF, re-centred."""
        self.theta = [f32(v) for v in old.theta]
        self.P = [[self.prior(i) if i == j else f32(0) for j in range(N)] for i in range(N)]
        self.updates = old.updates
        self.t_ref = OLD_TEMP_REF
        self.ref_mode = REF_SETPOINT
        self.clamp_model()
        self.sync_reference(0, float('nan'), float('nan'))
        if self.theta[2] <= self.theta_min(2) or self.theta[2] >= self.theta_max(2):
            self.theta[2] = self.theta_prior(2)
        self.integral = old.integral; self.heater = old.heater; self.fan = old.fan
        self.light_slot = old.light_slot; self.light_w = old.light_w

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

    def clamp_model(self):
        for i in range(N):
            self.theta[i] = f32(clampf(self.theta[i], self.theta_min(i), self.theta_max(i)))
            if self.P[i][i] > self.prior(i) * f32(10):
                self.P[i][i] = self.prior(i) * f32(10)
            if self.P[i][i] < 0:
                self.P[i][i] = self.prior(i) * f32(1e-3)

    def project_bounds(self):
        active = False
        P, th = self.P, self.theta
        for i in range(N):
            lo, hi = self.theta_min(i), self.theta_max(i)
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
        self.ticks += 1
        if self.v == 'old':
            return
        if self.ref_mode == REF_AMBIENT:
            self.amb_mode_ticks += 1
        if self.ambient_usable(now, amb, t):
            a = self.amb_filt
            if self.ref_mode != REF_AMBIENT or (self.centre and not self.centre_init):
                # NEW: enter (or, restored in ambient mode, re-enter) centred
                # on where the water is now, so the loss regressor starts at
                # zero and only the room's movement from here on reaches ka.
                if self.centre and math.isnan(t):
                    return
                self.centre_off = f32(t - a) if self.centre else f32(0)
                self.centre_init = True
                self.rebase(f32(a + self.centre_off))
                self.ref_mode = REF_AMBIENT
                if self.ph is None and self.P[2][2] < P_KA_AMBIENT:
                    self.set_ka_variance(P_KA_AMBIENT)
            else:
                self.t_ref = f32(a + self.centre_off)
            return
        sp = self.setpoint
        if self.ref_mode == REF_AMBIENT:
            self.ref_mode = REF_SETPOINT
            self.centre_init = False
            if self.ph is None and self.P[2][2] > self.p_ka:
                self.set_ka_variance(self.p_ka)
            self.rebase(sp)
            return
        if math.isnan(self.t_ref) or self.t_ref != sp:
            self.rebase(sp)

    def update_centre(self, dev_avg, wmin):
        """NEW: after each learning step, the ambient-mode offset follows the
        window's mean deviation with a KA_CENTRE_MIN time constant, by rebase."""
        if not self.centre or self.ref_mode != REF_AMBIENT:
            return
        a = f32(wmin / (KA_CENTRE_MIN + wmin))
        step = f32(dev_avg * a)
        if step == 0:
            return
        self.centre_off = f32(self.centre_off + step)
        self.rebase(f32(self.t_ref + step))

    def deadband(self):
        if self.v == 'old':
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
        return [self.theta[i] <= self.theta_min(i) or self.theta[i] >= self.theta_max(i) for i in range(N)]

    def recent_heat(self):
        if not self.relay or self.ring_n == 0:
            return float(self.heater)
        return clampf(sum(self.ring_h[:self.ring_n]) / (self.ring_n * 30.0), 0.0, 1.0)

    def recent_fan(self):
        if not self.relay or self.ring_n == 0:
            return float(self.fan)
        return clampf(sum(self.ring_f[:self.ring_n]) / (self.ring_n * 30.0), 0.0, 1.0)

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
        if self.v != 'old':
            gate = f32(0)
            for i in range(4):
                for j in range(4):
                    gate = f32(gate + phi[i] * P[i][j] * phi[j])
        else:
            gate = info
        informative = gate > INFO_MIN
        lam = f32(1) if self.v != 'old' else (LAMBDA_OLD if informative else f32(1))
        den = f32(lam + info)
        if self.new:
            # NEW: ka only moves on a window that actually excites it; otherwise
            # it is a "consider" parameter -- its gain is zeroed and P is
            # updated in Joseph form, which stays exact for a non-optimal gain.
            K = [f32(pphi[i] / den) for i in range(N)]
            self.ka_excited = abs(phi[2]) >= KA_EXCITE
            if not self.ka_excited:
                K[2] = f32(0)
            for i in range(N):
                th[i] = f32(th[i] + K[i] * err)
            # A = I - K phi';  P = A P A' + K K'
            AP = [[f32(P[i][j] - K[i] * sum(phi[k] * P[k][j] for k in range(N))) for j in range(N)]
                  for i in range(N)]
            for i in range(N):
                for j in range(N):
                    P[i][j] = f32(AP[i][j] - sum(AP[i][k] * phi[k] for k in range(N)) * K[j] + K[i] * K[j])
        else:
            for i in range(N):
                th[i] = f32(th[i] + (pphi[i] / den) * err)
            for i in range(N):
                for j in range(N):
                    P[i][j] = f32((P[i][j] - (pphi[i] * pphi[j]) / den) / lam)
        for i in range(N):
            for j in range(i + 1, N):
                a = f32(f32(0.5) * (P[i][j] + P[j][i]))
                P[i][j] = P[j][i] = a
        if self.v != 'old':
            if self.project_bounds():
                self.bound_hits += 1
                post = f32(0)
                for i in range(N):
                    post = f32(post + th[i] * phi[i])
                if self.new:
                    want = f32(err * (f32(1) - sum(phi[i] * K[i] for i in range(N))))
                else:
                    want = f32(err * lam / den)
                refit = f32((rate - post) - want)
                c = f32(th[4] + refit)
                if THETA_MIN[4] <= c <= THETA_MAX[4]:
                    th[4] = c
            P[4][4] = f32(P[4][4] + Q_C)
            if self.v == 'prev':
                P[2][2] = f32(P[2][2] + (PREV_Q_KA_AMBIENT if self.ref_mode == REF_AMBIENT else PREV_Q_KA_SETPOINT))
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
    def update(self, now, minute_of_day, t, cross, lux, amb, amb_reported=False, h_on_s=0.0, f_on_s=0.0):
        dt = f32(0.5)
        self.last_t = t
        self.h_on_total += h_on_s
        self.f_on_total += f_on_s
        self.ring_h[self.ring_i] = h_on_s; self.ring_f[self.ring_i] = f_on_s
        self.ring_i = (self.ring_i + 1) % 30; self.ring_n = min(self.ring_n + 1, 30)
        if self.has_ambient and amb_reported:
            self.amb_last_ms = now
        self.sync_reference(now, amb, t)
        if self.physics_pending:
            self.physics_pending = False
            if self.ph is not None and self.P[3][3] < self.prior(3):
                for j in range(N):
                    if j != 3:
                        self.P[3][j] = self.P[j][3] = f32(0)
                self.P[3][3] = self.prior(3)
            self.set_physics(self.phys_in, t, reset_ka=True, reset_kh=True)
        lux_norm = f32(clampf(lux / float(self.full_scale_lux), 0.0, 1.5))
        slot = int(minute_of_day) // 15
        first = slot != self.last_slot
        self.last_slot = slot
        w = self.light_w[slot]
        alpha = f32(1) if w < 1 else f32(0.15)
        self.light_slot[slot] = f32(self.light_slot[slot] * (1 - alpha) + lux_norm * alpha)
        if first and w < 30:
            self.light_w[slot] = f32(w + 1)

        ref_now = self.t_ref if self.v != 'old' else OLD_TEMP_REF
        if not self.relay:
            self.acc[0] = f32(self.acc[0] + self.heater)
            self.acc[1] = f32(self.acc[1] + self.fan)
        self.acc[3] = f32(self.acc[3] + lux_norm)
        self.acc[2] = f32(self.acc[2] + (t - ref_now))
        self.acc_n += 1
        x = float('nan')
        if self.v != 'old' and self.has_cross and not math.isnan(cross) and abs(t - cross) <= self.disagree_band:
            x = cross
        if math.isnan(self.anchor_t):
            self.acc = [f32(0)] * 4; self.acc_n = 0
            self.anchor_t = t; self.anchor_x = x; self.anchor_ms = now
            self.anchor_h_on = self.h_on_total; self.anchor_f_on = self.f_on_total
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
            if self.relay:
                wsec = (now - self.anchor_ms) / 1000.0
                self.acc[0] = f32(clampf((self.h_on_total - self.anchor_h_on) / wsec, 0.0, 1.0))
                self.acc[1] = f32(clampf((self.f_on_total - self.anchor_f_on) / wsec, 0.0, 1.0))
            dev_avg = self.acc[2]
            self.learn(rate)
            self.update_centre(dev_avg, wmin)
            self.acc = [f32(0)] * 4; self.acc_n = 0
            self.anchor_t = t; self.anchor_x = x; self.anchor_ms = now
            self.anchor_h_on = self.h_on_total; self.anchor_f_on = self.f_on_total

        th = self.theta
        kh = th[0]; kf = -th[1]
        pslot = int((minute_of_day + float(self.rt)) % 1440) // 15
        pl = self.light_slot[pslot] if self.light_w[pslot] >= 2 else lux_norm
        ref_now = self.t_ref if self.v != 'old' else OLD_TEMP_REF
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
        if self.relay:
            rate_now = kh * f32(self.recent_heat()) + th[1] * f32(self.recent_fan()) + passive_raw
        else:
            rate_now = kh * self.heater + th[1] * self.fan + passive_raw
        self.predicted = float(t + rate_now * 15)


# --- plants ------------------------------------------------------------------
EVAP_FH = {COVER_OPEN: -0.21, COVER_LID: -0.08, COVER_EVAP: -0.03, COVER_UNKNOWN: -0.08}
PUMP_FH = 0.05


def plant_for(kind, tau, cover=None, cabinet=None):
    """True tank. 75: 300 W into 226 kg (the 2026-09-29 and 10-07 full-power
    steps, 1.9-2.1 degF/h), restart-on-edge slow_pwm. nano: 150 W into
    ~51 kg, plain slow_pwm, cabinet."""
    if kind == '75':
        cover = COVER_OPEN if cover is None else cover
        return dict(tau=tau, kh=300 / (226 * CP_WATER) * 60, kf=2.0 / CMIN_TO_FH, kl=0.25 / CMIN_TO_FH,
                    c0=(EVAP_FH[cover] + PUMP_FH) / CMIN_TO_FH, setpoint_f=77.0, offset_b=0.15,
                    edge_restart=True, cabinet=None, cover=cover)
    cover = COVER_LID if cover is None else cover
    return dict(tau=tau, kh=150 / (51 * CP_WATER) * 60, kf=3.0 / CMIN_TO_FH, kl=0.6 / CMIN_TO_FH,
                c0=(EVAP_FH[cover] + PUMP_FH) / CMIN_TO_FH, setpoint_f=74.5, offset_b=0.3,
                edge_restart=False, cabinet=cabinet, cover=cover)


PHYS_75 = (75.0, 62.0, 300.0, COVER_OPEN, PLACE_ROOM)
PHYS_NANO = (16.0, 0.0, 150.0, COVER_LID, PLACE_CABINET)

OFFICE_F = ((0, 71.8), (180, 71.6), (360, 71.4), (540, 73.8), (720, 73.5), (910, 75.0),
            (1080, 73.0), (1260, 71.8), (1440, 71.8))


def office_room_f(minute_of_day):
    for (m0, v0), (m1, v1) in zip(OFFICE_F, OFFICE_F[1:]):
        if m0 <= minute_of_day <= m1:
            return v0 + (v1 - v0) * (minute_of_day - m0) / (m1 - m0)
    return OFFICE_F[-1][1]


def load_history():
    rows = []
    with open(DATA) as fh:
        for line in fh:
            if line.startswith('#') or line.startswith('unix'):
                continue
            r = line.rstrip('\n').split(',')
            g = lambda s: float(s) if s else float('nan')
            rows.append([int(r[0])] + [g(s) for s in r[1:]])
    return rows


_REAL_ROOM = None


def real_room_f(tmin):
    """The office as Home Assistant recorded it, looped; starts at midnight
    local on 2026-09-28 so minute-of-day lines up with the lights."""
    global _REAL_ROOM
    if _REAL_ROOM is None:
        rows = load_history()
        vals = [r[5] for r in rows]
        last = vals[0]
        clean = []
        for v in vals:
            if not math.isnan(v):
                last = v
            clean.append(last)
        _REAL_ROOM = clean[48:]   # 09-27 20:00 + 4 h = 09-28 00:00 EDT
    i = int(tmin / 5) % len(_REAL_ROOM)
    return _REAL_ROOM[i]


def simulate(ctrl, plant, days, seed=1, swap_day=None, make_new=None, ambient_probe=False,
             sp_changes=(), room='real', room_step_day=None, start_day_metrics=2.0, events=()):
    rng = random.Random(seed)
    T = C(plant['setpoint_f'])
    cab = None
    off_a = 0.0
    off_b = C(32 + plant['offset_b']) - C(32)
    tick_ms = 30000
    pred_hist = {}
    rec = dict(t=[], health=[], stale=[], db=[], tau=[], bias=[], T=[], heater=[], pred_err=[], at_bound=[], c=[],
               kh=[])
    sp = C(plant['setpoint_f'])
    nticks = int(days * 2880)
    last_zb = None
    hp_start = 0.0; fp_start = 0.0
    prev_hd = 0.0
    tau = plant['tau']
    c0 = plant['c0']
    h_eff = 0.0         # heat actually reaching the water near the probes: 1 min lag behind the relay
    for k in range(nticks):
        now = (k + 1) * tick_ms
        tmin = now / 60000.0
        day = tmin / 1440
        mod = tmin % 1440
        for (d, f_new) in sp_changes:
            if abs(day - d) < 0.5 / 2880:
                ctrl.setpoint = f32(C(f_new)); ctrl.integral = f32(0); sp = C(f_new)
        for (d, fn) in events:
            if abs(day - d) < 0.5 / 2880:
                ctrl, tau, c0 = fn(ctrl, T, tau, c0)
        if swap_day is not None and abs(day - swap_day) < 0.5 / 2880:
            ctrl = make_new(ctrl)
        if room == 'real':
            room_f = real_room_f(tmin)
        elif room == 'flat':
            room_f = 73.5 + 0.1 * math.sin(tmin / 97.0)    # a quiet day: +/-0.1 degF, a Zigbee step at most
        else:
            room_f = office_room_f(mod)
        if room_step_day is not None and day >= room_step_day:
            room_f += 3
        room_c = C(room_f)
        if cab is None:
            cab = room_c + (C(32 + 2.0) - C(32) if plant['cabinet'] else 0.0)
        light = 1.0 if 540 <= mod < 960 else 0.0
        # the board's heater_output: restart both windows on a 0 -> >0 edge
        hd = float(ctrl.heater)
        ts0 = (now - tick_ms) / 1000.0
        if plant['edge_restart'] and prev_hd <= 0.0 < hd:
            hp_start = ts0
        prev_hd = hd
        h_on_s = f_on_s = 0.0
        for s in range(6):
            ts = ts0 + s * 5
            while ts - hp_start >= 900:
                hp_start += 900
            while ts - fp_start >= 900:
                fp_start += 900
            h_on = 1.0 if hd * 900 > ts - hp_start else 0.0
            f_on = 1.0 if float(ctrl.fan) * 900 > ts - fp_start else 0.0
            h_on_s += 5 * h_on; f_on_s += 5 * f_on
            if plant['cabinet']:
                # cabinet air: small heat capacity between tank and room.
                # tau here is tank -> cabinet; the cabinet sheds to the room
                # through UA_cab = cabinet['ua_ratio'] * UA_tank.
                ua_t = 1.0 / tau            # per minute, in tank-capacity units
                ua_c = plant['cabinet']['ua_ratio'] * ua_t
                cap_c = plant['cabinet']['cap_ratio']
                air = cab
                dcab = (ua_t * (T - air) - ua_c * (air - room_c)) / cap_c
                cab += dcab * 5 / 60.0
            else:
                air = room_c
            h_eff += (h_on - h_eff) * 5 / 60.0
            dT = plant['kh'] * h_eff - plant['kf'] * f_on - (T - air) / tau + plant['kl'] * light + c0
            T += dT * 5 / 60.0
        q = lambda v: round(v / 0.0625) * 0.0625
        ta = f32(q(T + off_a + rng.gauss(0, 0.01)))
        tb = f32(q(T + off_b + rng.gauss(0, 0.01)))
        reported = False
        if ambient_probe:
            zq = round((room_c + 0.1 + rng.gauss(0, 0.03)) / 0.2) * 0.2
            if zq != last_zb:
                last_zb = zq
                reported = True
        amb = f32(last_zb) if (ambient_probe and last_zb is not None) else float('nan')
        ctrl.update(now, mod, ta, tb, light * 3000.0 * 0.9, amb, reported, h_on_s, f_on_s)
        pred_hist[k + 30] = ctrl.predicted
        if k in pred_hist:
            rec['pred_err'].append((day, F(pred_hist.pop(k)) - F(T)))
        if k % 10 == 0:
            rec['t'].append(day); rec['health'].append(ctrl.health()); rec['stale'].append(float(ctrl.stale))
            rec['db'].append(float(ctrl.deadband())); rec['tau'].append(ctrl.tau()); rec['bias'].append(float(ctrl.bias))
            rec['T'].append((day, F(T) - F(sp))); rec['heater'].append(h_on_s / 30.0)
            rec['at_bound'].append(ctrl.at_bound()[2])
            rec['c'].append(float(ctrl.theta[4])); rec['kh'].append(float(ctrl.theta[0]))
    return ctrl, rec


def summarize(rec, days, start=2.0, true_tau=None):
    idx = [i for i, t in enumerate(rec['t']) if t >= start]
    h = [rec['health'][i] for i in idx]
    pe = [e for (d, e) in rec['pred_err'] if d >= start]
    terr = [e for (d, e) in rec['T'] if d >= start]
    last = [i for i, t in enumerate(rec['t']) if t >= days - 2]
    tau2 = next((rec['tau'][i] for i, t in enumerate(rec['t']) if t >= start), float('nan'))
    taus = [rec['tau'][i] for i in idx]
    return dict(
        health_min=100 * min(h), health_mean=100 * sum(h) / len(h),
        pred_rms=math.sqrt(sum(e * e for e in pe) / len(pe)),
        ctrl_rms=math.sqrt(sum(e * e for e in terr) / len(terr)),
        bias_last=sum(rec['bias'][i] for i in last) / len(last) * CMIN_TO_FH,
        db=rec['db'][-1] * CMIN_TO_FH,
        tau2=tau2, tau_end=rec['tau'][-1], tau_min=min(taus), tau_max=max(taus),
        kh_end=rec['kh'][-1] * CMIN_TO_FH,
        ka_pinned_pct=100 * sum(1 for i in idx if rec['at_bound'][i]) / len(idx),
        true_tau=true_tau,
    )


HEADER = ("scenario                              hMin% hMean% pred15  ctrlRMS  bias  dband  tau@start tau_end "
          "tau range    kh_end  ka@bnd%\n"
          "                                      (after day 2)    degF    degF  degF/h degF/h   min    min     "
          "min          degF/h")


def row(label, s):
    tt = f" (true {s['true_tau']:.0f})" if s.get('true_tau') else ''
    print(f"{label:37s} {s['health_min']:5.0f} {s['health_mean']:6.1f} {s['pred_rms']:6.3f} {s['ctrl_rms']:7.3f}"
          f" {s['bias_last']:+6.2f} {s['db']:5.2f} {s['tau2']:8.0f} {s['tau_end']:7.0f} {s['tau_min']:6.0f}-"
          f"{s['tau_max']:<6.0f} {s['kh_end']:6.2f} {s['ka_pinned_pct']:6.0f}{tt}")


def selftest():
    c = Controller('new', 77.0, phys=PHYS_75)
    c.t_ref = f32(24.0)
    c.theta = [f32(0.018), f32(-0.02), f32(-0.0012), f32(0.003), f32(-0.01)]
    before = [c.theta[2] * (T - c.t_ref) + c.theta[4] for T in (f32(22.0), f32(25.0), f32(28.0))]
    c.rebase(f32(25.0))
    after = [c.theta[2] * (T - c.t_ref) + c.theta[4] for T in (f32(22.0), f32(25.0), f32(28.0))]
    assert all(abs(float(a - b)) < 1e-7 for a, b in zip(before, after)), (before, after)
    # a physics reset keeps the prediction at the current water temperature
    t_now = f32(25.3)
    p0 = c.theta[2] * (t_now - c.t_ref) + c.theta[4]
    c.theta[2] = f32(-0.0002)
    p0 = c.theta[2] * (t_now - c.t_ref) + c.theta[4]
    c.reset_param(2, t_now, 0.0)
    p1 = c.theta[2] * (t_now - c.t_ref) + c.theta[4]
    assert abs(float(p1 - p0)) < 1e-7, (p0, p1)
    c.theta[2] = f32(-0.00001)
    c.P[2][4] = c.P[4][2] = f32(-5e-5)
    c.project_bounds()
    assert c.theta[2] == -c.ka_lo and c.P[2][4] == 0 and c.P[4][2] == 0
    print("selftest: rebase invariant, physics reset keeps the prediction, projection decouples -- ok")


def print_bands():
    print("Physics bands (time constant = m*c/UA; see apply_physics_):")
    for name, ph in (("75 gal, 62 gal water, 300 W", (75, 62, 300)), ("nano 16 gal, 150 W", (16, 0, 150))):
        for cover, cn in ((COVER_OPEN, 'open top'), (COVER_LID, 'lid'), (COVER_EVAP, 'lid+evap cover'),
                          (COVER_UNKNOWN, 'unknown')):
            for pl, pn in ((PLACE_ROOM, 'room'), (PLACE_CABINET, 'cabinet')):
                p = physics(ph[0], ph[1], ph[2], cover, pl)
                print(f"  {name:30s} {cn:15s} {pn:8s} tau {1 / p['ka_max']:5.0f}-{1 / p['ka_min']:5.0f} min,"
                      f" prior {1 / p['ka_prior']:5.0f}  (UA {p['ua_lo']:.1f}-{p['ua_hi']:.1f} W/K)"
                      f"  kh {p['kh'] * CMIN_TO_FH:.2f} degF/h")


# --- measurement from the real history ------------------------------------
def measure():
    rows = load_history()
    t = np.array([r[0] for r in rows], float)
    L, R, cmd, on, room, lux, fan = (np.array([r[i] for r in rows]) for i in range(1, 8))
    T = (L + R) / 2
    u_on, u_cmd = on / 100, cmd / 100
    kh_phys = 300 / (234.7 * CP_WATER) * 3600 * 9 / 5    # degF/h at 100%
    print(f"history: {len(rows)} 5 min rows; mean commanded heater {np.nanmean(u_cmd) * 100:.1f}%,"
          f" relays actually closed {np.nanmean(u_on) * 100:.1f}% (x{np.nanmean(u_on) / np.nanmean(u_cmd):.2f})")
    # 1. heater gain from the two full-power steps
    import datetime as _dt
    tz = _dt.timezone(_dt.timedelta(hours=-4))
    at = lambda s: _dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=tz).timestamp()
    for lab, a, b in (("2026-09-29 setpoint 76->77", at("2026-09-29 10:35"), at("2026-09-29 11:00")),
                      ("2026-10-07 water change", at("2026-10-07 11:10"), at("2026-10-07 11:45"))):
        i = np.searchsorted(t, a); j = np.searchsorted(t, b)
        rate = np.polyfit((t[i:j + 1] - t[i]) / 3600, T[i:j + 1], 1)[0]
        print(f"  step {lab}: {rate:.2f} degF/h at {np.nanmean(u_on[i:j]) * 100:.0f}% delivered"
              f" (physics, 300 W into 62 gal: {kh_phys:.2f})")
    # 2. loss from the heat balance: kh*u_delivered - dT/dt = ka*(T - room) - kl*L - c0
    bad = np.isnan(T) | np.isnan(u_on) | np.isnan(room) | np.isnan(lux) | (np.nan_to_num(fan) > 0)
    for a, b in ((at("2026-09-27 18:00"), at("2026-09-28 01:00")),       # fan run, setpoint 78 -> 76
                 (at("2026-09-29 10:30"), at("2026-09-29 11:30")),       # setpoint 76 -> 77
                 (at("2026-10-07 10:50"), at("2026-10-07 13:00"))):      # water change
        bad |= (t >= a) & (t < b)

    def windows(W, night):
        out = []
        for i in range(0, len(t) - W, W):
            sl = slice(i, i + W + 1)
            if bad[sl].any() or (night and np.nanmax(lux[i:i + W]) > 20):
                continue
            rate = np.polyfit(np.arange(W + 1) / 12.0, T[sl], 1)[0]
            day = int((t[i] - t[0] - 10 * 3600) // 86400)
            out.append((day, u_on[i:i + W].mean(), (T[i:i + W] - room[i:i + W]).mean(), lux[i:i + W].mean() / 1000,
                        rate))
        return np.array(out)

    def solve(w, night, kh):
        y = kh * w[:, 1] - w[:, 4]
        cols = [w[:, 2], -np.ones(len(w))] if night else [w[:, 2], -w[:, 3], -np.ones(len(w))]
        return np.linalg.lstsq(np.c_[tuple(cols)], y, rcond=None)[0]

    rnd = random.Random(1)
    print("  heat balance, kh fixed by the steps, 1 h windows, bootstrap over days:")
    res = {}
    for night in (True, False):
        for kh in (kh_phys * 0.9, kh_phys, kh_phys * 1.1):
            w = windows(12, night)
            b = solve(w, night, kh)
            days = sorted(set(w[:, 0]))
            bs = []
            for _ in range(400):
                pick = [rnd.choice(days) for _ in days]
                ww = np.concatenate([w[w[:, 0] == d] for d in pick])
                bs.append(solve(ww, night, kh)[0])
            lo, hi = np.percentile(bs, [5, 95])
            res[(night, round(kh, 2))] = 60 / b[0]
            print(f"    {'nights  ' if night else 'all day '} kh={kh:.2f}: ka={b[0]:.4f}/h  tau={60 / b[0]:4.0f} min"
                  f"  90% CI {60 / hi:4.0f}-{60 / lo:4.0f}   c0={b[-1]:+.3f} degF/h"
                  + (f"  light {b[1]:.2f} degF/h per klx" if not night else ''))
    # the same balance, but crediting the heater with COMMANDED duty -- what
    # the firmware learned from until now
    print("  (crediting commanded instead of delivered duty is what made the controller's kh"
          f" ~{np.nanmean(u_on) / np.nanmean(u_cmd):.1f}x too high)")
    return res


# --- real-data replay -----------------------------------------------------
def replay(phys=PHYS_75, centre=True, verbose=True):
    """Feed the 75's real 5-minute history to NEW's learn_(): rate from the
    probe means, delivered heater fraction, room from the Office Multi-Sensor,
    lux. The loop itself is not re-run -- the controller of the day made the
    decisions -- so this measures what the estimator concludes from what
    actually happened."""
    rows = [r for r in load_history() if r[0] >= 1790575200]   # from 09-28 01:00 EDT, after the 78 -> 76 descent
    c = Controller('new', 77.0, phys=phys, ambient=True, centre=centre)
    c.ref_mode = REF_AMBIENT
    prev = None
    out = []
    for r in rows:
        unix, L, R, cmd, on, room, lux, fan = r
        if any(math.isnan(v) for v in (L, R, on, room, lux)) or (not math.isnan(fan) and fan > 0):
            prev = None
            continue
        T = f32(C((L + R) / 2)); a = f32(C(room))
        if prev is None:
            c.t_ref = f32(a + (T - a))
            c.centre_off = f32(T - a)
            prev = (T, a, on)
            continue
        # the room moves the regressor; only the centre is rebased
        c.t_ref = f32(a + c.centre_off)
        rate = f32((T - prev[0]) / 5.0)
        dev = f32((T + prev[0]) / 2 - c.t_ref)
        # the rate runs from the middle of the previous bin to the middle of
        # this one, so the heat that drove it is half of each bin's
        c.acc = [f32((on + prev[2]) / 200), f32(0), dev, f32(clampf(lux / 3000.0, 0, 1.5))]
        c.acc_n = 1
        if abs(float(rate)) < 0.05:          # the water change and the setpoint step are not drift
            c.learn(rate)
            c.update_centre(dev, 5.0)
        prev = (T, a, on)
        out.append((unix, c.tau(), float(c.theta[0]) * CMIN_TO_FH, float(c.theta[4]) * CMIN_TO_FH, c.health()))
    if verbose:
        import datetime as _dt
        tz = _dt.timezone(_dt.timedelta(hours=-4))
        print("  replay of the real history through NEW (ambient mode, 5 min steps):")
        for k in range(0, len(out), len(out) // 12):
            u, tau, kh, cc, h = out[k]
            print(f"    {_dt.datetime.fromtimestamp(u, tz):%m-%d %H:%M}  tau {tau:5.0f} min  kh {kh:4.2f} degF/h"
                  f"  c {cc:+.3f} degF/h  health {h * 100:3.0f}%")
        u, tau, kh, cc, h = out[-1]
        taus = [o[1] for o in out[len(out) // 3:]]
        print(f"    end: tau {tau:.0f} min (last two thirds {min(taus):.0f}-{max(taus):.0f}), kh {kh:.2f} degF/h,"
              f" pinned {100 * sum(1 for o in out if o[1] >= 1 / float(c.ka_lo) - 1 or o[1] <= 1 / float(c.ka_hi) + 1) / len(out):.0f}%")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--days', type=float, default=14.0)
    ap.add_argument('--measure', action='store_true')
    ap.add_argument('--replay', action='store_true')
    a = ap.parse_args()
    if a.measure:
        measure()
        return
    if a.replay:
        replay()
        return
    days = 6.0 if a.quick else a.days
    selftest()
    print_bands()
    print(HEADER)
    zig = dict(ambient=True)
    # 75: measured ~810 min open top. 150/300/400 are the brief's values -- outside what 62 gal can do
    for tau in (800, 1000, 400, 300, 150):
        p = plant_for('75', tau)
        for amb in (True, False):
            ctrl = Controller('new', p['setpoint_f'], phys=PHYS_75, ambient=amb)
            _, rec = simulate(ctrl, p, days, ambient_probe=amb)
            row(f"75 tau={tau} NEW{'+zigbee' if amb else ''}", summarize(rec, days, true_tau=tau))
    # a quiet room all day, every day: nothing excites ka, so it must stay put
    p = plant_for("75", 800)
    _, rec = simulate(Controller('new', 77.0, phys=PHYS_75, ambient=True), p, days, ambient_probe=True, room='flat')
    row("75 tau=800 NEW+zigbee quiet room", summarize(rec, days, true_tau=800))
    _, rec = simulate(Controller('prev', 77.0, max_tau=6000, ambient=True), p, days, ambient_probe=True, room='flat')
    row("75 tau=800 PREV+zigbee quiet room", summarize(rec, days, true_tau=800))
    # the brief's short time constants with no physics configured (legacy band)
    for tau in (150, 300, 400):
        p = plant_for("75", tau)
        _, rec = simulate(Controller('new', 77.0, max_tau=6000, ambient=True), p, days, ambient_probe=True)
        row(f"75 tau={tau} NEW no-physics +zigbee", summarize(rec, days, true_tau=tau))
    for tau in (800,):
        p = plant_for('75', tau)
        for amb in (True, False):
            _, rec = simulate(Controller('prev', p['setpoint_f'], max_tau=6000, ambient=amb), p, days,
                              ambient_probe=amb)
            row(f"75 tau={tau} PREV(201f2c8){'+zig' if amb else ''}", summarize(rec, days, true_tau=tau))
    # lids go on: open -> lid on day 5, true tau 800 -> 1100, evaporation 0.21 -> 0.08 degF/h
    p = plant_for("75", 800)

    def lid_on(ctrl, T, tau, c0):
        ctrl.set_physics((75.0, 62.0, 300.0, COVER_LID, PLACE_ROOM), ctrl.last_t)
        return ctrl, 1100, (EVAP_FH[COVER_LID] + PUMP_FH) / CMIN_TO_FH
    _, rec = simulate(Controller('new', 77.0, phys=PHYS_75, ambient=True), p, days + 6, ambient_probe=True,
                      events=((5.0, lid_on),))
    s = summarize(rec, days + 6, start=5.0 + 2, true_tau=1100)
    row("75 open->lid d5 +zigbee (after d7)", s)
    # the 201f2c8 model as the 75 left it (ka pinned 6000, kh learned on
    # commanded duty) flashed with this firmware on day 4
    def flash(old):
        n = Controller('new', 77.0, phys=PHYS_75, ambient=True)
        n.migrate_prev(old)
        n.anchor_t = float('nan')
        return n
    old = Controller('prev', 77.0, max_tau=6000, ambient=True)
    _, rec = simulate(old, p, days + 4, ambient_probe=True, swap_day=4.0, make_new=flash)
    row("75 PREV->flash d4 +zigbee (after d6)", summarize(rec, days + 4, start=6.0, true_tau=800))
    # nano: 16 gal, lid, in a closed stand, 150 W, no room sensor
    for tau_tank, cab_ratio in ((900, 1.5), (600, 3.0), (1500, 1.0)):
        p = plant_for('nano', tau_tank, cabinet=dict(ua_ratio=cab_ratio, cap_ratio=0.05))
        eff = tau_tank * (1 + 1 / cab_ratio)
        _, rec = simulate(Controller('new', p['setpoint_f'], phys=PHYS_NANO, cross=False), p, days)
        row(f"nano cab tau_t={tau_tank} r={cab_ratio} NEW", summarize(rec, days, true_tau=eff))
    # the warned-against case: a room sensor outside the cabinet
    p = plant_for('nano', 900, cabinet=dict(ua_ratio=1.5, cap_ratio=0.05))
    _, rec = simulate(Controller('new', p['setpoint_f'], phys=PHYS_NANO, cross=False, ambient=True), p, days,
                      ambient_probe=True)
    row("nano cab tau_t=900 NEW+room sensor", summarize(rec, days, true_tau=1500))
    _, rec = simulate(Controller('prev', p['setpoint_f'], cross=False), p, days)
    row("nano cab tau_t=900 PREV", summarize(rec, days, true_tau=1500))
    # setpoint step 77 -> 79 -> 77 without a room sensor: an excursion ka can learn from
    p = plant_for("75", 800)
    _, rec = simulate(Controller('new', 77.0, phys=PHYS_75), p, days, sp_changes=((3.0, 79.0), (4.5, 77.0)))
    row("75 tau=800 NEW sp 77/79/77", summarize(rec, days, true_tau=800))
    replay()


if __name__ == '__main__':
    main()
