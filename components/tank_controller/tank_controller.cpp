#include "tank_controller.h"
#include "esphome/core/log.h"
#include "esphome/core/hal.h"
#include <cmath>

namespace esphome {
namespace tank_controller {

static const char *const TAG = "tank_controller";

// Learn from a temperature difference taken over this long, not from
// tick-to-tick differences -- see the note in the header.
static const uint32_t LEARN_WINDOW_MS = 300000;  // 5 minutes
// If the probe goes away for longer than this, stop controlling.
static const uint32_t SENSOR_TIMEOUT_MS = 120000;
static const uint32_t SAVE_INTERVAL_MS = 1800000;  // 30 minutes

// A gap longer than this between valid readings means the windows that
// span it are not measuring anything real.
static const uint32_t DISCONTINUITY_MS = 90000;    // 1.5 min -- one missed read
static const uint32_t HISTORY_WIPE_MS = 300000;    // 5 min

// Heater at full for this long with less than this much rise means it is
// not actually heating: unplugged, failed, or a dead relay channel.
//
// 45 -> 20 minutes on 2026-09-14. This is also the last line of defence
// against a probe that reads a steady wrong number: the rate guards
// reject a jump, but a value that arrives after a probe outage is
// re-anchored on, and if it is bogus AND cold the heater runs flat out
// until this trips. At 45 minutes that was +2.4 degF of real heat into
// the tank; at 20 it is about +1. A genuine cold tank at full power
// rises ~1 degF in 20 minutes, twenty times the 0.05 degC bar, so there
// is no false trip to trade against.
static const uint32_t HEAT_STALL_MS = 1200000;     // 20 minutes
static const float HEAT_STALL_RISE = 0.05f;        // degC

// A reading accepted across a gap -- boot, or a probe outage long enough
// that the rate guard stood down -- is the one reading nothing else has
// vouched for. For this long afterwards the heater is capped, so if that
// reading was wrong the damage is bounded while the stall detector and
// the cross-check catch up. Half power for ten minutes costs a genuinely
// cold tank a few minutes of recovery; it caps a bogus one at ~+0.4 degF.
static const uint32_t REANCHOR_SETTLE_MS = 600000;  // 10 minutes
static const float REANCHOR_HEAT_CAP = 0.5f;

// Two probes that disagree by more than the band for this long mean one of
// them is lying and there is no way to know which. Heater off is the only
// safe answer to that. Five minutes rides through a single glitchy
// sample on either side without tripping.
static const uint32_t DISAGREE_MS = 300000;         // 5 minutes
// 15 not 5: a two-heater 48" tank carries a real gradient between its
// probes, and its band is set wide enough that only a lying probe can
// cross it. The one-probe boards keep their 2.0 default regardless.
static const float DISAGREE_BAND_MAX_F = 15.0f;
static const float DISAGREE_BAND_MAX = DISAGREE_BAND_MAX_F * 5.0f / 9.0f;

// Fan equivalent. The bar is deliberately low -- merely "did not fall at
// all" -- because passive loss alone should drop this tank well over a
// degF in 45 minutes. If the water is flat or rising while the fan is
// commanded wide open, something is wrong with the fan, the relay
// channel, or the outlet. It cannot detect a weak fan, only an absent
// one; the learned fan gain is the sensitive measure.
static const uint32_t FAN_STALL_MS = 2700000;      // 45 minutes
static const float FAN_STALL_FALL = 0.05f;         // degC

// Residual EMA weight. Feeds the Model Bias diagnostic only -- see the
// comment on integral authority below for why this is reported and not
// acted on.
static const float BIAS_EMA_W = 0.2f;

// ---------------------------------------------------------------------
// Model health: does this model still describe this tank?
// ---------------------------------------------------------------------
// get_confidence() counts learning steps. It only ever rises, so a model
// that has seen a day of data is trusted completely and permanently --
// including after the tank physically changes. That happened here: a
// canister filter added a continuous heat load, and the controller went
// on predicting a falling tank, at 100% confidence, while it sat 0.9 degF
// above setpoint with the integral capped too low to overrule it.
//
// The deadband is the residual below which a persistent error is just
// sensor quantisation -- not evidence of anything, the mistake an earlier
// version of this file made by acting on a single drift sample. It is now
// computed, not fixed: health_deadband_().
//
// STALE_SCALE is how much sustained one-directional error it takes to
// stop believing the model entirely. 0.02 degC/min is 2.2 degF/h, which
// is roughly the whole cooling authority of the fan: if the model is
// wrong by that much, it is not describing this tank.
// Both were set far too tight on the first attempt, and the tank showed it
// immediately: a residual of 0.046 degC/min (4.96 degF/h) is normal while
// RLS is converging, and the original 0.020 scale called that a worthless
// model. Health floored at 0 and stayed there.
//
// The deadband was then the single-sample quantisation floor, 1.35 degF/h;
// it is now measured against the EMA's own noise -- see "Health against
// the measured noise floor" below. Scale is 0.05 degC/min (5.4 degF/h) --
// more than twice the fan's entire authority, so health only reaches zero
// when the model is wrong by more than the actuators could correct even in
// principle.
static const float STALE_SCALE = 0.050f;
// A slow EMA, separate from bias_. bias_ uses BIAS_EMA_W = 0.2 -- about a
// five sample memory -- which is right for a dashboard reading and far too
// jumpy to gate control authority on. This one averages over roughly fifty
// steps, so a single disturbed reading cannot swing the feedforward.
static const float STALE_EMA_W = 0.02f;
// Per-step covariance re-inflation while the model looks stale. RLS gain
// shrinks as P converges, which is right for a fixed plant and wrong for
// one that just changed -- by the time the tank changes, P is small and
// the correction crawls. 2% per step recovers the prior covariance in a
// couple of hundred steps, fast enough to matter and slow enough not to
// destabilise a model that is merely being rained on by noise.
static const float P_REINFLATE = 1.02f;
// Below this, phi' P phi says the step carries no usable information: the
// actuators are idle and the tank is sitting where it was. Sized against an
// idle regressor with P at the prior, which lands near 1e-5, versus a step
// with the heater or fan actually running, which is an order of magnitude
// above it. It used to gate the forgetting factor; with that gone it gates
// only the stale re-inflation, so P is re-opened on steps that can actually
// use the gain, not on idle ones.
//
// Measured over the EXCITATION regressors only -- heater, fan, loss, light
// -- not the constant. c's variance is now deliberately large (it tracks
// the room, see Q), and its regressor is 1 on every step, so counting it
// would call every idle step informative.
static const float INFO_MIN = 5e-5f;

// Ceiling on what the integral term alone may command, as a fraction of
// heater duty. See the clamp for why this is not a fixed rate.
//
// 0.3 -> 0.5 on 2026-09-14. The 0.3 was sized against an overshoot that
// happened when a flat clamp let the integral outvote the measurement;
// since then the sign guard forbids heat above setpoint+0.1 F and the
// clearing below zeroes any positive integral the moment it does, so the
// integral cannot carry heat through setpoint any more and the overshoot
// that 0.3 guarded against is bounded by those instead (~0.2 F). What 0.3
// could NOT do was hold a steady load the model has not learned yet: the
// tank moved to the floor and lost the canister's heat, its passive loss
// went past 30% of heater authority, and it sat cold with the integral
// pinned while RLS caught up. Half the heater is enough headroom for any
// room this tank will sit in.
static const float INTEGRAL_AUTHORITY = 0.5f;

// Sign guard deadband. Inside it the feedforward is free to act
// predictively; outside it the measured error decides the direction.
//
// Written in Fahrenheit and converted once, like every other number a
// human sets or reads in this project. Celsius survives below this line
// only because the model's priors and clamps are tuned in degC/min --
// it is an implementation detail and must not reach a log line, a sensor
// or a screen.
static const float GUARD_DEADBAND_F = 0.1f;
static const float GUARD_DEADBAND = GUARD_DEADBAND_F * 5.0f / 9.0f;

// Readings outside this window are not temperatures, they are faults, and
// they take the no-probe path (heater off after SENSOR_TIMEOUT_MS) rather
// than the under/over-temperature cutouts. The cutouts assume the number
// is real; these bounds are where that assumption stops. A DS18B20 with a
// marginal data line reads all zeros, and CRC(0...0) == 0 passes, so the
// probe delivers a perfectly valid 0.0 C. On 2026-09-13 that ran the
// heater at 100% for 25 minutes into a 74.5 F tank, because 0 C is below
// min_temperature and that branch heats. sensors.yaml converts the two
// known signatures (0 C, 85 C power-on) to NaN before they get here; this
// is the backstop for any board that does not, and for whatever the next
// bogus number turns out to be. 41-140 F: no aquarium on earth is outside it.
static const float PLAUSIBLE_MIN_F = 41.0f;
static const float PLAUSIBLE_MAX_F = 140.0f;
static const float PLAUSIBLE_MIN = (PLAUSIBLE_MIN_F - 32.0f) * 5.0f / 9.0f;
static const float PLAUSIBLE_MAX = (PLAUSIBLE_MAX_F - 32.0f) * 5.0f / 9.0f;

// The window above was not enough. The night after it went in, the same
// marginal bus produced 11.8 C -- exactly half of the 23.6 C tank, a
// one-bit slip in the read -- which is a perfectly plausible temperature
// for some aquarium and sat inside the window, below min_temperature, and
// drove the heater to 100% for 2.5 minutes (2026-09-14 03:49). No fixed
// window can tell a corrupted 53 F from a real one. What can is the rate:
// this tank moves at most ~3 degF per HOUR flat out, so a reading more
// than a degree away from the one 30 s earlier is not the water. Only
// judged against a RECENT reading -- after DISCONTINUITY_MS with nothing
// valid the guard stands down and accepts whatever arrives, so a genuine
// step across a probe outage (a water change with the probe out) is
// re-anchored on rather than rejected forever. sensors.yaml applies the
// same idea per 10 s sample; this is the backstop for boards that do not.
static const float MAX_STEP_F = 1.8f;
static const float MAX_STEP = MAX_STEP_F * 5.0f / 9.0f;

// How far above setpoint the tank must sit before the fan is worth running.
// Wider than GUARD_DEADBAND, and asymmetric with the heater on purpose:
// running an evaporative fan against a small warm excursion costs water
// and risks pushing the tank into the cool bands for nothing.
//
// This is now a runtime setting (fan_deadband_, the "Fan Deadband" number)
// and this is only its first-boot default; the value is persisted like the
// setpoint. It was a fixed 0.5 degF, justified by the tank shedding
// "roughly 3.3 degF/h all by itself" so that warm excursions self-correct.
// That figure is stale: with the mesh lid the tank measured 0.23 degF/h
// unaided (2026-09-12, 0.7 degF in three hours after the light ramped
// down), and the fixed band showed up in the data as a flat 0.5 degF
// daytime plateau -- the tank rose to exactly setpoint+0.5 and the fan
// held it there, the whole light period, every day. Half of the 0.9 degF
// daily swing was this constant.
//
// The first-boot default itself lives with the other config defaults in
// __init__.py (fan_deadband: 0.25). Only the ceiling is enforced here, in
// degF for the human and converted once; see GUARD_DEADBAND_F.
static const float FAN_DEADBAND_MAX_F = 2.0f;
static const float FAN_DEADBAND_MAX = FAN_DEADBAND_MAX_F * 5.0f / 9.0f;

// There is no forgetting factor any more. It was 0.9995, applied on
// informative steps only, and it was the crude, undirected form of what Q
// (below) now does deliberately: lambda < 1 divides ALL of P by lambda,
// including directions the step did not excite, which is windup. With c and
// ka given explicit process noise there was nothing left for it to do but
// that -- the simulation (tools/thermal_model_sim.py) showed it parking the
// heater and fan variances at their P_PRIOR*10 cap whenever the ambient
// probe made every step informative. A step change in the hardware (a
// heater dying) is caught by the stale-model re-inflation instead, which
// fires on evidence rather than on the clock.

// Physically plausible bounds. Constraining the fit is what keeps the
// closed-loop identification from running off into nonsense when the
// controller isn't exciting the system much.
//
// theta[4] (c) is the drift at T_ref with nothing running. With T_ref at
// the setpoint that is the drift the tank shows where it is held, and
// +/-0.15 degC/min (+/-16 degF/h) brackets any room this tank will sit in.
// With T_ref at the room (ambient probe) it is the tank's own heat --
// pumps, ballast -- and the same bound is generous.
//
// theta[1] (fan) is bounded AWAY from zero for the same reason theta[0]
// (heater) has a floor of 0.002: the control law divides by the gain, so a
// gain free to approach zero turns any cooling demand into a saturated
// output. A fan that does nothing at all is not a fan.
//
// theta[2]'s upper bound (-ka closest to zero, i.e. the SLOWEST tank) is
// the one entry in THETA_MAX that is not used as written: it is the board's
// max_time_constant, held as ka_min_ (see theta_max_()). -0.001 here is
// the 1000 min default sized for the ~10 gal nano.
//
// History, because it explains everything below: on 2026-10-12 the 75's
// ka sat pinned on its bound for days with Model Bias +2.5..+3.0 degF/h and
// health ~73%. Raising the bound to 6000 min (bbf4b6f) only moved the pin
// -- Tank Time Constant read EXACTLY 6000 within two days, bias back at
// +2.6 degF/h, health 78%. tools/thermal_model_sim.py reproduces that to
// the decimal from the old code and shows the three faults that made it:
//
//   1. The loss regressor was (T - 24.0 C). The 75 is held at 77.0 degF
//      (25.0 C) +/- 0.05, so that regressor was 1.05 +/- 0.03 -- a copy of
//      the constant column. ka and c were interchangeable, and RLS split
//      each correction between them by covariance: P[2][2]*1.05^2 against
//      P[4][4] = 1e-4 against 1e-5, so ten times more of every correction
//      went into ka than into c. The data wanted a NEGATIVE ka (it is the
//      only way ka*1.05 can cancel the prior's 3 degF/h error in c), so ka
//      ran to its bound, wherever the bound was.
//   2. The bound was a plain clamp. It threw ka's share of each correction
//      away, while the covariance went on "knowing" the combination was
//      fitted, so the residual never closed.
//   3. c's covariance was 1e-5 and never grew -- lambda is held at 1 on
//      uninformative steps, correctly, to stop windup -- so c learned at
//      ~1e-5 of the residual per step: a 2.6 degF/h error would take
//      months. c could not track the room, ever.
//
// The fix is one for each: the reference is the operating point (fault 1,
// see "Where the model is centred"); bounds are enforced by a covariance-
// aware projection that moves the correction rather than discarding it
// (fault 2, project_bounds_()); and c is modelled as what it physically is,
// a quantity that drifts with an unmeasured room, by adding process noise
// to its covariance every step (fault 3, Q below).
static const float THETA_MIN[N_PARAMS] = {0.002f, -0.300f, -0.200f, 0.000f, -0.150f};
static const float THETA_MAX[N_PARAMS] = {0.300f, -0.002f, -0.001f, 0.050f, 0.150f};

// Starting guesses: a typical 100-200W heater in a tens-of-gallons tank.
// theta[4] carries the assumption that an unheated tank cools: -0.030
// degC/min is the ~3.3 degF/h the nano sheds unaided, measured. On a big
// tank it is wrong by a couple of degF/h, and that no longer matters --
// c now re-learns in hours (see Q), where it used to need months.
//
// theta[2] as written here is NOT used: ka's prior is fifteen times the
// board's floor, ka_min_ = 1/max_time_constant (theta_prior_()). At the
// 1000 min default that is exactly the -0.015 below (66.7 min) -- every
// board that keeps the default starts where it always did -- and on the
// 75's 6000 min it is 400 min instead of a nano's 67. A prior an order of
// magnitude inside the physical ceiling, scaled by the same tank-size
// judgement that set the ceiling.
static const float THETA_PRIOR[N_PARAMS] = {0.030f, -0.020f, -0.015f, 0.003f, -0.030f};

// ---------------------------------------------------------------------
// The drift: c as a random walk
// ---------------------------------------------------------------------
// Nothing in this model measures the room (unless an ambient probe is
// fitted). The room is the tank's real "heat drift" -- day against night,
// the house heating coming on in October, sun through the window behind
// the 75 -- and a model with fixed parameters is biased whenever it moves.
// At T_ref = setpoint, all of it lands in c. So c is not a constant to be
// converged on; it is a slowly wandering state to be tracked, and the
// textbook way to say that to RLS (a Kalman filter with a random-walk
// parameter) is to add process noise Q to its variance every step.
//
// P is in units of the measurement noise (RLS with a unit noise variance),
// and for a parameter observed every step the Riccati recursion
// P <- P - P^2/(1+P) + Q settles where P^2/(1+P) = Q. The gain is then
// K = P/(1+P). Choosing a tracking time of N steps (K = 1/N) gives
//     P_ss = 1/(N-1)      Q = 1/(N(N-1)).
// N = 24: two hours of 5 minute steps. Sizing it, both ways:
//   * fast enough: the office the 75 sits in swings ~3.5 degF a day and
//     rises 2.4 degF between 06:00 and 09:00. For a 1000 min tank that
//     moves the drift by 0.0013 degC/min over three hours; a two hour lag
//     on it is under 0.001 degC/min (0.1 degF/h), a fifth of one LSB of
//     the 5 minute rate. A +3 degF step (the heating season starting) is
//     tracked to 1/e in two hours and gone by the afternoon.
//   * slow enough: a gain of 1/24 averages the 5 minute rate's ~0.005
//     degC/min quantisation noise down to ~0.0007 degC/min (0.08 degF/h)
//     of jitter in c -- 0.02 degF over the 15 minute forecast.
// The same N with an ambient probe. A slower c was tried there (a day, so
// it could not soak up the room's swing before ka did) and the simulation
// said no: in closed loop the heater duty mirrors the room, so the room's
// swing is split between ka and kh, not handed to ka, and a sluggish c only
// left the error from that split in the residual (health ~88%, Tank Time
// Constant off by 3-5x). With c kept agile and ka given room to move
// (P_KA_AMBIENT), ka converged to within ~30% of the plant's time
// constant and the forecast matched setpoint mode.
//
// Q on the other parameters: zero for kh, kf and kl -- a heater's wattage
// does not drift, and when one fails the stale-model re-inflation below is
// the mechanism for that step change. A small Q on ka so its variance
// creeps back up between informative stretches: 1e-7 per step at the
// setpoint (excursions are rare; to the P_PRIOR*10 cap in ~2 months), 1e-6
// with an ambient probe (every day is informative there).
//
// How this sits with the anti-windup: Q inflates only the parameters it is
// given, and c is excited on every step by construction (its regressor is
// the literal 1), so the recursion above bounds it at P_ss; ka's variance
// is bounded by the P_PRIOR*10 cap in clamp_model_(). Nothing else grows.
// The informative-step test (which now only gates the stale re-inflation)
// ignores the constant column, or c's deliberately large variance would
// call every step informative.
static const float C_TRACK_STEPS = 24.0f;  // 2 h
static const float Q_C = 1.0f / (C_TRACK_STEPS * (C_TRACK_STEPS - 1.0f));
static const float Q_KA_SETPOINT = 1e-7f;
static const float Q_KA_AMBIENT = 1e-6f;

// Prior covariance -- how wrong we think the prior is, per parameter.
// c starts at its steady state, so a fresh (or migrated) model tracks at
// full speed from the first step. ka's 1e-4 is for setpoint mode, where it
// is barely observable and a looser value only lets it wander onto a bound
// (simulated on the nano: pinned at 1000 min half the time at 1e-2).
static const float P_PRIOR[N_PARAMS] = {1e-3f, 1e-3f, 1e-4f, 1e-5f, 1.0f / (C_TRACK_STEPS - 1.0f)};
// ka's variance in ambient mode, where the room's swing makes it
// observable. Raised to this on entry and returned to P_PRIOR[2] on exit,
// by scaling its row and column so P stays positive definite; see
// set_ka_variance_().
static const float P_KA_AMBIENT = 1e-2f;

// ---------------------------------------------------------------------
// Where the model is centred
// ---------------------------------------------------------------------
// The loss term is ka*(T - T_ref), and T_ref decides what c means and
// which of ka and c the data can see. A FIXED T_ref is only harmless while
// the tank lives on it: away from it, (T - T_ref) is a near-constant
// offset sitting beside the constant column, and the two are not
// separately identifiable (fault 1 above). So T_ref follows the operating
// point:
//
//   setpoint mode (no ambient probe, or it is not reporting): T_ref is the
//   ACTIVE setpoint -- the override while cycling, the owner's number
//   otherwise -- because that is where the controller holds the water.
//   (T - T_ref) is then just the control error: zero-mean, a tenth of a
//   degree on a steady day, and only large during a real excursion (a
//   setpoint move, a water change, a heater outage), which is precisely
//   the data that measures ka. c is the drift at the held temperature,
//   observed directly every five minutes.
//
//   Why the setpoint and not an EMA of the measured temperature: both
//   centre the regressor, but the setpoint moves only when someone moves
//   it, so c keeps one meaning between those moments and needs no
//   per-tick re-expression; an EMA would follow a heater outage down and
//   quietly re-define c in the middle of exactly the excursion ka should
//   be learned from.
//
//   ambient mode (a room sensor configured and passing every check in
//   ambient_usable_() for 10 minutes): T_ref is the room. The regressor is
//   no longer a near-constant: it carries the room's daily swing, so ka
//   becomes measurable from an ordinary day, and c shrinks to the tank's
//   own heat. The room is NOT rebased on as it moves -- that would hand c
//   the room's swing and starve ka of it; it is the regressor.
//
//   The room used is low-passed (AMBIENT_FILTER_MIN). The 75's source is
//   a Zigbee multi-sensor: 0.2 degC steps, reported on change, an hour or
//   two apart when the office is steady. Raw, every report is a 0.36 degF
//   step in T_ref -- to the model, a sudden heat event. Filtered over 20
//   minutes the staircase becomes the ramp the room actually made, and a
//   lidded tank's air film does not respond faster than that anyway.
//
// Changing T_ref in either mode, or switching modes, re-expresses c at the
// new reference so the prediction does not step:
//     -ka*(T - r) + c  ==  -ka*(T - r') + c'   =>   c' = c - ka*(r' - r)
// (theta[4] += theta[2]*(r' - r), theta[2] being -ka.) The covariance is
// carried through the same linear map, P' = A P A', so the certainty of
// the combination survives the move as well as its value. See rebase_().
//
// How long a reading stays good with no new one is per source --
// ambient_timeout in YAML, ambient_timeout_ms_ here: 10 minutes for a probe
// that reports every few seconds, hours for a report-on-change Zigbee
// sensor. A source that knows it has gone away (Zigbee availability
// "offline", MQTT disconnected) publishes NAN, which ends it at once.
//
// A source must pass every check continuously this long before the model
// moves onto it, so a flapping connection costs a re-expression per
// outage, not per tick. Leaving is immediate.
static const uint32_t AMBIENT_SETTLE_MS = 600000;    // 10 minutes
// Air in a room with an aquarium in it. Outside this it is a fault.
static const float AMBIENT_MIN_F = 40.0f;
static const float AMBIENT_MAX_F = 100.0f;
static const float AMBIENT_MIN = (AMBIENT_MIN_F - 32.0f) * 5.0f / 9.0f;
static const float AMBIENT_MAX = (AMBIENT_MAX_F - 32.0f) * 5.0f / 9.0f;
// A "room" reading within 0.2 degF of the water for three hours running is
// a probe that fell in the tank (or is taped to the glass), not air. Rooms
// do sit at tank temperature sometimes; then the ambient term carries
// nothing and the setpoint model loses nothing by taking over.
static const float SUBMERGED_BAND_F = 0.2f;
static const float SUBMERGED_BAND = SUBMERGED_BAND_F * 5.0f / 9.0f;
static const uint32_t SUBMERGED_MS = 3UL * 3600UL * 1000UL;
// Low-pass on the room reading before the model uses it; see above.
static const float AMBIENT_FILTER_MIN = 20.0f;

// ---------------------------------------------------------------------
// Learning from both probes
// ---------------------------------------------------------------------
// The control and cross-check probes are two independent DS18B20s, each
// quantised to 0.0625 degC. A 5 minute rate from one probe carries that
// LSB as noise (sigma ~0.0051 degC/min); averaging the two probes' rates
// halves its variance. Each probe's rate is taken against its own anchor,
// so their fixed offset -- up to 1.8 degF uncalibrated, and a real
// gradient on the 48" tank -- cancels and never reads as a rate.
//
// Averaged only when both readings are valid and inside the disagreement
// band at both ends of the window, AND the two probes saw the same change
// to within PAIR_RATE_TOL. That last test is what keeps a marginal cross-
// check bus from poisoning a step: it is not vetted by the control
// probe's rate guards, and a one-off half-degree glitch on it inside an
// 8 degF band would otherwise be learned as 0.1 degC/min of drift. When
// any test fails the step uses the control probe alone, as before.
//
// Learning only. The loop still regulates on the control probe: averaging
// in a probe that is not rate-guarded would put its faults straight into
// the heater, and on the 48" tank the average is a point between two
// heaters that nobody chose as the target.
static const float PAIR_RATE_TOL = 0.125f;  // degC over the window, 2 LSB

// ---------------------------------------------------------------------
// Health against the measured noise floor
// ---------------------------------------------------------------------
// The old fixed deadband (one LSB over a 5 minute window, 0.0125 degC/min
// == 1.35 degF/h) was sized against a SINGLE sample. Health is judged on
// a 50-step EMA of the signed residual, whose noise is far smaller: for a
// residual with spread sigma, the EMA's spread is sigma*sqrt(w/(2-w)),
// about 0.1*sigma at w = 0.02. Against that, 1.35 degF/h was a dozen
// standard deviations -- a model could be 1.3 degF/h wrong for ever and
// read 100%.
//
// So the deadband is HEALTH_Z standard deviations of the EMA, with sigma
// measured live (resid_var_, the residual's spread about its own mean)
// and floored at the quantisation limit, so a lucky quiet spell cannot
// make it hair-trigger: one DS18B20's 5 minute rate has sigma = LSB/
// sqrt(6)/5 min = 0.0051 degC/min, two probes averaged 0.0036. Ceiling at
// the old 0.0125, so a residual made noisy by disturbances cannot buy a
// biased model a clean bill of health. A healthy model's stale_ sits
// within the band and reads 100%; a real mismatch of a few tenths of a
// degF/h shows. STALE_SCALE is unchanged: health reaches zero only when the
// model is wrong by more than twice the fan's whole authority.
static const float HEALTH_Z = 4.0f;
static const float QUANT_RATE_SIGMA = 0.0625f / 2.449490f / 5.0f;      // one probe
static const float QUANT_RATE_SIGMA_PAIR = QUANT_RATE_SIGMA / 1.414214f;
static const float STALE_DEADBAND_MAX = 0.0125f;

static float clampf(float v, float lo, float hi) {
  if (std::isnan(v))
    return lo;
  return v < lo ? lo : (v > hi ? hi : v);
}

void TankController::load_prior_() {
  for (uint8_t i = 0; i < N_PARAMS; i++) {
    this->model_.theta[i] = this->theta_prior_(i);
    for (uint8_t j = 0; j < N_PARAMS; j++)
      this->model_.p[i][j] = (i == j) ? P_PRIOR[i] : 0.0f;
  }
  this->model_.updates = 0;
  // Centred on the first tick, wherever the operating point is then. The
  // prior's c is already "drift where the tank is held", so adopting the
  // reference needs no re-expression.
  this->model_.t_ref = NAN;
  this->model_.ref_mode = REF_SETPOINT;
  this->history_idx_ = 0;
  this->history_count_ = 0;
  for (uint8_t i = 0; i < N_SLOTS; i++) {
    this->light_.slot[i] = 0.0f;
    this->light_.weight[i] = 0.0f;
  }
}

void TankController::setup() {
  this->load_prior_();

  this->model_pref_ = global_preferences->make_preference<ThermalModel>(fnv1_hash("tank_model_v3"));
  this->light_pref_ = global_preferences->make_preference<LightProfile>(fnv1_hash("tank_light"));
  this->setpoint_pref_ = global_preferences->make_preference<float>(fnv1_hash("tank_setpoint"));
  this->fan_deadband_pref_ = global_preferences->make_preference<float>(fnv1_hash("tank_fan_deadband"));
  this->disagree_band_pref_ = global_preferences->make_preference<float>(fnv1_hash("tank_disagree_band"));

  // v4 carries its reference temperature with it. v3 -- everything up to
  // bbf4b6f -- was centred on the fixed LEGACY_TEMP_REF and is migrated:
  //   * theta is kept and declared to be at 24.0 C; sync_reference_() below
  //     then re-expresses c at today's setpoint (c' = c - ka*(sp - 24.0)),
  //     so the first prediction on new firmware equals the last one on the
  //     old -- no step in the feedforward.
  //   * the covariance is NOT kept. It is the product of fault 1 and 2 (see
  //     THETA_MAX): a ka/c correlation built on a near-constant regressor,
  //     with the clamp having thrown away the corrections it "knew" about,
  //     so it is confidently wrong about exactly the combination that is
  //     biased. Back to the prior, as import_model() does for the same
  //     reason: the values are a good start, the certainty is not earned.
  //   * updates (and so Model Confidence) is kept -- the gains are real.
  // On the 75 that means a ka still sitting on its 6000 min bound. It is
  // left there rather than reset to the 67 min prior: with the reference at
  // the operating point ka barely enters the prediction, and it will move
  // the first time the tank makes a real excursion.
  bool migrated = false;
  ThermalModel stored{};
  if (this->model_pref_.load(&stored) && !std::isnan(stored.theta[0])) {
    this->model_ = stored;
    this->clamp_model_();
    ESP_LOGI(TAG, "Restored thermal model after %" PRIu32 " learning steps", this->model_.updates);
  } else {
    auto legacy_pref = global_preferences->make_preference<ThermalModelV3>(fnv1_hash("tank_model_v3"));
    ThermalModelV3 legacy{};
    if (legacy_pref.load(&legacy) && !std::isnan(legacy.theta[0])) {
      for (uint8_t i = 0; i < N_PARAMS; i++) {
        this->model_.theta[i] = legacy.theta[i];
        for (uint8_t j = 0; j < N_PARAMS; j++)
          this->model_.p[i][j] = (i == j) ? P_PRIOR[i] : 0.0f;
      }
      this->model_.updates = legacy.updates;
      this->model_.t_ref = LEGACY_TEMP_REF;
      this->model_.ref_mode = REF_SETPOINT;
      this->clamp_model_();
      migrated = true;
      ESP_LOGW(TAG, "Migrating thermal model from fixed %.1f degF reference (%" PRIu32 " learning steps kept)",
               LEGACY_TEMP_REF * 9.0f / 5.0f + 32.0f, this->model_.updates);
    }
  }
  LightProfile light{};
  if (this->light_pref_.load(&light) && !std::isnan(light.slot[0]))
    this->light_ = light;

  float sp = NAN;
  if (this->setpoint_pref_.load(&sp) && !std::isnan(sp))
    this->setpoint_ = clampf(sp, this->min_temp_, this->max_temp_);

  float db = NAN;
  if (this->fan_deadband_pref_.load(&db) && !std::isnan(db))
    this->fan_deadband_ = clampf(db, 0.0f, FAN_DEADBAND_MAX);

  float dz = NAN;
  if (this->disagree_band_pref_.load(&dz) && !std::isnan(dz))
    this->disagree_band_ = clampf(dz, 0.0f, DISAGREE_BAND_MAX);

  // The ambient probe's own update interval is unknown here, so freshness
  // is judged by when it last published, not by polling its state.
  if (this->ambient_sensor_ != nullptr)
    this->ambient_sensor_->add_on_state_callback([this](float) { this->ambient_last_ms_ = millis(); });

  this->resid_var_ = QUANT_RATE_SIGMA * QUANT_RATE_SIGMA;

  // Setpoint is loaded, so the model can be centred on it now -- a migrated
  // model is re-expressed here, before anything predicts with it -- and the
  // result persisted at once rather than after the first 30 minutes.
  this->sync_reference_(millis(), NAN);
  if (migrated) {
    // A ka sitting exactly on its bound in a v3 model is the bug's
    // signature, not a measurement -- on the 75 it is the 6000 min pin. It
    // goes back to the prior, AFTER the re-centring above so c was carried
    // across with the ka it was fitted alongside. At the setpoint the
    // prediction does not change (the regressor is zero there); away from
    // it the prior is no worse a guess than a clamp artefact. Only ka: a
    // fan gain on its floor, say, is real evidence of a fan not cooling.
    const float ka = this->model_.theta[2];
    if (ka <= THETA_MIN[2] || ka >= this->theta_max_(2)) {
      ESP_LOGW(TAG, "Migrated loss coefficient was pinned at %.0f min - back to the %.0f min prior",
               -1.0f / ka, -1.0f / this->theta_prior_(2));
      this->model_.theta[2] = this->theta_prior_(2);
    }
    this->save_state_();
  }

  // Start with everything off until the first real reading arrives.
  this->apply_outputs_(0.0f, 0.0f);
  this->last_update_ms_ = millis();
  this->last_save_ms_ = millis();
  // The first reading after boot has no history behind it either.
  this->reanchor_ms_ = millis();
}

void TankController::set_disagreement_band(float v) {
  if (std::isnan(v))
    return;
  v = clampf(v, 0.0f, DISAGREE_BAND_MAX);
  if (v == this->disagree_band_)
    return;
  this->disagree_band_ = v;
  this->disagree_band_pref_.save(&v);
}

void TankController::set_setpoint(float v) {
  if (std::isnan(v))
    return;
  v = clampf(v, this->min_temp_, this->max_temp_);
  if (v == this->setpoint_)
    return;
  this->setpoint_ = v;
  // Old integral was accumulated against a different target.
  this->integral_ = 0.0f;
  this->setpoint_pref_.save(&v);
}

void TankController::set_hold(bool v) {
  if (v == this->hold_)
    return;
  this->hold_ = v;
  this->integral_ = 0.0f;
  if (v) {
    ESP_LOGI(TAG, "Hold: outputs off, learning paused");
    this->state_text_ = "hold";
    this->apply_outputs_(0.0f, 0.0f);
    this->heat_stall_since_ms_ = 0;
    this->heater_stalled_ = false;
    this->fan_stall_since_ms_ = 0;
    this->fan_stalled_ = false;
    this->disagree_since_ms_ = 0;
    this->probe_disagreement_ = false;
    // Whatever the learn window was measuring, the hold cuts across it.
    this->reset_learn_window_();
  } else {
    // Not a re-anchor. That cap exists for a GAP in readings, where the
    // first value back has nothing recent to be checked against; through a
    // hold the readings kept flowing and kept being checked. A tank that
    // has just been told to heat gets full authority, now -- the learner
    // was already reset on entry, which is the part that was new water.
    ESP_LOGI(TAG, "Hold released - regulating");
  }
}

void TankController::set_setpoint_override(float c) {
  const float prev = this->setpoint_override_;
  if (std::isnan(c)) {
    this->setpoint_override_ = NAN;
    if (!std::isnan(prev)) {
      ESP_LOGI(TAG, "Setpoint override cleared - back to %.1f degF", this->setpoint_ * 9.0f / 5.0f + 32.0f);
      this->integral_ = 0.0f;
    }
    return;
  }
  c = clampf(c, this->min_temp_, this->max_temp_);
  if (c == prev)
    return;
  this->setpoint_override_ = c;
  this->integral_ = 0.0f;
  ESP_LOGI(TAG, "Setpoint override %.1f degF (owner's setpoint %.1f degF untouched)", c * 9.0f / 5.0f + 32.0f,
           this->setpoint_ * 9.0f / 5.0f + 32.0f);
}

void TankController::set_fan_deadband(float v) {
  if (std::isnan(v))
    return;
  v = clampf(v, 0.0f, FAN_DEADBAND_MAX);
  if (v == this->fan_deadband_)
    return;
  this->fan_deadband_ = v;
  // The integral is deliberately left alone: the clamps in update() zero
  // whatever part of it the new band makes unusable on the next tick.
  this->fan_deadband_pref_.save(&v);
}

void TankController::reset_learning() {
  ESP_LOGW(TAG, "Resetting learned model and light profile to priors");
  this->load_prior_();
  this->integral_ = 0.0f;
  this->bias_ = 0.0f;
  this->stale_ = 0.0f;
  this->resid_var_ = QUANT_RATE_SIGMA * QUANT_RATE_SIGMA;
  // Windows in flight were accumulated against the old model; carrying
  // them over would fold pre-reset data into the first new learning step.
  this->reset_learn_window_();
  this->last_light_slot_ = -1;
  this->heat_stall_since_ms_ = 0;
  this->heater_stalled_ = false;
  this->fan_stall_since_ms_ = 0;
  this->fan_stalled_ = false;
  this->save_state_();
}

void TankController::import_model(float heater_f_per_h, float fan_f_per_h, float light_f_per_h,
                                 float bias_f_per_h, float time_constant_min, float confidence_pct) {
  // degF/hour -> degC/minute. 9/5 for the scale, 60 for the time base.
  const float to_c_min = 1.0f / (60.0f * 9.0f / 5.0f);

  this->model_.theta[0] = heater_f_per_h * to_c_min;
  this->model_.theta[1] = -fan_f_per_h * to_c_min;
  this->model_.theta[2] = (time_constant_min > 1.0f) ? -(1.0f / time_constant_min) : this->theta_prior_(2);
  this->model_.theta[3] = light_f_per_h * to_c_min;
  this->model_.theta[4] = bias_f_per_h * to_c_min;

  // Covariance goes back to the prior rather than being inherited. A tight
  // P would tell RLS the fit is already settled and make it refuse to move
  // -- but this model was measured on another device, and anything that
  // differs (a relay with different contact resistance, the probe sitting
  // somewhere else in the tank) has to be learnable from here. Confident
  // starting point, still willing to be corrected.
  for (uint8_t i = 0; i < N_PARAMS; i++)
    for (uint8_t j = 0; j < N_PARAMS; j++)
      this->model_.p[i][j] = (i == j) ? P_PRIOR[i] : 0.0f;

  // Confidence is what gates the feedforward, so it has to come across or
  // the imported model would sit unused. Capped at 90%: an inherited fit
  // has earned most of the trust, not all of it.
  const float target = (24.0f * 60.0f) / (LEARN_WINDOW_MS / 60000.0f);
  this->model_.updates = (uint32_t) (clampf(confidence_pct, 0.0f, 90.0f) / 100.0f * target);

  // The imported c is the old device's drift where IT held the tank, so it
  // is declared to be at today's setpoint. If an ambient probe is in use,
  // the next tick re-expresses it at the room like any mode change.
  this->model_.t_ref = this->get_active_setpoint();
  this->model_.ref_mode = REF_SETPOINT;
  this->clamp_model_();
  this->integral_ = 0.0f;
  this->reset_learn_window_();
  this->save_state_();

  ESP_LOGI(TAG, "Imported model: kh=%.4f kf=%.4f ka=%.5f kl=%.4f c=%.4f, confidence %.0f%%",
           this->model_.theta[0], -this->model_.theta[1], -this->model_.theta[2], this->model_.theta[3],
           this->model_.theta[4], this->get_confidence());
}

float TankController::theta_max_(uint8_t i) const {
  // ka's floor is the board's max_time_constant; every other bound is fixed.
  return i == 2 ? -this->ka_min_ : THETA_MAX[i];
}

void TankController::set_max_time_constant(float minutes) {
  // __init__.py validates 100-20000 min. Re-checked here because ka_min_
  // must stay strictly positive (get_time_constant divides by it). ka's
  // prior is 15*ka_min_ (theta_prior_()), so at the 100 min minimum it is
  // 0.15 -- still inside THETA_MIN[2]'s 0.2. 1000 min is the default.
  if (!(minutes >= 100.0f))
    minutes = 1000.0f;
  this->ka_min_ = 1.0f / minutes;
}

float TankController::theta_prior_(uint8_t i) const {
  // See THETA_PRIOR for why ka's prior follows the board's ceiling.
  return i == 2 ? -15.0f * this->ka_min_ : THETA_PRIOR[i];
}

float TankController::p_prior_(uint8_t i) const {
  // ka's variance is mode-dependent; see P_KA_AMBIENT.
  if (i == 2 && this->model_.ref_mode == REF_AMBIENT)
    return P_KA_AMBIENT;
  return P_PRIOR[i];
}

void TankController::set_ka_variance_(float target) {
  // Move ka's variance to `target` by scaling its row and column by
  // sqrt(target/P22) -- a congruence transform (D P D with D diagonal), so
  // P stays positive definite and ka's correlations with the rest keep
  // their sign and strength. Used on ambient-mode entry and exit.
  float(&p)[N_PARAMS][N_PARAMS] = this->model_.p;
  if (!(p[2][2] > 0.0f)) {
    p[2][2] = target;
    return;
  }
  const float sc = std::sqrt(target / p[2][2]);
  for (uint8_t j = 0; j < N_PARAMS; j++) {
    if (j == 2)
      continue;
    p[2][j] *= sc;
    p[j][2] = p[2][j];
  }
  p[2][2] = target;
}

void TankController::clamp_model_() {
  // Every path that puts numbers into theta ends here: setup()'s restore
  // from flash, import_model(), rebase_(), and each RLS step in learn_()
  // (after project_bounds_(), so in learn_ this is only a backstop). A model
  // saved with ka pinned at an older, tighter ceiling is simply inside the
  // new range on the next boot and free to move.
  if (this->model_.ref_mode != REF_SETPOINT && this->model_.ref_mode != REF_AMBIENT)
    this->model_.ref_mode = REF_SETPOINT;
  for (uint8_t i = 0; i < N_PARAMS; i++) {
    if (std::isnan(this->model_.theta[i]))
      this->model_.theta[i] = this->theta_prior_(i);
    this->model_.theta[i] = clampf(this->model_.theta[i], THETA_MIN[i], this->theta_max_(i));
    for (uint8_t j = 0; j < N_PARAMS; j++) {
      if (std::isnan(this->model_.p[i][j]))
        this->model_.p[i][j] = (i == j) ? this->p_prior_(i) : 0.0f;
    }
    // Keep the covariance from blowing up during long unexcited stretches.
    const float pp = this->p_prior_(i);
    if (this->model_.p[i][i] > pp * 10.0f)
      this->model_.p[i][i] = pp * 10.0f;
    if (this->model_.p[i][i] < 0.0f)
      this->model_.p[i][i] = pp * 1e-3f;
  }
}

bool TankController::project_bounds_() {
  // Enforce the bounds on an RLS step without throwing the correction away.
  //
  // A plain clamp (all this file used to do) sets theta[i] back to its
  // bound and leaves everything else where the unconstrained step put it.
  // But that step split the correction across parameters according to P:
  // whatever share went to theta[i] is simply deleted, while P goes on
  // recording that the step was absorbed. On a correlated pair -- ka and c
  // with a near-constant regressor -- that is a persistent one-signed
  // residual the model is certain it has already fitted. Fault 2.
  //
  // Instead, for each parameter outside its bounds:
  //   1. Project in the metric of P (the minimum-variance projection onto
  //      theta[i] = bound, standard for inequality-constrained Kalman
  //      estimates): every other parameter moves by its regression on
  //      theta[i], P[j][i]/P[i][i] times the amount theta[i] is pulled
  //      back. A correlated c takes over what ka was not allowed to.
  //   2. Condition P on theta[i] being pinned -- subtract its column's
  //      outer product -- then zero its cross-covariances while keeping
  //      its own variance. The others' certainty now reflects the pin, and
  //      theta[i] is decoupled: still free to leave the bound when the data
  //      says so, with no stale correlation dragging c along when it does.
  // learn_() then re-fits c on whatever this leaves unexplained (step 3).
  // Returns whether any bound was active.
  bool active = false;
  for (uint8_t i = 0; i < N_PARAMS; i++) {
    const float lo = THETA_MIN[i], hi = this->theta_max_(i);
    const float ti = this->model_.theta[i];
    if (std::isnan(ti)) {
      this->model_.theta[i] = this->theta_prior_(i);
      active = true;
      continue;
    }
    if (ti >= lo && ti <= hi)
      continue;
    active = true;
    const float bound = ti < lo ? lo : hi;
    const float pii = this->model_.p[i][i];
    if (pii > 1e-20f) {
      const float d = bound - ti;
      float col[N_PARAMS];
      for (uint8_t j = 0; j < N_PARAMS; j++)
        col[j] = this->model_.p[j][i];
      for (uint8_t j = 0; j < N_PARAMS; j++)
        if (j != i)
          this->model_.theta[j] += col[j] / pii * d;
      for (uint8_t j = 0; j < N_PARAMS; j++)
        for (uint8_t k = 0; k < N_PARAMS; k++)
          if (j != i && k != i)
            this->model_.p[j][k] -= col[j] * col[k] / pii;
      for (uint8_t j = 0; j < N_PARAMS; j++)
        if (j != i)
          this->model_.p[i][j] = this->model_.p[j][i] = 0.0f;
    }
    this->model_.theta[i] = bound;
  }
  return active;
}

void TankController::reset_learn_window_() {
  this->learn_anchor_temp_ = NAN;
  this->learn_anchor_cross_ = NAN;
  this->acc_heater_ = this->acc_fan_ = this->acc_light_ = this->acc_dev_ = 0.0f;
  this->acc_n_ = 0;
}

bool TankController::ambient_usable_(uint32_t now, float water) {
  // Every check, every tick. Failing any of them drops the model back to
  // the setpoint at once -- a reference that is not being measured any
  // more is the one thing the model must not keep using -- and resets the
  // settle timer, so it comes back only after AMBIENT_SETTLE_MS clean.
  //   configured; reported within ambient_timeout_ms_; a number; air
  //   temperature (40-100 degF); and not sat on the water temperature for
  //   SUBMERGED_MS (a probe in the tank, not in the room).
  bool ok = this->ambient_sensor_ != nullptr && this->ambient_last_ms_ != 0 &&
            now - this->ambient_last_ms_ <= this->ambient_timeout_ms_;
  float a = NAN;
  if (ok) {
    a = this->ambient_sensor_->state;
    ok = !std::isnan(a) && a >= AMBIENT_MIN && a <= AMBIENT_MAX;
  }
  if (ok && !std::isnan(water)) {
    if (fabsf(water - a) <= SUBMERGED_BAND) {
      if (this->ambient_close_since_ms_ == 0)
        this->ambient_close_since_ms_ = now == 0 ? 1 : now;
      if (now - this->ambient_close_since_ms_ >= SUBMERGED_MS) {
        if (this->ambient_ok_since_ms_ != 0)
          ESP_LOGW(TAG, "Room reading has matched the water within %.1f degF for %" PRIu32 " h - ignoring it",
                   SUBMERGED_BAND_F, SUBMERGED_MS / 3600000UL);
        ok = false;
      }
    } else {
      this->ambient_close_since_ms_ = 0;
    }
  }
  if (!ok) {
    this->ambient_ok_since_ms_ = 0;
    this->ambient_filt_ = NAN;
    return false;
  }
  // The low-pass the model reads; see AMBIENT_FILTER_MIN. Seeded with the
  // first good reading, then first-order with the tick's own dt.
  if (std::isnan(this->ambient_filt_) || this->ambient_filt_ms_ == 0) {
    this->ambient_filt_ = a;
  } else {
    const float dt = (now - this->ambient_filt_ms_) / 60000.0f;
    this->ambient_filt_ += (a - this->ambient_filt_) * (dt / (AMBIENT_FILTER_MIN + dt));
  }
  this->ambient_filt_ms_ = now;
  if (this->ambient_ok_since_ms_ == 0)
    this->ambient_ok_since_ms_ = now == 0 ? 1 : now;
  // Already in ambient mode (e.g. restored from flash with the source
  // reporting): no need to sit out the settle time again.
  if (this->model_.ref_mode == REF_AMBIENT)
    return true;
  return now - this->ambient_ok_since_ms_ >= AMBIENT_SETTLE_MS;
}

void TankController::rebase_(float new_ref) {
  // Re-express the model at a new reference without changing what it
  // predicts at any temperature:
  //   -ka*(T - r) + c == -ka*(T - r') + c'   =>   c' = c - ka*(r' - r)
  // i.e. theta' = A*theta with A = I + d*e4*e2', d = r' - r. The covariance
  // goes through the same map, P' = A P A', which touches only row/column 4:
  //   P'44 = P44 + 2d*P42 + d^2*P22,   P'4j = P4j + d*P2j  (j != 4).
  // The window being accumulated is re-expressed too: its sum of (T - r)
  // over n samples becomes a sum of (T - r') by subtracting n*d.
  const float old_ref = this->model_.t_ref;
  if (std::isnan(new_ref))
    return;
  if (std::isnan(old_ref)) {
    this->model_.t_ref = new_ref;
    return;
  }
  const float d = new_ref - old_ref;
  if (d == 0.0f)
    return;
  float(&p)[N_PARAMS][N_PARAMS] = this->model_.p;
  this->model_.theta[4] += this->model_.theta[2] * d;
  const float p42 = p[4][2], p22 = p[2][2];
  p[4][4] = p[4][4] + 2.0f * d * p42 + d * d * p22;
  for (uint8_t j = 0; j < N_PARAMS; j++) {
    if (j == 4)
      continue;
    p[4][j] = p[4][j] + d * p[2][j];
    p[j][4] = p[4][j];
  }
  this->acc_dev_ -= this->acc_n_ * d;
  this->model_.t_ref = new_ref;
  this->clamp_model_();
}

void TankController::sync_reference_(uint32_t now, float water) {
  // Keep the model centred where "Where the model is centred" says. Runs
  // every tick, before anything predicts or learns; costs a comparison
  // unless something actually moved.
  if (this->ambient_usable_(now, water)) {
    const float a = this->ambient_filt_;
    if (this->model_.ref_mode != REF_AMBIENT) {
      this->rebase_(a);
      this->model_.ref_mode = REF_AMBIENT;
      if (this->model_.p[2][2] < P_KA_AMBIENT)
        this->set_ka_variance_(P_KA_AMBIENT);
      ESP_LOGI(TAG, "Thermal model now measured against room air (%s, %.1f degF)", this->ambient_source_,
               a * 9.0f / 5.0f + 32.0f);
    } else {
      // The room is the regressor here, not a reference to re-express
      // against: c keeps its meaning (the tank's own heat) and the swing
      // goes to ka. The window's deviations are accumulated per tick
      // against the room as it was then, so nothing needs shifting.
      this->model_.t_ref = a;
    }
    return;
  }
  const float sp = this->get_active_setpoint();
  if (this->model_.ref_mode == REF_AMBIENT) {
    // Back from the last room value the model used to the setpoint.
    this->model_.ref_mode = REF_SETPOINT;
    if (this->model_.p[2][2] > P_PRIOR[2])
      this->set_ka_variance_(P_PRIOR[2]);
    this->rebase_(sp);
    ESP_LOGW(TAG, "Room air (%s) not usable - thermal model back on the %.1f degF setpoint", this->ambient_source_,
             sp * 9.0f / 5.0f + 32.0f);
    return;
  }
  if (std::isnan(this->model_.t_ref) || this->model_.t_ref != sp) {
    const bool first = std::isnan(this->model_.t_ref);
    const float was = this->model_.t_ref;
    this->rebase_(sp);
    if (!first)
      ESP_LOGI(TAG, "Thermal model re-centred %.1f -> %.1f degF (prediction unchanged)", was * 9.0f / 5.0f + 32.0f,
               sp * 9.0f / 5.0f + 32.0f);
  }
}

const char *TankController::get_reference_text() const {
  if (this->model_.ref_mode == REF_AMBIENT)
    return this->ambient_text_;
  return this->ambient_sensor_ == nullptr ? "setpoint (no room sensor)" : "setpoint (room: none)";
}

float TankController::health_deadband_() const {
  // HEALTH_Z standard deviations of stale_'s own noise; see "Health against
  // the measured noise floor". sigma is the residual's measured spread,
  // never below what two DS18B20s quantising could produce.
  float sigma = std::sqrt(std::fmax(this->resid_var_, 0.0f));
  if (sigma < QUANT_RATE_SIGMA_PAIR)
    sigma = QUANT_RATE_SIGMA_PAIR;
  const float ema_sigma = sigma * std::sqrt(STALE_EMA_W / (2.0f - STALE_EMA_W));
  return std::fmin(HEALTH_Z * ema_sigma, STALE_DEADBAND_MAX);
}

void TankController::save_state_() {
  this->model_pref_.save(&this->model_);
  this->light_pref_.save(&this->light_);
}

int TankController::current_slot_(int minutes_ahead) const {
#ifdef USE_TIME
  if (this->time_ != nullptr) {
    auto now = this->time_->now();
    if (now.is_valid()) {
      int minutes = now.hour * 60 + now.minute + minutes_ahead;
      minutes = ((minutes % 1440) + 1440) % 1440;
      return minutes / 15;
    }
  }
#endif
  (void) minutes_ahead;
  return -1;
}

void TankController::update_light_profile_(float lux_norm) {
  int slot = this->current_slot_();
  if (slot < 0)
    return;
  // Only count a slot's confidence up once per visit. Incrementing on
  // every 30s update instead meant a slot reached "well observed" about a
  // minute after first seeing it, so the profile was never more than one
  // day's data pretending to be a schedule.
  const bool first_seen_today = (slot != this->last_light_slot_);
  this->last_light_slot_ = slot;

  float w = this->light_.weight[slot];
  // Fast to converge on the first day, slow and averaging after that.
  float alpha = w < 1.0f ? 1.0f : 0.15f;
  this->light_.slot[slot] = this->light_.slot[slot] * (1.0f - alpha) + lux_norm * alpha;
  if (first_seen_today && w < 30.0f)
    this->light_.weight[slot] = w + 1.0f;
}

float TankController::predicted_light_for_(int minutes_ahead) const {
  int slot = this->current_slot_(minutes_ahead);
  if (slot < 0 || this->light_.weight[slot] < 2.0f) {
    // No clock or not enough history yet -- assume the lights stay as they are.
    return this->lux_sensor_ == nullptr || std::isnan(this->lux_sensor_->state)
               ? 0.0f
               : clampf(this->lux_sensor_->state / this->full_scale_lux_, 0.0f, 1.5f);
  }
  return this->light_.slot[slot];
}

void TankController::learn_(float dt_min, float measured_rate) {
  // phi = [heater, fan, (T - T_ref), light, 1], all window averages.
  float phi[N_PARAMS] = {this->acc_heater_, this->acc_fan_, this->acc_dev_, this->acc_light_, 1.0f};

  float pred = 0.0f;
  for (uint8_t i = 0; i < N_PARAMS; i++)
    pred += this->model_.theta[i] * phi[i];
  float err = measured_rate - pred;

  // A residual this large is a bad reading or someone doing a water change,
  // not new information about the tank.
  if (std::fabs(err) > 0.5f) {
    ESP_LOGW(TAG, "Discarding learning step, residual %.2f degF/h looks like a disturbance",
             err * 60.0f * 9.0f / 5.0f);
    return;
  }

  float p_phi[N_PARAMS] = {0};
  for (uint8_t i = 0; i < N_PARAMS; i++)
    for (uint8_t j = 0; j < N_PARAMS; j++)
      p_phi[i] += this->model_.p[i][j] * phi[j];

  // phi' P phi -- the full quadratic form, which the gain needs.
  float info = 0.0f;
  for (uint8_t i = 0; i < N_PARAMS; i++)
    info += phi[i] * p_phi[i];
  // ...and the same over the excitation regressors alone, which is what
  // says whether the step tells us anything. See INFO_MIN for why the
  // constant column is left out.
  float info_x = 0.0f;
  for (uint8_t i = 0; i < 4; i++)
    for (uint8_t j = 0; j < 4; j++)
      info_x += phi[i] * this->model_.p[i][j] * phi[j];

  // No forgetting factor (lambda = 1); see the note where LAMBDA used to
  // be. What keeps the model able to follow a changing tank is Q on the
  // parameters that physically drift, added below, and the stale-model
  // re-inflation, which is what `informative` still gates.
  const bool informative = info_x > INFO_MIN;
  const float lambda = 1.0f;

  const float denom = lambda + info;
  if (!(denom > 1e-9f))
    return;

  for (uint8_t i = 0; i < N_PARAMS; i++)
    this->model_.theta[i] += (p_phi[i] / denom) * err;

  for (uint8_t i = 0; i < N_PARAMS; i++)
    for (uint8_t j = 0; j < N_PARAMS; j++)
      this->model_.p[i][j] = (this->model_.p[i][j] - (p_phi[i] * p_phi[j]) / denom) / lambda;

  // P is symmetric by construction but drifts with float rounding over
  // thousands of updates, and an asymmetric covariance can make the gain
  // diverge. Cheap to re-impose, so do it every step.
  for (uint8_t i = 0; i < N_PARAMS; i++)
    for (uint8_t j = i + 1; j < N_PARAMS; j++) {
      const float avg = 0.5f * (this->model_.p[i][j] + this->model_.p[j][i]);
      this->model_.p[i][j] = this->model_.p[j][i] = avg;
    }

  // Bounds, by projection rather than clamp (fault 2) -- then step 3 of
  // project_bounds_()'s recipe: what the unconstrained step explained of
  // this window and the projected one does not, c takes. The posterior
  // residual of the unconstrained step is err*lambda/denom (standard RLS).
  if (this->project_bounds_()) {
    float post = 0.0f;
    for (uint8_t i = 0; i < N_PARAMS; i++)
      post += this->model_.theta[i] * phi[i];
    const float want = err * lambda / denom;
    const float refit = (measured_rate - post) - want;
    const float c = this->model_.theta[4] + refit;
    if (c >= THETA_MIN[4] && c <= THETA_MAX[4])
      this->model_.theta[4] = c;
  }

  // Process noise: the parameters that drift, drift (see Q). Added on every
  // step, informative or not -- the room moves whether or not the heater
  // happens to be running.
  this->model_.p[4][4] += Q_C;
  this->model_.p[2][2] += this->model_.ref_mode == REF_AMBIENT ? Q_KA_AMBIENT : Q_KA_SETPOINT;

  this->clamp_model_();
  this->model_.updates++;

  // Track how wrong the model keeps being, and in which direction, and
  // publish it. Reported, deliberately not acted on: an earlier version
  // of this file used bias to gate the feedforward, on the strength of a
  // drift reading of 0.00 degF/h that turned out to be quantisation --
  // one DS18B20 LSB over a 5 minute window is exactly 1.35 degF/h, so
  // that sensor alternates between 0.00 and 1.35 and a single sample of
  // it says nothing. The model was not biased; the reading was aliased.
  // The number is worth having on a dashboard so that mistake is visible
  // next time, and worth keeping out of the control path until something
  // more than one sample justifies it.
  this->bias_ = (1.0f - BIAS_EMA_W) * this->bias_ + BIAS_EMA_W * err;
  this->stale_ = (1.0f - STALE_EMA_W) * this->stale_ + STALE_EMA_W * err;
  // The residual's spread about its own running mean -- the noise floor
  // health is measured against. About the mean, not about zero, so a
  // biased model cannot widen its own deadband by being biased.
  const float dev = err - this->stale_;
  this->resid_var_ = (1.0f - STALE_EMA_W) * this->resid_var_ + STALE_EMA_W * dev * dev;

  // A model that is wrong in one direction, step after step, is stale --
  // random noise averages to zero here, a changed tank does not. While
  // that holds, re-inflate the covariance so RLS corrects at the speed it
  // had when it was new, capped at the prior so it cannot run away. c no
  // longer depends on this (Q keeps it live); it is what lets kh, kf and kl
  // follow a step change in the hardware.
  if (informative && this->get_model_health() < 1.0f) {
    for (uint8_t i = 0; i < N_PARAMS; i++) {
      const float lim = this->p_prior_(i);
      if (this->model_.p[i][i] < lim)
        this->model_.p[i][i] = std::fmin(this->model_.p[i][i] * P_REINFLATE, lim);
    }
  }

  ESP_LOGD(TAG, "learn: rate=%.2f pred=%.2f err=%.2f degF/h kh=%.4f kf=%.4f ka=%.5f kl=%.4f c=%.4f ref=%.2f degF",
           measured_rate * 108.0f, pred * 108.0f, err * 108.0f, this->model_.theta[0], -this->model_.theta[1],
           -this->model_.theta[2], this->model_.theta[3], this->model_.theta[4],
           this->model_.t_ref * 9.0f / 5.0f + 32.0f);
  (void) dt_min;
}

void TankController::apply_outputs_(float heater, float fan) {
  this->heater_duty_ = clampf(heater, 0.0f, 1.0f);
  this->fan_duty_ = this->fan_available_ ? clampf(fan, 0.0f, 1.0f) : 0.0f;
  if (this->heater_ != nullptr)
    this->heater_->set_level(this->heater_duty_);
  if (this->fan_ != nullptr)
    this->fan_->set_level(this->fan_duty_);
}

void TankController::update() {
  const uint32_t now = millis();
  const float dt_min = (now - this->last_update_ms_) / 60000.0f;
  this->last_update_ms_ = now;

  // Centre the model before anything reads it: a setpoint, override or
  // ambient-probe change since the last tick is re-expressed here.
  this->sync_reference_(now, this->temp_sensor_ == nullptr ? NAN : this->temp_sensor_->state);

  float t = this->temp_sensor_ == nullptr ? NAN : this->temp_sensor_->state;

  if (!std::isnan(t) && (t < PLAUSIBLE_MIN || t > PLAUSIBLE_MAX)) {
    ESP_LOGW(TAG, "Reading of %.1f degF is not a water temperature - treating the probe as missing",
             t * 9.0f / 5.0f + 32.0f);
    t = NAN;
  }
  if (!std::isnan(t) && !std::isnan(this->last_temp_) && this->last_valid_ms_ != 0 &&
      now - this->last_valid_ms_ <= DISCONTINUITY_MS && fabsf(t - this->last_temp_) > MAX_STEP) {
    ESP_LOGW(TAG, "Reading jumped %.1f degF in %" PRIu32 "s - not water, treating the probe as missing",
             (t - this->last_temp_) * 9.0f / 5.0f, (now - this->last_valid_ms_) / 1000);
    t = NAN;
  }

  if (std::isnan(t)) {
    if (this->missing_since_ms_ == 0)
      this->missing_since_ms_ = now;
    if (now - this->missing_since_ms_ > SENSOR_TIMEOUT_MS) {
      // No temperature means no safe way to heat. Cutting the heater is the
      // conservative failure: a slowly cooling tank beats a cooked one.
      if (!this->safety_tripped_)
        ESP_LOGE(TAG, "No temperature for %" PRIu32 "s - shutting the heater down", SENSOR_TIMEOUT_MS / 1000);
      this->safety_tripped_ = true;
      this->state_text_ = "fault: no probe";
      this->apply_outputs_(0.0f, 0.0f);
    }
    return;
  }
  this->missing_since_ms_ = 0;

  // A gap in readings invalidates anything measured across it. The learn
  // window would otherwise compute a rate over the whole outage from a
  // single sample's regressor averages and feed that straight into RLS,
  // and the swing figure would report a range that was never observed.
  const uint32_t since_valid = this->last_valid_ms_ == 0 ? 0 : now - this->last_valid_ms_;
  this->last_valid_ms_ = now;
  this->last_temp_ = t;
  if (since_valid > HISTORY_WIPE_MS) {
    ESP_LOGW(TAG, "Gap of %" PRIu32 "s in readings - discarding swing history", since_valid / 1000);
    this->history_idx_ = 0;
    this->history_count_ = 0;
  }
  if (since_valid > DISCONTINUITY_MS) {
    this->reset_learn_window_();
    this->heat_stall_since_ms_ = 0;
    this->fan_stall_since_ms_ = 0;
    // This reading was accepted without a recent one to check it against.
    this->reanchor_ms_ = now;
  }
  const bool settling = this->reanchor_ms_ != 0 && now - this->reanchor_ms_ < REANCHOR_SETTLE_MS;

  // --- hold --------------------------------------------------------------
  // Before the cross-check and the stall detectors on purpose: a tank
  // being filled has probes in air and heaters commanded off, and every
  // one of those checks would call that a fault. Reading validity above
  // still runs, so the gap logic does not fire when the hold ends.
  if (this->hold_) {
    this->state_text_ = "hold";
    this->apply_outputs_(0.0f, 0.0f);
    return;
  }

  // --- cross-check probe -------------------------------------------------
  // A second DS18B20 on its own bus. Not a control input -- the loop
  // regulates on the control probe alone -- but the only thing that can
  // catch the control probe reading a steady, plausible, wrong number,
  // which is exactly what a flooded probe produced on 2026-09-14: 11.8 C,
  // half the tank, inside every window, for minutes at a time. Sustained
  // disagreement means one probe is lying and there is no telling which,
  // so the heater goes off until they agree again. Either probe reading
  // NaN is not a disagreement; the missing-probe path covers the control
  // side and the cross-check simply stands down.
  if (this->cross_sensor_ != nullptr) {
    const float b = this->cross_sensor_->state;
    if (!std::isnan(b) && fabsf(t - b) > this->disagree_band_) {
      if (this->disagree_since_ms_ == 0)
        this->disagree_since_ms_ = now;
      if (now - this->disagree_since_ms_ > DISAGREE_MS) {
        if (!this->probe_disagreement_)
          ESP_LOGE(TAG, "Probes disagree: control %.2f degF, cross-check %.2f degF for %" PRIu32 " min - heater off",
                   t * 9.0f / 5.0f + 32.0f, b * 9.0f / 5.0f + 32.0f, DISAGREE_MS / 60000);
        this->probe_disagreement_ = true;
        this->state_text_ = "fault: probes disagree";
        this->integral_ = 0.0f;
        this->apply_outputs_(0.0f, 0.0f);
        return;
      }
    } else {
      if (this->probe_disagreement_)
        ESP_LOGI(TAG, "Probes agree again - resuming");
      this->disagree_since_ms_ = 0;
      this->probe_disagreement_ = false;
    }
  }

  this->history_[this->history_idx_] = t;
  this->history_idx_ = (this->history_idx_ + 1) % N_HISTORY;
  if (this->history_count_ < N_HISTORY)
    this->history_count_++;

  // --- heater stall ------------------------------------------------------
  // Judged on the duty already commanded, so it covers every path out of
  // update() including the hard temperature limits below.
  if (this->heater_duty_ >= 0.9f) {
    if (this->heat_stall_since_ms_ == 0) {
      this->heat_stall_since_ms_ = now;
      this->heat_stall_temp_ = t;
    } else if (now - this->heat_stall_since_ms_ > HEAT_STALL_MS) {
      const bool rose = (t - this->heat_stall_temp_) >= HEAT_STALL_RISE;
      if (!rose && !this->heater_stalled_)
        ESP_LOGE(TAG, "Heater at full for %" PRIu32 " min with no rise (%.2f degF) - heater may be dead",
                 HEAT_STALL_MS / 60000, (t - this->heat_stall_temp_) * 9.0f / 5.0f);
      this->heater_stalled_ = !rose;
      this->heat_stall_since_ms_ = now;
      this->heat_stall_temp_ = t;
    }
  } else {
    this->heat_stall_since_ms_ = 0;
    this->heater_stalled_ = false;
  }

  if (this->fan_duty_ >= 0.9f) {
    if (this->fan_stall_since_ms_ == 0) {
      this->fan_stall_since_ms_ = now;
      this->fan_stall_temp_ = t;
    } else if (now - this->fan_stall_since_ms_ > FAN_STALL_MS) {
      const bool fell = (this->fan_stall_temp_ - t) >= FAN_STALL_FALL;
      if (!fell && !this->fan_stalled_)
        ESP_LOGE(TAG, "Fan at full for %" PRIu32 " min with no fall (%.2f degF) - fan may be dead",
                 FAN_STALL_MS / 60000, (t - this->fan_stall_temp_) * 9.0f / 5.0f);
      this->fan_stalled_ = !fell;
      this->fan_stall_since_ms_ = now;
      this->fan_stall_temp_ = t;
    }
  } else {
    this->fan_stall_since_ms_ = 0;
    this->fan_stalled_ = false;
  }

  if (this->safety_tripped_) {
    ESP_LOGI(TAG, "Temperature probe is back");
    this->safety_tripped_ = false;
    this->integral_ = 0.0f;
  }

  float lux_norm = 0.0f;
  if (this->lux_sensor_ != nullptr && !std::isnan(this->lux_sensor_->state))
    lux_norm = clampf(this->lux_sensor_->state / this->full_scale_lux_, 0.0f, 1.5f);
  this->update_light_profile_(lux_norm);

  // --- accumulate averages for the next learning step -------------------
  // The regressor is the CONTROL probe's deviation from the reference --
  // the same quantity the prediction below uses, so learning and
  // forecasting never disagree about which water they mean.
  this->acc_heater_ += this->heater_duty_;
  this->acc_fan_ += this->fan_duty_;
  this->acc_light_ += lux_norm;
  this->acc_dev_ += t - this->model_.t_ref;
  this->acc_n_++;

  // The cross-check probe, if it is usable for the rate this tick: valid,
  // a water temperature, and inside the disagreement band. See "Learning
  // from both probes".
  float cross = NAN;
  if (this->cross_sensor_ != nullptr) {
    const float b = this->cross_sensor_->state;
    if (!std::isnan(b) && b >= PLAUSIBLE_MIN && b <= PLAUSIBLE_MAX && fabsf(t - b) <= this->disagree_band_)
      cross = b;
  }

  if (std::isnan(this->learn_anchor_temp_)) {
    this->reset_learn_window_();
    this->learn_anchor_temp_ = t;
    this->learn_anchor_cross_ = cross;
    this->learn_anchor_ms_ = now;
  } else if (now - this->learn_anchor_ms_ >= LEARN_WINDOW_MS && this->acc_n_ > 0) {
    const float window_min = (now - this->learn_anchor_ms_) / 60000.0f;
    const float d_a = t - this->learn_anchor_temp_;
    float delta = d_a;
    if (!std::isnan(cross) && !std::isnan(this->learn_anchor_cross_)) {
      const float d_b = cross - this->learn_anchor_cross_;
      if (fabsf(d_b - d_a) <= PAIR_RATE_TOL)
        delta = 0.5f * (d_a + d_b);
    }
    const float rate = delta / window_min;
    this->drift_rate_ = rate;
    this->acc_heater_ /= this->acc_n_;
    this->acc_fan_ /= this->acc_n_;
    this->acc_light_ /= this->acc_n_;
    this->acc_dev_ /= this->acc_n_;
    if (this->learning_enabled_)
      this->learn_(window_min, rate);
    this->reset_learn_window_();
    this->learn_anchor_temp_ = t;
    this->learn_anchor_cross_ = cross;
    this->learn_anchor_ms_ = now;
  }

  // --- hard safety limits ------------------------------------------------
  if (t >= this->max_temp_) {
    this->state_text_ = "over temperature";
    this->integral_ = 0.0f;
    this->apply_outputs_(0.0f, 1.0f);
    return;
  }
  if (t <= this->min_temp_) {
    this->state_text_ = "under temperature";
    this->integral_ = 0.0f;
    this->apply_outputs_(settling ? REANCHOR_HEAT_CAP : 1.0f, 0.0f);
    return;
  }

  // --- predictive control ------------------------------------------------
  const float kh = this->model_.theta[0];
  const float kf = -this->model_.theta[1];

  // Look ahead by roughly one response time: this is what makes the heater
  // back off *before* the lights come on rather than after the tank warms.
  this->predicted_light_ = this->predicted_light_for_((int) this->response_time_);

  // What the tank will do on its own, with no heater and no fan.
  const float passive_raw = this->model_.theta[2] * (t - this->model_.t_ref) +
                            this->model_.theta[3] * this->predicted_light_ + this->model_.theta[4];

  // Weight the feedforward by how much the model has actually learned.
  //
  // Until RLS has data, `passive_raw` is a guess about an ambient
  // temperature nobody measured -- and it is routinely several times
  // larger than the error term, so it decides the output on its own. Both
  // directions of that guess have already misfired here: an equilibrium
  // set too high refused to heat a cold tank, and one set too low called
  // for heat while the tank sat above target.
  //
  // At zero confidence this collapses to plain feedback on the measured
  // error, which cannot be wrong about the sign. The prediction phases in
  // over roughly a day as the model earns it.
  // Two independent gates, multiplied: has the model had enough data, and
  // do its predictions still match the tank. Either one being low pulls the
  // feedforward out and leaves plain feedback on measured error, which
  // cannot be wrong about the sign.
  const float trust = clampf(this->get_confidence() / 100.0f, 0.0f, 1.0f) * this->get_model_health();
  const float passive = passive_raw * trust;

  const float error = this->get_active_setpoint() - t;

  // Aim to close the error over response_time_ minutes, capped so a big step
  // change doesn't demand a thermally impossible ramp.
  float desired = clampf(error / this->response_time_, -0.15f, 0.15f);

  // Integral term: mops up whatever the model still gets wrong. Sized so a
  // 1 degC error saturates it in roughly one response time -- the old
  // 1/(4*rt^2) took about three hours, far too slow to rescue a bad prior.
  const float ki = 1.0f / (this->response_time_ * this->response_time_);
  this->integral_ += error * dt_min * ki;
  // Bound the integral by the actuator authority it can command, not by a
  // fixed rate. This is what caused the overshoot: at the old flat
  // +/-0.05 degC/min and a learned kh of 0.032, the integral ALONE was
  // worth 158% heater duty. Once saturated it held the heater at 100%
  // until the measured error alone could outweigh it, which took 3.6 degF
  // of overshoot -- and that is what the tank did, running 39 minutes at
  // full power from 75.8 F to 77.8 F against a 76.0 F setpoint.
  //
  // Capped at 30% duty the integral can still mop up a steady-state
  // offset the model gets wrong, which is its job, but it can no longer
  // outvote the measurement. Scaled by kh so it tracks the learned heater
  // rather than assuming one.
  // Bounded by what each actuator can do with it, not by a single rate.
  // A positive integral drives the heater and a negative one drives the
  // fan, and the two gains differ by roughly an order of magnitude, so
  // clamping both sides with kh held the heater to 30% duty while leaving
  // the fan free up to 0.3*kh/kf -- which grows without bound as kf falls.
  // With an unlearned fan gain that is how a 0.66 degF excursion came out
  // as 100% fan.
  const float i_max_heat = INTEGRAL_AUTHORITY * (kh > 1e-4f ? kh : THETA_PRIOR[0]);
  const float i_max_cool = INTEGRAL_AUTHORITY * (kf > 1e-4f ? kf : -THETA_PRIOR[1]);
  this->integral_ = clampf(this->integral_, -i_max_cool, i_max_heat);

  const float net = desired + this->integral_ - passive;

  float heater = 0.0f, fan = 0.0f;
  if (net > 0.0f) {
    heater = kh > 1e-4f ? net / kh : 0.0f;
    this->state_text_ = heater > 0.99f ? "heating (full)" : "heating";
  } else if (net < 0.0f) {
    if (this->fan_available_ && kf > 1e-4f) {
      fan = -net / kf;
      this->state_text_ = "cooling";
    } else {
      this->state_text_ = "coasting";
    }
  } else {
    this->state_text_ = "holding";
  }

  // Sign guard. The feedforward is a model; the error is a measurement.
  // When the two disagree about which direction the tank needs to move,
  // the measurement wins -- nothing legitimate asks for heat while the
  // water is already above target, or for cooling while it is below.
  //
  // This is the piece the tank's own history actually justifies: with the
  // integral saturated, the controller ran 39 minutes at 100% duty from
  // 75.8 F up to 77.8 F against a 76.0 F setpoint. The integral clamp
  // above is the root fix; this is the backstop that cannot be wrong
  // about the sign whatever the model does. The deadband leaves the
  // genuinely useful case -- pre-empting the lights near setpoint --
  // fully intact.
  if (error < -GUARD_DEADBAND && heater > 0.0f) {
    ESP_LOGW(TAG, "Sign guard: model asked for %.0f%% heat at %.2f degF above setpoint", heater * 100.0f,
             -error * 9.0f / 5.0f);
    heater = 0.0f;
    this->state_text_ = "coasting (overruled)";
  } else if (error > GUARD_DEADBAND && fan > 0.0f) {
    ESP_LOGW(TAG, "Sign guard: model asked for %.0f%% cooling at %.2f degF below setpoint", fan * 100.0f,
             error * 9.0f / 5.0f);
    fan = 0.0f;
    this->state_text_ = "coasting (overruled)";
  } else if (fan > 0.0f && error > -this->fan_deadband_) {
    // Warm, but not by enough to be worth evaporating water over. Ordered
    // AFTER the sign guard on purpose: this branch is wide enough to
    // swallow the pathological below-setpoint case, and that one has to
    // keep reaching the log.
    fan = 0.0f;
    this->state_text_ = "coasting";
  }

  // Anti-windup: if we're pinned at an actuator limit, stop integrating.
  if ((heater >= 1.0f && error > 0.0f) || (fan >= 1.0f && error < 0.0f))
    this->integral_ -= error * dt_min * ki;

  // The same idea for the other end of the range. A rule that forbids an
  // actuator is a saturation at zero, and the check above did not see it
  // as one: the fan deadband zeroed the fan without touching the integral,
  // so through every light period the tank sat inside the band, the error
  // stayed negative, and the integral wound up to its cooling clamp asking
  // for a fan it was not allowed to have. When the light ramped down and
  // the water crossed back under setpoint, that stored demand had to
  // unwind before the heater could command anything -- 50 minutes at a
  // 0.2 degF error against the 1/rt^2 gain -- and the tank fell 0.3 degF
  // below target waiting for it (2026-09-12: heater at 0.4% at 19:00,
  // 13.7% at 20:00, water at 74.2 F against 74.5).
  //
  // Keyed on the rules, not on whether an actuator happened to be asked
  // for this tick: integral in a direction the rules currently forbid is
  // not a correction, it is a debt, whatever the rest of the sum did. And
  // it is cleared rather than merely frozen -- freezing would still carry
  // over whatever the fan had accumulated legitimately before the band
  // closed. The heater's own integral is untouched while the fan is
  // forbidden; that is exactly what catches the light-off cooling.
  //
  // Gated on a fan existing. Without one the negative side is the only
  // thing that can trim an over-confident heater model, and clearing it
  // would hand a fan-less tank a permanent warm offset.
  if (this->fan_available_ && error > -this->fan_deadband_ && this->integral_ < 0.0f)
    this->integral_ = 0.0f;
  if (error < -GUARD_DEADBAND && this->integral_ > 0.0f)
    this->integral_ = 0.0f;

  if (settling && heater > REANCHOR_HEAT_CAP) {
    heater = REANCHOR_HEAT_CAP;
    // Say what is being driven, not what was wanted.
    this->state_text_ = "heating (capped)";
  }

  this->apply_outputs_(heater, fan);

  // Where the model says we'll be in 15 minutes at this output level.
  // Uses the unweighted prediction: this is the model's honest forecast,
  // not the trust-limited term the controller acts on.
  const float rate_now =
      kh * this->heater_duty_ + this->model_.theta[1] * this->fan_duty_ + passive_raw;
  this->predicted_temp_ = t + rate_now * 15.0f;

  if (now - this->last_save_ms_ > SAVE_INTERVAL_MS) {
    this->save_state_();
    this->last_save_ms_ = now;
  }
}

float TankController::get_swing() const {
  // Ten minutes of data before this number means anything at all.
  if (this->history_count_ < 20)
    return NAN;
  float lo = this->history_[0], hi = this->history_[0];
  for (uint8_t i = 1; i < this->history_count_; i++) {
    const float v = this->history_[i];
    if (v < lo)
      lo = v;
    if (v > hi)
      hi = v;
  }
  return hi - lo;
}

float TankController::get_time_constant() const {
  // clamp_model_() holds ka at or above ka_min_ (> 0), so this cannot divide
  // by zero. The old `ka > 1e-4` test would have reported NaN for any
  // learned time constant beyond 10000 min, which max_time_constant now
  // permits; the guard is kept only against a corrupted model.
  const float ka = -this->model_.theta[2];
  return ka > 0.0f ? 1.0f / ka : NAN;  // minutes
}

float TankController::get_model_health() const {
  // 1.0 while the residual's running mean is indistinguishable from noise,
  // falling to 0.0 as a persistent one-directional error grows to the size
  // of the fan's whole authority. Uses the SIGNED error EMA, not the
  // magnitude: noise cancels in the EMA and a genuinely wrong model does
  // not, so this measures staleness rather than noisiness. The deadband is
  // that EMA's own measured noise, not a fixed number; see
  // health_deadband_().
  const float e = std::fabs(this->stale_);
  const float db = this->health_deadband_();
  if (e <= db)
    return 1.0f;
  return clampf(1.0f - (e - db) / STALE_SCALE, 0.0f, 1.0f);
}

float TankController::get_confidence() const {
  // Purely how much data the model has seen -- deliberately NOT multiplied
  // by health. Folding the two together made this read 0 for a full day
  // after a reset, because a freshly reset model IS inaccurate by
  // definition, and that destroyed the only signal that says whether
  // learning is progressing at all.
  //
  // The two are separate measurements answering separate questions: this
  // one is "has it had time", get_model_health() is "is it right". Both
  // gate the feedforward, at the trust site in update().
  const float target = (24.0f * 60.0f) / (LEARN_WINDOW_MS / 60000.0f);
  return clampf(100.0f * this->model_.updates / target, 0.0f, 100.0f);
}

void TankController::dump_config() {
  ESP_LOGCONFIG(TAG, "Tank Controller:");
  ESP_LOGCONFIG(TAG, "  Setpoint: %.1f degF (limits %.1f - %.1f)", this->setpoint_ * 9.0f / 5.0f + 32.0f,
                this->min_temp_ * 9.0f / 5.0f + 32.0f, this->max_temp_ * 9.0f / 5.0f + 32.0f);
  ESP_LOGCONFIG(TAG, "  Response time: %.0f min", this->response_time_);
  ESP_LOGCONFIG(TAG, "  Max time constant: %.0f min", 1.0f / this->ka_min_);
  if (this->ambient_sensor_ != nullptr) {
    ESP_LOGCONFIG(TAG, "  Room air: %s (valid for %" PRIu32 " min after each report)", this->ambient_source_,
                  this->ambient_timeout_ms_ / 60000UL);
  } else {
    ESP_LOGCONFIG(TAG, "  Room air: none");
  }
  if (std::isnan(this->model_.t_ref)) {
    ESP_LOGCONFIG(TAG, "  Model reference: not yet centred");
  } else {
    ESP_LOGCONFIG(TAG, "  Model reference: %.2f degF (%s)", this->model_.t_ref * 9.0f / 5.0f + 32.0f,
                  this->model_.ref_mode == REF_AMBIENT ? "room air" : "setpoint");
  }
  ESP_LOGCONFIG(TAG, "  Fan available: %s", YESNO(this->fan_available_));
  ESP_LOGCONFIG(TAG, "  Fan deadband: %.2f degF above setpoint", this->fan_deadband_ * 9.0f / 5.0f);
  ESP_LOGCONFIG(TAG, "  Cross-check probe: %s (disagreement band %.1f degF)", YESNO(this->cross_sensor_ != nullptr),
                this->disagree_band_ * 9.0f / 5.0f);
  ESP_LOGCONFIG(TAG, "  Learning: %s (%" PRIu32 " steps, %.0f%% confidence)", ONOFF(this->learning_enabled_),
                this->model_.updates, this->get_confidence());
  ESP_LOGCONFIG(TAG, "  Model: kh=%.4f kf=%.4f ka=%.5f kl=%.4f c=%.4f", this->model_.theta[0], -this->model_.theta[1],
                -this->model_.theta[2], this->model_.theta[3], this->model_.theta[4]);
}

}  // namespace tank_controller
}  // namespace esphome
