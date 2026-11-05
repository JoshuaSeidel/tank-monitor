// Host test of the 75's "is it the lamp or the sensor's view" check.
//
//   c++ -std=c++17 -O2 -o /tmp/light_view_test tools/light_view_test.cpp && /tmp/light_view_test
//   (run from the repo root; it reads packages/light_wrgb2.yaml)
//
// Field bug, 2026-11-05: a fish feeder in front of the sensor pod cut every
// channel ~80% in one sample (NIR 14 -> 3, lamp lux 585 -> 135). The board
// called the lamp dark and re-pushed it four times; each push blanks the
// lamp for 20-90 s. The minute tick in light_wrgb2.yaml now classifies a
// mismatch with view_change() first. The lambda below is that code; main()
// checks the YAML carries it word for word (whitespace aside), then runs it
// through the cases that matter.
#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

// ---- verbatim from packages/light_wrgb2.yaml (minute tick) ----
auto view_change = [](float nir_ref, float nir, float full_ref, float full) -> int {
  if (std::isnan(nir_ref) || std::isnan(nir) || std::isnan(full_ref) || std::isnan(full) ||
      nir_ref <= 0.0f || full_ref <= 0.0f || full < 0.0f) return 0;
  const float rn = nir / nir_ref, rl = full / full_ref;
  const bool together = rl >= 0.5f * rn && rl <= 2.0f * rn;   // same factor, within 2x
  if (nir_ref >= 6.0f && nir >= 1.0f && rn <= 0.5f && together) return -1;
  if (nir >= 6.0f && rn >= 2.0f && together) return 1;
  return 0;
};
// ---- end verbatim ----

static int failures = 0;

static void expect(const char *what, float nr, float n, float fr, float f, int want) {
  const int got = view_change(nr, n, fr, f);
  const bool ok = got == want;
  if (!ok) failures++;
  printf("%s  %-58s NIR %5.1f -> %5.1f  lamp %6.0f -> %6.0f  => %+d (want %+d)\n",
         ok ? "ok  " : "FAIL", what, nr, n, fr, f, got, want);
}

// The text from "auto view_change" to the first line that is just "};",
// all whitespace removed.
static std::string block(const std::string &src) {
  const size_t a = src.find("auto view_change = [](");
  if (a == std::string::npos) return "";
  const size_t b = src.find("\n", src.find("return 0;\n", src.find("return 1;", a)));
  const size_t e = src.find("};", b);
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
  const std::string yaml = slurp("packages/light_wrgb2.yaml");
  const std::string self = slurp(__FILE__);
  if (yaml.empty() || self.empty()) {
    printf("run from the repo root (needs packages/light_wrgb2.yaml and %s)\n", __FILE__);
    return 2;
  }
  const std::string by = block(yaml), bs = block(self);
  const bool same = !by.empty() && by == bs;
  printf("%s  light_wrgb2.yaml carries the tested view_change() verbatim\n", same ? "ok  " : "FAIL");
  if (!same) failures++;

  const float N = NAN;
  // The incident and its variants: the view is cut, NIR and lamp together.
  expect("2026-11-05 feeder in front of the pod", 14, 3, 585, 135, -1);
  expect("half covered", 14, 7, 585, 300, -1);
  expect("pod knocked askew, lamp side cut more (2x off)", 14, 6, 585, 130, -1);
  // A dark lamp takes only its own light: NIR stays -> ask the lamp.
  expect("lamp really dark, daylight steady", 14, 14, 585, 10, 0);
  expect("lamp really dark, room LEDs leak a little", 14, 13, 585, 40, 0);
  expect("lamp really dark under a passing cloud", 14, 6, 585, 10, 0);
  // Clouds alone move NIR, not the (unmixed) lamp lux.
  expect("cloud, lamp fine", 14, 5, 585, 585, 0);
  expect("sun out, lamp fine", 6, 20, 585, 585, 0);
  // No daylight to tell by: guard 2 (ask the lamp) decides.
  expect("fully covered: NIR to 0", 14, 0, 585, 0, 0);
  expect("night / blinds down: NIR ~0 before", 2, 0, 585, 100, 0);
  expect("NIR under 6 before", 5, 1, 585, 120, 0);
  expect("no view learned yet", N, 3, N, 135, 0);
  expect("no NIR reading", 14, N, 585, 135, 0);
  expect("level near 0: no lamp-at-full figure", 14, 3, 585, N, 0);
  // Opposite direction: uncovered after a level learned while blocked.
  expect("uncovered after a relearn while blocked", 3, 14, 135, 585, 1);
  expect("uncovered, NIR only to 5 (too little to judge)", 2, 5, 135, 585, 0);
  // A real overshoot (2026-10-19, ~2.3x) with steady daylight stays "over".
  expect("lamp overshoot, NIR steady", 14, 14, 585, 1345, 0);
  expect("known blind spot: overshoot as the sun comes out -> relearns", 4, 16, 585, 1345, 1);

  printf("\n%s (%d failure%s)\n", failures ? "FAILED" : "all passed", failures, failures == 1 ? "" : "s");
  return failures ? 1 : 0;
}
