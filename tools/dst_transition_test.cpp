// Host simulation of both boards' lamp-day logic across the US DST changes.
//
//   c++ -std=c++17 -O2 -o /tmp/dst_test tools/dst_transition_test.cpp && /tmp/dst_test
//   (run from the repo root; it reads packages/light_wrgb2.yaml)
//
// Field bug, 2026-11-01: both boards computed the day before the 02:00
// fall-back (the 75 at 00:00 EDT, the nano at 01:30 EDT), so its wall-clock
// minutes were EDT; the lamps' clocks were then resynced to EST and both
// tanks ran an hour late against the sun. This walks every minute of both
// transitions (2026-11-01 and 2027-03-14, TZ America/New_York) through a
// model of each board's decision logic, OLD and NEW, and checks the one
// thing that matters: when the LAMP reaches civil dawn and dusk on its own
// clock, is that the real civil dawn and dusk?
//
// The solar math is the real tank_monitor::daylight (components/
// fluval_light/daylight.h); its fork twin in chihiros-esphome is the same
// code by design. Time fields come from libc localtime_r under the real
// tz database, standing in for ESPHome's ESPTime. The decision logic is a
// model of light_wrgb2.yaml (light_sun_check, minute tick, 03:00 resync,
// light_push) and fluval_light.cpp (update, sync_clock, push_curve) -- the
// 75's offset expression is checked verbatim against the YAML below.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fstream>
#include <sstream>
#include <string>

#include "../components/fluval_light/daylight.h"

namespace dl = tank_monitor::daylight;

static const double LAT = 39.8, LON = -76.7;
static int failures = 0;

struct T {  // the ESPTime fields the boards use
  time_t timestamp;
  int hour, minute, second, yday;
  bool dst;
};
static T at(time_t ts) {
  struct tm lt;
  localtime_r(&ts, &lt);
  return {ts, lt.tm_hour, lt.tm_min, lt.tm_sec, lt.tm_yday + 1, lt.tm_isdst > 0};
}
static time_t utc(int y, int mo, int d, int h, int mi) {
  struct tm u{};
  u.tm_year = y - 1900;
  u.tm_mon = mo - 1;
  u.tm_mday = d;
  u.tm_hour = h;
  u.tm_min = mi;
  return timegm(&u);
}

// The expression light_wrgb2.yaml uses (twice), pasted verbatim; main()
// checks the YAML still carries exactly this text.
#define YAML_OFF_EXPR (int) ((((long) (now.hour * 3600 + now.minute * 60 + now.second) - (long) (now.timestamp % 86400)) % 86400L + 86400L) % 86400L / 60L)
#define STR2(x) #x
#define STR(x) STR2(x)
static int yaml_off(const T &now) { return YAML_OFF_EXPR; }
static const char *YAML_EXPR = STR(YAML_OFF_EXPR);

static int off_of(const T &n) { return dl::utc_offset_min(n.timestamp, n.hour, n.minute, n.second); }

// A computed day: the plan, on the board's `mid` (now - local time of day).
struct Day {
  dl::Plan p;
  int yday = -1, off = -1;
};
static Day compute(const T &n) {
  Day d;
  const time_t mid = n.timestamp - (time_t) (n.hour * 3600 + n.minute * 60 + n.second);
  d.p = dl::plan(mid, LAT, LON, 0.5f, 0, 0.7f);
  d.yday = n.yday;
  d.off = off_of(n);
  return d;
}

// The lamp: holds a curve of wall-clock minutes and a free-running clock
// that was set to local wall time at its last sync (offset frozen then).
struct Lamp {
  int dawn = -1, dusk = -1;  // curve minutes
  int clock_off = -1;        // offset its clock was set on, minutes east mod 1440
  int curve_yday = -1;
};

// When does the lamp actually reach minute m of `local_date` on its clock?
// Its clock reads utc + clock_off; its midnight for that date is the UTC
// instant that reads 00:00.
static time_t lamp_fires(const Lamp &l, time_t date_noon_utc, int m) {
  const int off = l.clock_off > 720 ? l.clock_off - 1440 : l.clock_off;  // signed minutes
  const time_t lamp_local = date_noon_utc + off * 60;
  const time_t lamp_mid_local = lamp_local - lamp_local % 86400;
  return lamp_mid_local - off * 60 + (time_t) m * 60;
}

