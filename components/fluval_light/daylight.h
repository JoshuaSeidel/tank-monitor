#pragma once
#include <cmath>
#include <ctime>
#include <vector>
#include <algorithm>

// A real day for an aquarium light, vendor-neutral.
//
// It lives inside components/fluval_light/ rather than a components/daylight/
// of its own because ESPHome copies external components by DIRECTORY, and a
// header in a directory with no component class in it does not reliably make
// it into the build. One consumer, one copy. If a second fixture in this repo
// ever needs the sun, promote it then -- and only then.
//
// ---------------------------------------------------------------------
// WHERE THIS CAME FROM, AND THE SIBLING YOU MUST KEEP IN STEP
// ---------------------------------------------------------------------
// This is the astronomy half of chihiros-esphome's
// components/chihiros_ble/daylight.h, which has driven the 75 gal's
// WRGB II Pro since 2026-10. It is lifted rather than rewritten: that
// implementation is proven against hardware, and a second solar model
// computing slightly different sunrises for two tanks in the same room
// would be a bug nobody could see.
//
// THE COPIES ARE NOT LINKED. A change to the sun model here needs the
// same change in the fork, and vice versa. That duplication is a
// deliberate choice, not an oversight: the fork carries an open upstream
// PR to BartdeJonge/chihiros-esphome, and a fork that #includes
// tank-monitor is a fork that can never be merged upstream. ESPHome has
// no mechanism for one external component to depend on another's header,
// so the options were a copy or a cross-repo dependency that breaks the
// PR. The copy wins.
//
// What was left behind, because it is WRGB-specific: warm() (the golden
// shift for a red/green/blue/white mix), luminous() (that fixture's
// channel weights), point_at() and points() (which return
// WRGB2Device::CurvePoint). Only those last two need the protocol
// header -- which is why the fork's daylight.h carries an
// #include "chihiros_devices.h" that 130 lines of pure astronomy have no
// use for. Splitting it there would make this copy unnecessary for the
// math and is worth doing next time that file is open.
//
// ---------------------------------------------------------------------
// THE MODEL
// ---------------------------------------------------------------------
//   h(t)    solar elevation, degrees (NOAA low-precision ephemeris, ~0.1 deg)
//   E(h)    clear-sky global horizontal illuminance, lux:
//             h >= 0       direct + sky, Kasten-Young air mass
//             -6 <= h < 0  civil twilight, 800 lx * 10^(0.38 h)
//             h < -6       0
//   level   = (E(h) / E(noon))^g
//
// g = 1 is literal photometry and reads far too dim for the first
// 90 minutes -- the lamp would light at sunrise rather than at dawn.
// g < 1 compresses the range the way vision does (lightness ~
// luminance^(1/3..1/2)). Plants respond to the linear photon dose, which
// the caller reports separately as full-equivalent hours.
//
// No allocation in the math, no state. Times are POSIX epoch seconds (UTC).

