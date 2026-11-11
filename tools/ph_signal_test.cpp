// Host test of Water pH's "is there a probe signal at all" check.
//
//   c++ -std=c++17 -O2 -o /tmp/ph_signal_test tools/ph_signal_test.cpp && /tmp/ph_signal_test
//   (run from the repo root; it reads packages/ph.yaml)
//
// Field bug, 2026-11-09/10: the 75 gal's pH front-end read 0.000 V for ~29 h
// while Home Assistant showed Water pH 7.34 for 23.6 h of it, and the CO2
// schedule ran gas against that number. The transport half of the fix is
// publish_nan_as_none (packages/base.yaml); the device half is that
// packages/ph.yaml now refuses a voltage outside the front-end's band, or
// one that has not been refreshed for 5 minutes, before any pH maths. The
// lambda below is that check; main() confirms the YAML carries it word for
// word (whitespace aside), then runs it through the cases that matter.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

// ---- verbatim from packages/ph.yaml (water_ph lambda) ----
auto ph_signal_ok = [](float v, uint32_t age_ms) -> bool {
  if (std::isnan(v)) return false;
  if (v < 0.05f || v > 3.0f) return false;   // front-end dead or railed
  if (age_ms > 300000) return false;         // no in-band sample for 5 min
  return true;
};
// ---- end verbatim ----

static int failures = 0;

static void expect(const char *what, float v, uint32_t age_ms, bool want) {
  const bool got = ph_signal_ok(v, age_ms);
  const bool ok = got == want;
  if (!ok) failures++;
  printf("%s  %-52s %6.3f V  age %7u ms  => %s (want %s)\n", ok ? "ok  " : "FAIL", what, v,
         (unsigned) age_ms, got ? "signal" : "none  ", want ? "signal" : "none");
}

// The text from "auto ph_signal_ok = [](" to the first "};" after it, all
// whitespace removed.
static std::string block(const std::string &src) {
  const size_t a = src.find("auto ph_signal_ok = [](");
  if (a == std::string::npos) return "";
  const size_t e = src.find("};", a);
  if (e == std::string::npos) return "";
  std::string out;
  for (size_t i = a; i < e + 2; i++)
    if (!isspace((unsigned char) src[i])) out += src[i];
  return out;
}

static std::string slurp(const char *path) {
  std::ifstream f(path);
  if (!f) return "";
  std::stringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

int main() {
  const std::string yaml = slurp("packages/ph.yaml");
  const std::string self = slurp(__FILE__);
  if (yaml.empty() || self.empty()) {
    printf("run from the repo root (needs packages/ph.yaml and %s)\n", __FILE__);
    return 2;
  }
  const std::string by = block(yaml), bs = block(self);
  const bool same = !by.empty() && by == bs;
  printf("%s  ph.yaml carries the tested ph_signal_ok() verbatim\n", same ? "ok  " : "FAIL");
  if (!same) failures++;

  // The incident: front-end output at 0 V, still being refreshed.
  expect("2026-11-09 front-end at 0.000 V", 0.000f, 1000, false);
  expect("ADC noise floor on a dead front-end", 0.030f, 1000, false);
  expect("pin pulled to the 3.3 V rail (12 dB reads ~3.1 V)", 3.10f, 1000, false);
  expect("never read", NAN, 0, false);
  // Real readings: tank, every buffer, both ends of the electrode's range.
  expect("tank at pH ~7.3", 1.47f, 5000, true);
  expect("9.18 buffer", 1.148f, 5000, true);
  expect("6.86 buffer", 1.548f, 5000, true);
  expect("4.00 buffer", 2.04f, 5000, true);
  expect("pH 14 (still ~0.4 V)", 0.40f, 5000, true);
  expect("pH 0 (~2.8 V)", 2.80f, 5000, true);
  expect("band edge, low", 0.05f, 5000, true);
  expect("band edge, high", 3.00f, 5000, true);
  // Freshness: a good-looking value the source stopped refreshing.
  expect("in band, 4 min since last in-band sample", 1.47f, 240000, true);
  expect("in band, exactly 5 min", 1.47f, 300000, true);
  expect("in band, 5 min 1 ms -- source stopped", 1.47f, 300001, false);
  expect("in band, a day stale", 1.47f, 86400000u, false);

  printf("\n%s (%d failure%s)\n", failures ? "FAILED" : "all passed", failures, failures == 1 ? "" : "s");
  return failures ? 1 : 0;
}