// Truth: civil dawn/dusk for the date, from a minute scan of real UTC.
static void truth(time_t date_noon_utc, time_t &dawn, time_t &dusk) {
  dawn = dusk = 0;
  double prev = dl::elevation(date_noon_utc - 12 * 3600, LAT, LON);
  for (time_t t = date_noon_utc - 12 * 3600 + 60; t < date_noon_utc + 12 * 3600; t += 60) {
    const double h = dl::elevation(t, LAT, LON);
    if (prev < -6.0 && h >= -6.0 && !dawn) dawn = t;
    if (prev >= -6.0 && h < -6.0) dusk = t - 60;
    prev = h;
  }
}

static std::string hm_local(time_t t) {
  T n = at(t);
  char b[32];
  snprintf(b, sizeof(b), "%02d:%02d %s", n.hour, n.minute, n.dst ? "EDT" : "EST");
  return b;
}

static void check(const char *who, const char *variant, const Lamp &l, time_t date_noon, bool expect_ok) {
  time_t tdawn, tdusk;
  truth(date_noon, tdawn, tdusk);
  const time_t ldawn = lamp_fires(l, date_noon, l.dawn), ldusk = lamp_fires(l, date_noon, l.dusk);
  const long e1 = (long) (ldawn - tdawn) / 60, e2 = (long) (ldusk - tdusk) / 60;
  const bool ok = labs(e1) <= 1 && labs(e2) <= 1;
  printf("  %-5s %-3s lamp dawn %s (sun %s, %+4ld min)  dusk %s (sun %s, %+4ld min)  %s\n", who, variant,
         hm_local(ldawn).c_str(), hm_local(tdawn).c_str(), e1, hm_local(ldusk).c_str(), hm_local(tdusk).c_str(), e2,
         ok ? "ON TIME" : "WRONG");
  if (ok != expect_ok) {
    printf("    FAIL: expected %s\n", expect_ok ? "on time" : "the old bug to reproduce");
    failures++;
  }
}

// ---- the 75 gal (light_wrgb2.yaml) -------------------------------------
struct Board75 {
  bool fixed = false;
  Day day;
  Lamp lamp;
  void push(const T &n) {  // light_push: (new) light_sun_check first; prepare() sets the clock
    if (fixed) sun_check(n);
    lamp.dawn = day.p.d.dawn;
    lamp.dusk = day.p.d.dusk;
    lamp.curve_yday = day.yday;
    lamp.clock_off = off_of(n);
  }
  bool sun_check(const T &n) {  // light_sun_check
    const bool new_day = day.yday != n.yday;
    const bool new_off = fixed && day.off >= 0 && day.off != yaml_off(n);
    if (!new_day && !new_off) return false;
    day = compute(n);
    return true;
  }
  void tick(const T &n) {  // interval: 1min
    if (fixed) {
      if (sun_check(n)) { push(n); return; }
      if (n.hour == 3 && n.minute == 0) push(n);
    } else {
      if (n.hour == 3 && n.minute == 0) push(n);  // old: re-pushes the cached day
      if (day.yday != n.yday) { day = compute(n); push(n); return; }
    }
  }
  void button(const T &n) {  // "Push Light Phase Now"
    if (fixed) day = compute(n);  // new: light_select_phase first
    push(n);
  }
};

// ---- the nano (fluval_light.cpp) ---------------------------------------
struct Nano {
  bool fixed = false;
  int last_push_day = -1, curve_off = -1;
  Lamp lamp;
  void queue_clock(const T &n) { lamp.clock_off = off_of(n); }
  void push_curve(const T &n) {
    Day d = compute(n);
    curve_off = d.off;
    if (fixed) queue_clock(n);  // new: clock always goes out with the curve
    lamp.dawn = d.p.d.dawn;
    lamp.dusk = d.p.d.dusk;
    lamp.curve_yday = d.yday;
  }
  void sync_clock(const T &n) {
    if (fixed && curve_off >= 0 && off_of(n) != curve_off) { push_curve(n); return; }
    queue_clock(n);
  }
  void update(const T &n) {  // every 60 s
    if (n.hour == 1 && n.minute >= 30 && n.yday != last_push_day) {
      last_push_day = n.yday;
      if (!fixed) sync_clock(n);
      push_curve(n);
      return;
    }
    if (fixed && curve_off >= 0 && off_of(n) != curve_off) { curve_off = off_of(n); push_curve(n); }
  }
  void on_connect(const T &n) { sync_clock(n); }
};