namespace tank_monitor {
namespace daylight {

inline double elevation(time_t utc, double lat, double lon) {
  const double d2r = M_PI / 180.0;
  const double n = utc / 86400.0 + 2440587.5 - 2451545.0;  // days since J2000
  const double L = std::fmod(280.460 + 0.9856474 * n, 360.0);
  const double g = std::fmod(357.528 + 0.9856003 * n, 360.0) * d2r;
  const double lam = (L + 1.915 * std::sin(g) + 0.020 * std::sin(2 * g)) * d2r;
  const double eps = (23.439 - 0.0000004 * n) * d2r;
  const double ra = std::atan2(std::cos(eps) * std::sin(lam), std::cos(lam));
  const double dec = std::asin(std::sin(eps) * std::sin(lam));
  const double gmst = std::fmod(18.697374558 + 24.06570982441908 * n, 24.0);
  const double ha = (gmst * 15.0 + lon) * d2r - ra;
  const double la = lat * d2r;
  return std::asin(std::sin(la) * std::sin(dec) + std::cos(la) * std::cos(dec) * std::cos(ha)) / d2r;
}

inline double illuminance(double h) {
  if (h < -6.0)
    return 0.0;
  if (h < 0.0)
    return 800.0 * std::pow(10.0, 0.38 * h);
  const double s = std::sin(h * M_PI / 180.0);
  const double m = 1.0 / (s + 0.50572 * std::pow(h + 6.07995, -1.6364));
  return 127500.0 * std::exp(-0.21 * m) * s + 800.0 + 15500.0 * std::sqrt(s);
}

inline float level(double h, double e_noon, float expo) {
  const double e = illuminance(h);
  if (e <= 0.0 || e_noon <= 0.0)
    return 0.0f;
  const double r = e / e_noon;
  return (float) std::pow(r > 1.0 ? 1.0 : r, (double) expo);
}

// The day's events in local minutes, from a 1-minute scan of local
// midnight .. +24 h. -1 when the event does not happen (polar day/night).
struct Day {
  int dawn = -1, rise = -1, noon = -1, set = -1, dusk = -1;
  double e_noon = 0.0;
};

inline Day day(time_t local_midnight_utc, double lat, double lon) {
  Day d;
  double best = -90.0, prev = 0.0;
  for (int m = 0; m <= 1440; m++) {
    const double h = elevation(local_midnight_utc + (time_t) m * 60, lat, lon);
    if (m > 0) {
      if (prev < -6.0 && h >= -6.0 && d.dawn < 0)
        d.dawn = m;
      if (prev < -0.833 && h >= -0.833 && d.rise < 0)
        d.rise = m;
      if (prev >= -0.833 && h < -0.833)
        d.set = m - 1;
      if (prev >= -6.0 && h < -6.0)
        d.dusk = m - 1;
    }
    if (m < 1440 && h > best) {
      best = h;
      d.noon = m;
    }
    prev = h;
  }
  d.e_noon = illuminance(best);
  return d;
}

// Everything a board needs about one day of the curve.
struct Plan {
  Day d;
  double lat = 0, lon = 0;
  time_t mid = 0;          // local midnight, UTC epoch
  float expo = 0.5f;       // daylight exponent
  float scale = 1.0f;      // peak (1 = the phase's full values; <1 under a cap)
  float natural_h = 0.0f;  // full-equivalent hours at scale 1
  float dose_h = 0.0f;     // full-equivalent hours delivered (after any cap)
  int bright_on = -1, bright_off = -1;  // level >= th * peak
  bool ok = false;
};

// Fraction of the phase's full values at local minute m.
inline float frac_at(const Plan &p, int m) {
  if (!p.ok || m < p.d.dawn || m > p.d.dusk)
    return 0.0f;
  return p.scale * level(elevation(p.mid + (time_t) m * 60, p.lat, p.lon), p.d.e_noon, p.expo);
}

inline double elev_at(const Plan &p, int m) { return elevation(p.mid + (time_t) m * 60, p.lat, p.lon); }

// Cubic ease, 0 below a and 1 above b. Same function as the Chihiros copy,
// because the warm shift it drives has to behave identically on both tanks.
inline float smoothstep(float a, float b, float x) {
  if (x <= a)
    return 0.0f;
  if (x >= b)
    return 1.0f;
  const float t = (x - a) / (b - a);
  return t * t * (3.0f - 2.0f * t);
}

// cap_min > 0 scales the whole day down to that many full-equivalent
// minutes if the natural day delivers more; 0 = natural.
inline Plan plan(time_t local_midnight_utc, double lat, double lon, float expo, int cap_min, float th) {
  Plan p;
  p.d = day(local_midnight_utc, lat, lon);
  p.lat = lat;
  p.lon = lon;
  p.mid = local_midnight_utc;
  p.expo = expo;
  if (p.d.dawn < 0 || p.d.dusk <= p.d.dawn || p.d.e_noon <= 0.0)
    return p;
  p.ok = true;

  double sum = 0.0;
  for (int m = p.d.dawn; m <= p.d.dusk; m++)
    sum += level(elevation(p.mid + (time_t) m * 60, lat, lon), p.d.e_noon, expo);
  p.natural_h = (float) (sum / 60.0);

  p.scale = 1.0f;
  if (cap_min > 0 && sum > cap_min)
    p.scale = (float) (cap_min / sum);
  p.dose_h = p.natural_h * p.scale;

  const float peak = p.scale;
  for (int m = p.d.dawn; m <= p.d.dusk; m++) {
    const float f = frac_at(p, m);
    if (f >= th * peak) {
      if (p.bright_on < 0)
        p.bright_on = m;
      p.bright_off = m;
    }
  }
  return p;
}

// ---------------------------------------------------------------------
// WHICH MINUTES TO SEND
// ---------------------------------------------------------------------
// Vendor-neutral half of the fork's points(): choose WHEN the curve
// bends, and leave rendering the channel values at those minutes to the
// caller, who is the only one who knows how many channels the fixture has
// and what they mean.
//
// Always: civil dawn, sunrise, sunset, civil dusk exactly -- those are
// the day's real corners and a resampler that misses them makes the lamp
// light late and go out early. Then `edge` steps within `edge_span` of
// dawn and dusk where the curve is steep, and `step` steps through the
// flat middle.
//
// max_pts is a HARD cap, and the loop is why this function exists rather
// than a fixed grid: a Chihiros takes 24 points and a Fluval Plant 4.0
// takes 12, so the same summer day has to fit both. Steps double until it
// does, which drops resolution from the middle of the day first -- the
// part where the curve is flattest and losing a point costs least.
inline std::vector<int> pick_minutes(const Plan &p, int step, int edge, int edge_span = 120, int max_pts = 24) {
  std::vector<int> ms;
  if (!p.ok)
    return ms;
  for (int tries = 0; tries < 6; tries++) {
    ms.clear();
    ms.push_back(p.d.dawn);
    ms.push_back(p.d.dusk);
    if (p.d.rise > p.d.dawn)
      ms.push_back(p.d.rise);
    if (p.d.set > 0 && p.d.set < p.d.dusk)
      ms.push_back(p.d.set);
    auto near = [&](int m) {
      for (int x : ms)
        if (std::abs(x - m) < 5)
          return true;
      return false;
    };
    for (int m = (p.d.dawn / edge + 1) * edge; m < p.d.dusk; m += edge) {
      const bool at_edge = m <= p.d.dawn + edge_span || m >= p.d.dusk - edge_span;
      if (!at_edge && m % step != 0)
        continue;
      if (!near(m))
        ms.push_back(m);
    }
    std::sort(ms.begin(), ms.end());
    if ((int) ms.size() <= max_pts || tries == 5)
      return ms;
    step *= 2;
    edge *= 2;
  }
  return ms;
}

}  // namespace daylight
}  // namespace tank_monitor