static void run(const char *name, time_t from, time_t to, time_t date_noon, bool reconnect) {
  printf("\n%s, %s .. %s, nano BLE reconnect at 06:00: %s\n", name, hm_local(from).c_str(), hm_local(to).c_str(),
         reconnect ? "yes" : "no");
  for (int fixed = 0; fixed <= 1; fixed++) {
    Board75 b; b.fixed = fixed;
    Nano nn; nn.fixed = fixed;
    // Yesterday's state, as the boards would hold it at 23:00.
    T start = at(from);
    b.day = compute(start);
    b.push(start);
    nn.last_push_day = start.yday;
    nn.push_curve(start);
    for (time_t t = from; t <= to; t += 60) {
      T n = at(t);
      b.tick(n);
      nn.update(n);
      if (reconnect && n.hour == 6 && n.minute == 0) nn.on_connect(n);
    }
    // Lamp-day checked for the transition date (nothing more is pushed
    // before dawn in either model).
    const char *v = fixed ? "NEW" : "OLD";
    check("75gal", v, b.lamp, date_noon, fixed);
    // The OLD nano is only wrong if something resyncs its clock after the
    // switch (a BLE reconnect; the field case): with no reconnect its clock
    // and its curve both stay on the old offset and happen to agree.
    check("nano", v, nn.lamp, date_noon, fixed || !reconnect);
  }
}

int main() {
  setenv("TZ", "America/New_York", 1);
  tzset();

  // The 75's YAML copy of the offset expression must be the one tested.
  {
    std::ifstream f("packages/light_wrgb2.yaml");
    if (!f) { printf("run from the repo root (needs packages/light_wrgb2.yaml)\n"); return 2; }
    std::stringstream ss;
    ss << f.rdbuf();
    const std::string y = ss.str();
    size_t n = 0;
    for (size_t p = y.find(YAML_EXPR); p != std::string::npos; p = y.find(YAML_EXPR, p + 1)) n++;
    printf("light_wrgb2.yaml carries the tested offset expression %zu times (expect 2)\n", n);
    if (n != 2) failures++;
  }

  // utc_offset_min == the YAML expression == the tz database, every 7 min
  // of 2026-2027 (catches both switches and every hour of day).
  {
    long n = 0, bad = 0;
    for (time_t t = utc(2026, 1, 1, 0, 0); t < utc(2028, 1, 1, 0, 0); t += 7 * 60, n++) {
      T x = at(t);
      struct tm lt;
      localtime_r(&t, &lt);
      const int want = (int) (((lt.tm_gmtoff / 60) % 1440 + 1440) % 1440);
      if (off_of(x) != want || yaml_off(x) != want) bad++;
    }
    printf("offset helper vs tz database: %ld samples, %ld mismatches\n", n, bad);
    if (bad) failures++;
    printf("  EDT -> %d (UTC%+.1f), EST -> %d (UTC%+.1f)\n", off_of(at(utc(2026, 7, 1, 12, 0))),
           dl::offset_hours(off_of(at(utc(2026, 7, 1, 12, 0)))), off_of(at(utc(2026, 12, 1, 12, 0))),
           dl::offset_hours(off_of(at(utc(2026, 12, 1, 12, 0)))));
  }

  // Fall back: 2026-11-01 02:00 EDT -> 01:00 EST (06:00 UTC).
  const time_t fb_from = utc(2026, 11, 1, 3, 0), fb_to = utc(2026, 11, 1, 11, 30), fb_noon = utc(2026, 11, 1, 17, 0);
  run("FALL BACK 2026-11-01", fb_from, fb_to, fb_noon, true);
  run("FALL BACK 2026-11-01", fb_from, fb_to, fb_noon, false);
  // Spring forward: 2027-03-14 02:00 EST -> 03:00 EDT (07:00 UTC).
  const time_t sf_from = utc(2027, 3, 14, 4, 0), sf_to = utc(2027, 3, 14, 10, 30), sf_noon = utc(2027, 3, 14, 16, 0);
  run("SPRING FORWARD 2027-03-14", sf_from, sf_to, sf_noon, true);
  run("SPRING FORWARD 2027-03-14", sf_from, sf_to, sf_noon, false);

  // Push Light Phase Now, pressed at 08:00 EST on 2026-11-01 under the OLD
  // tick (the field case: the button alone re-sent 07:08-18:32).
  {
    printf("\nPush Light Phase Now at 08:00 EST 2026-11-01 (75 gal day computed at 00:00 EDT)\n");
    for (int fixed = 0; fixed <= 1; fixed++) {
      Board75 b; b.fixed = fixed;
      T mid_edt = at(utc(2026, 11, 1, 4, 0));
      b.day = compute(mid_edt);
      b.push(mid_edt);
      b.button(at(utc(2026, 11, 1, 13, 0)));
      check("75gal", fixed ? "NEW" : "OLD", b.lamp, fb_noon, fixed);
    }
  }

  printf("\n%s (%d failure%s)\n", failures ? "FAILED" : "PASSED", failures, failures == 1 ? "" : "s");
  return failures ? 1 : 0;
}
