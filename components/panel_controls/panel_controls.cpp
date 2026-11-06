#include "panel_controls.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"

#include "esphome/core/helpers.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace esphome {
namespace panel_controls {

static const char *const TAG = "panel_controls";

// The board file's palette.
static const Color BG(7, 11, 15), CARD(26, 32, 40), HAIR(42, 50, 60), TRACK(30, 37, 46);
static const Color INK(255, 255, 255), INK2(185, 194, 204), MUTED(111, 123, 136);
static const Color BLUE(57, 135, 229), HEAT(255, 138, 92), GOOD(12, 163, 12), BAD(208, 59, 59);
static const Color AQUA(25, 158, 112), AMBER(255, 176, 32), BTN(42, 52, 64);

static const float GH_PER_DEG = 17.86f;  // ppm CaCO3 per German degree

// Water-test steppers: the steps a drop or strip kit actually reads.
struct TestField {
  const char *label;
  const char *unit;
  const float *steps;
  int n;
  int start;  // index of the first value a "+" from not-tested lands on
  const char *fmt;
};
static const float PH_STEPS[] = {6.0f, 6.2f, 6.4f, 6.6f, 6.8f, 7.0f, 7.2f, 7.4f, 7.6f, 7.8f, 8.0f, 8.2f, 8.4f, 8.8f};
static const float NH_STEPS[] = {0.0f, 0.25f, 0.5f, 1.0f, 2.0f, 4.0f, 8.0f};
static const float NO2_STEPS[] = {0.0f, 0.25f, 0.5f, 1.0f, 2.0f, 5.0f};
static const float NO3_STEPS[] = {0.0f, 5.0f, 10.0f, 20.0f, 40.0f, 80.0f, 160.0f};
static const float DEG_STEPS[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20};
static const TestField FIELDS[6] = {
    {"PH", "", PH_STEPS, 14, 5, "%.1f"},
    {"AMMONIA", "ppm", NH_STEPS, 7, 0, "%.2f"},
    {"NITRITE", "ppm", NO2_STEPS, 6, 0, "%.2f"},
    {"NITRATE", "ppm", NO3_STEPS, 7, 0, "%.0f"},
    {"GH", "drops", DEG_STEPS, 17, 6, "%.0f"},
    {"KH", "drops", DEG_STEPS, 17, 4, "%.0f"},
};

// ---------------------------------------------------------------- values

float PanelControls::num_(const std::string &name) {
  auto it = this->pending_num_.find(name);
  return it != this->pending_num_.end() ? it->second : this->archive_->setting(name);
}
std::string PanelControls::text_(const std::string &name) {
  auto it = this->pending_text_.find(name);
  return it != this->pending_text_.end() ? it->second : this->archive_->setting_text(name);
}
bool PanelControls::on_(const std::string &name) {
  auto it = this->pending_on_.find(name);
  return it != this->pending_on_.end() ? it->second : this->archive_->setting_on(name);
}

void PanelControls::after_command_() {
  this->pending_version_ = this->archive_->settings_version();
  this->archive_->request_settings(1500);
  this->force_ = true;
}

void PanelControls::set_num_(const std::string &name, float v) {
  char b[24];
  snprintf(b, sizeof(b), "%g", v);
  if (!this->archive_->send_command("N," + name + "," + b)) {
    this->message_ = "Controller not connected";
    this->message_ms_ = millis();
    return;
  }
  this->pending_num_[name] = v;
  this->after_command_();
}

void PanelControls::press_(const std::string &name) {
  if (!this->archive_->send_command("P," + name)) {
    this->message_ = "Controller not connected";
    this->message_ms_ = millis();
    return;
  }
  this->message_ = name + " sent";
  this->message_ms_ = millis();
  this->after_command_();
}

void PanelControls::set_switch_(const std::string &name, bool on) {
  if (!this->archive_->send_command("W," + name + (on ? ",1" : ",0"))) {
    this->message_ = "Controller not connected";
    this->message_ms_ = millis();
    return;
  }
  this->pending_on_[name] = on;
  this->after_command_();
}

void PanelControls::set_time_(const std::string &name, int minutes) {
  minutes = ((minutes % 1440) + 1440) % 1440;
  char b[12];
  snprintf(b, sizeof(b), "%02d:%02d:00", minutes / 60, minutes % 60);
  if (!this->archive_->send_command("M," + name + "," + b)) {
    this->message_ = "Controller not connected";
    this->message_ms_ = millis();
    return;
  }
  this->pending_text_[name] = b;
  this->after_command_();
}

static int minutes_of(const std::string &hms) {
  int h = 0, m = 0;
  if (sscanf(hms.c_str(), "%d:%d", &h, &m) != 2)
    return -1;
  return h * 60 + m;
}

// --------------------------------------------------------------- drawing

void PanelControls::frect_(display::Display &it, int x, int y, int w, int h, Color c) {
  if (w <= 0 || h <= 0)
    return;
  static uint16_t row[800];
  if (w > 800)
    w = 800;
  const uint16_t px = convert_big_endian(display::ColorUtil::color_to_565(c));
  for (int i = 0; i < w; i++)
    row[i] = px;
  for (int j = 0; j < h; j++)
    it.draw_pixels_at(x, y + j, w, 1, (const uint8_t *) row, display::COLOR_ORDER_RGB, display::COLOR_BITNESS_565,
                      true, 0, 0, 0);
}

void PanelControls::rr_(display::Display &it, int x, int y, int w, int h, int r, Color c) {
  this->frect_(it, x + r, y, w - 2 * r, h, c);
  this->frect_(it, x, y + r, w, h - 2 * r, c);
  it.filled_circle(x + r, y + r, r, c);
  it.filled_circle(x + w - r - 1, y + r, r, c);
  it.filled_circle(x + r, y + h - r - 1, r, c);
  it.filled_circle(x + w - r - 1, y + h - r - 1, r, c);
}

void PanelControls::button_(display::Display &it, int x, int y, int w, int h, const char *label,
                            display::BaseFont *f, Color fg, Color bg, std::function<void()> act) {
  this->rr_(it, x, y, w, h, 12, bg);
  it.print(x + w / 2, y + h / 2, f, fg, display::TextAlign::CENTER, label);
  // Hit area a little larger than the drawing: fingers, not styluses.
  this->buttons_[this->last_page_].push_back(Button{x - 6, y - 6, w + 12, h + 12, std::move(act)});
}

// A row: label and sub-line on the left, the value, and -/+ on the right.
void PanelControls::stepper_(display::Display &it, int x, int y, int w, const char *label, const std::string &value,
                             const std::string &sub, std::function<void()> minus, std::function<void()> plus,
                             const char *minus_label, const char *plus_label) {
  it.print(x + 16, y + 16, this->f_micro_, MUTED, display::TextAlign::CENTER_LEFT, label);
  it.print(x + 16, y + 50, this->f_big_, value == "--" ? MUTED : INK, display::TextAlign::CENTER_LEFT, value.c_str());
  if (!sub.empty())
    it.print(x + 16, y + 80, this->f_micro_, MUTED, display::TextAlign::CENTER_LEFT, sub.c_str());
  const bool small = strlen(minus_label) > 1;
  const int bw = small ? 72 : 64;
  if (minus)
    this->button_(it, x + w - 2 * bw - 26, y + 22, bw, 56, minus_label, this->f_med_, INK, BTN, std::move(minus));
  if (plus)
    this->button_(it, x + w - bw - 14, y + 22, bw, 56, plus_label, this->f_med_, INK, BTN, std::move(plus));
}

void PanelControls::chrome_(display::Display &it, const char *title, int dot_index, int dot_count) {
  this->frect_(it, 0, 0, 800, 480, BG);
  it.print(20, 20, this->f_small_, INK2, display::TextAlign::CENTER_LEFT, title);
  if (!this->link_)
    it.print(400, 20, this->f_micro_, BAD, display::TextAlign::CENTER, "CONTROLLER NOT CONNECTED");
  this->frect_(it, 0, 432, 800, 1, HAIR);
  it.print(20, 457, this->f_micro_, MUTED, display::TextAlign::CENTER_LEFT, "< BACK");
  it.print(560, 457, this->f_micro_, MUTED, display::TextAlign::CENTER_RIGHT, "NEXT >");
  // Page dots, right-aligned like the board's pages.
  int x = 776 - (dot_count - 1) * 18;
  for (int k = 0; k < dot_count; k++, x += 18) {
    if (k == dot_index)
      this->frect_(it, x - 9, 454, 18, 6, BLUE);
    else
      it.filled_circle(x, 457, 3, TRACK);
  }
  if (!this->message_.empty() && millis() - this->message_ms_ < 8000)
    it.print(300, 457, this->f_micro_, AMBER, display::TextAlign::CENTER, this->message_.c_str());
}

static std::string fmt(const char *f, float v) {
  if (std::isnan(v))
    return "--";
  char b[24];
  snprintf(b, sizeof(b), f, v);
  return b;
}

void PanelControls::page_settings_(display::Display &it) {
  this->rr_(it, 18, 46, 372, 380, 15, CARD);
  this->rr_(it, 410, 46, 372, 380, 15, CARD);

  const float sp = this->num_("Target Temperature");
  this->stepper_(it, 18, 52, 372, "TARGET TEMPERATURE", fmt("%.1f\xC2\xB0", sp),
                 std::isnan(this->temp_f_) ? "water --" : "water " + fmt("%.1f\xC2\xB0", this->temp_f_),
                 [this, sp]() { if (!std::isnan(sp)) this->set_num_("Target Temperature", sp - 0.5f); },
                 [this, sp]() { if (!std::isnan(sp)) this->set_num_("Target Temperature", sp + 0.5f); });
  const float off = this->num_("Cal Temperature Offset");
  this->stepper_(it, 18, 145, 372, "PROBE OFFSET", fmt("%+.1f\xC2\xB0", off), "against a trusted thermometer",
                 [this, off]() { if (!std::isnan(off)) this->set_num_("Cal Temperature Offset", off - 0.1f); },
                 [this, off]() { if (!std::isnan(off)) this->set_num_("Cal Temperature Offset", off + 0.1f); });
  const float watts = this->num_("Heater Power");
  this->stepper_(it, 18, 238, 372, "HEATER WATTS", fmt("%.0f", watts), "from the heater's label",
                 [this, watts]() { if (!std::isnan(watts)) this->set_num_("Heater Power", std::max(0.0f, watts - 5.0f)); },
                 [this, watts]() { if (!std::isnan(watts)) this->set_num_("Heater Power", watts + 5.0f); });
  const float db = this->num_("Fan Deadband");
  this->stepper_(it, 18, 331, 372, "FAN STARTS ABOVE TARGET BY", fmt("%.2f\xC2\xB0", db), "",
                 [this, db]() { if (!std::isnan(db)) this->set_num_("Fan Deadband", std::max(0.0f, db - 0.05f)); },
                 [this, db]() { if (!std::isnan(db)) this->set_num_("Fan Deadband", db + 0.05f); });

  // CO2 schedule. Turning it on is two taps: there is no pH probe watching.
  const bool sched = this->on_("CO2 Schedule");
  it.print(426, 68, this->f_micro_, MUTED, display::TextAlign::CENTER_LEFT, "CO2 SCHEDULE");
  it.print(426, 102, this->f_small_, sched ? AQUA : MUTED, display::TextAlign::CENTER_LEFT,
           sched ? "ON - runs daily" : "OFF");
  const bool armed = this->armed_ == "co2" && millis() - this->armed_ms_ < 6000;
  this->button_(it, 640, 74, 128, 56, sched ? "TURN OFF" : (armed ? "TAP AGAIN" : "TURN ON"), this->f_small_,
                INK, sched ? BTN : (armed ? Color(120, 80, 10) : Color(14, 80, 58)), [this, sched]() {
                  if (sched) {
                    this->set_switch_("CO2 Schedule", false);
                  } else if (this->armed_ == "co2" && millis() - this->armed_ms_ < 6000) {
                    this->armed_.clear();
                    this->set_switch_("CO2 Schedule", true);
                  } else {
                    this->armed_ = "co2";
                    this->armed_ms_ = millis();
                    this->force_ = true;
                  }
                });
  auto time_row = [&](int y, const char *label, const char *name) {
    const int m = minutes_of(this->text_(name));
    char v[16];
    if (m < 0)
      snprintf(v, sizeof(v), "--");
    else
      snprintf(v, sizeof(v), "%02d:%02d", m / 60, m % 60);
    const std::string n = name;
    this->stepper_(it, 410, y, 372, label, v, "15 minute steps",
                   [this, n, m]() { if (m >= 0) this->set_time_(n, m - 15); },
                   [this, n, m]() { if (m >= 0) this->set_time_(n, m + 15); });
  };
  time_row(145, "CO2 ON AT", "CO2 On At");
  time_row(238, "CO2 OFF AT", "CO2 Off At");
  time_row(331, "BUBBLER BACK ON AT", "Bubbler On At");
}

void PanelControls::page_calibrate_(display::Display &it) {
  this->rr_(it, 18, 46, 372, 380, 15, CARD);
  this->rr_(it, 410, 46, 372, 380, 15, CARD);

  // ---- TDS ----
  const float std_ppm = this->num_("Cal TDS Standard");
  auto step = [this, std_ppm](float d) {
    if (!std::isnan(std_ppm))
      this->set_num_("Cal TDS Standard", std::max(1.0f, std_ppm + d));
  };
  this->stepper_(it, 18, 52, 372, "TDS STANDARD, PPM", fmt("%.0f", std_ppm), "the number on the bottle",
                 [step]() { step(-10); }, [step]() { step(10); }, "-10", "+10");
  it.print(34, 195, this->f_micro_, MUTED, display::TextAlign::CENTER_LEFT, "FINE ADJUST");
  this->stepper_(it, 18, 145, 372, "", "", "", [step]() { step(-1); }, [step]() { step(1); }, "-1", "+1");
  const float k = this->num_("Cal TDS K Factor");
  it.print(34, 262, this->f_micro_, MUTED, display::TextAlign::CENTER_LEFT, "PROBE READS NOW");
  it.print(34, 296, this->f_big_, std::isnan(this->tds_raw_) ? MUTED : INK, display::TextAlign::CENTER_LEFT,
           fmt("%.0f", this->tds_raw_).c_str());
  it.print(200, 302, this->f_small_, MUTED, display::TextAlign::CENTER_LEFT,
           ("ppm   K " + fmt("%.2f", k)).c_str());
  const bool armed = this->armed_ == "tds" && millis() - this->armed_ms_ < 6000;
  char lbl[40];
  snprintf(lbl, sizeof(lbl), armed ? "TAP AGAIN: SET TO %.0f" : "CALIBRATE TDS", std_ppm);
  this->button_(it, 34, 340, 340, 64, lbl, this->f_small_, INK, armed ? Color(120, 80, 10) : Color(14, 80, 58),
                [this]() {
                  if (this->armed_ == "tds" && millis() - this->armed_ms_ < 6000) {
                    this->armed_.clear();
                    this->press_("Calibrate TDS");
                  } else {
                    this->armed_ = "tds";
                    this->armed_ms_ = millis();
                    this->force_ = true;
                  }
                });

  // ---- pH ----
  it.print(426, 68, this->f_micro_, MUTED, display::TextAlign::CENTER_LEFT, "PH PROBE");
  if (std::isnan(this->ph_) && std::isnan(this->num_("Cal pH High Value"))) {
    it.print(426, 110, this->f_small_, MUTED, display::TextAlign::CENTER_LEFT, "No pH probe fitted.");
    it.print(426, 140, this->f_micro_, MUTED, display::TextAlign::CENTER_LEFT,
             "Wire its output to D3: it reads by itself.");
    return;
  }
  it.print(426, 102, this->f_big_, std::isnan(this->ph_) ? MUTED : INK, display::TextAlign::CENTER_LEFT,
           fmt("%.2f", this->ph_).c_str());
  it.print(560, 108, this->f_small_, MUTED, display::TextAlign::CENTER_LEFT, "now");
  const float hi = this->num_("Cal pH High Value"), lo = this->num_("Cal pH Low Value");
  this->stepper_(it, 410, 145, 372, "HIGH BUFFER", fmt("%.2f", hi), "",
                 [this, hi]() { if (!std::isnan(hi)) this->set_num_("Cal pH High Value", hi - 0.01f); },
                 [this, hi]() { if (!std::isnan(hi)) this->set_num_("Cal pH High Value", hi + 0.01f); });
  this->stepper_(it, 410, 238, 372, "LOW BUFFER", fmt("%.2f", lo), "",
                 [this, lo]() { if (!std::isnan(lo)) this->set_num_("Cal pH Low Value", lo - 0.01f); },
                 [this, lo]() { if (!std::isnan(lo)) this->set_num_("Cal pH Low Value", lo + 0.01f); });
  auto capture = [this](const char *key, const char *button) {
    if (this->armed_ == key && millis() - this->armed_ms_ < 6000) {
      this->armed_.clear();
      this->press_(button);
    } else {
      this->armed_ = key;
      this->armed_ms_ = millis();
      this->force_ = true;
    }
  };
  const bool ah = this->armed_ == "phhi" && millis() - this->armed_ms_ < 6000;
  const bool al = this->armed_ == "phlo" && millis() - this->armed_ms_ < 6000;
  this->button_(it, 426, 340, 164, 64, ah ? "TAP AGAIN" : "CAPTURE HIGH", this->f_small_, INK,
                ah ? Color(120, 80, 10) : BTN, [capture]() { capture("phhi", "Capture High Point"); });
  this->button_(it, 602, 340, 164, 64, al ? "TAP AGAIN" : "CAPTURE LOW", this->f_small_, INK,
                al ? Color(120, 80, 10) : BTN, [capture]() { capture("phlo", "Capture Low Point"); });
}

void PanelControls::page_test_(display::Display &it) {
  for (int i = 0; i < 6; i++) {
    const int col = i % 3, row = i / 3;
    const int x = 18 + col * 258, y = 46 + row * 150;
    this->rr_(it, x, y, 248, 140, 15, CARD);
    const TestField &f = FIELDS[i];
    const float v = this->entry_[i];
    it.print(x + 16, y + 20, this->f_micro_, MUTED, display::TextAlign::CENTER_LEFT, f.label);
    it.print(x + 16, y + 62, this->f_big_, std::isnan(v) ? MUTED : INK, display::TextAlign::CENTER_LEFT,
             fmt(f.fmt, v).c_str());
    it.print(x + 16, y + 94, this->f_micro_, MUTED, display::TextAlign::CENTER_LEFT,
             std::isnan(v) ? "not tested" : f.unit);
    auto idx = [f, v]() {
      int best = 0;
      for (int k = 0; k < f.n; k++)
        if (fabsf(f.steps[k] - v) < fabsf(f.steps[best] - v))
          best = k;
      return best;
    };
    this->button_(it, x + 16, y + 102 - 0, 100, 30, "-", this->f_med_, INK, BTN, [this, i, idx, f]() {
      if (std::isnan(this->entry_[i]))
        return;
      const int k = idx();
      this->entry_[i] = k == 0 ? NAN : f.steps[k - 1];  // below the bottom step: not tested
      this->force_ = true;
    });
    this->button_(it, x + 132, y + 102, 100, 30, "+", this->f_med_, INK, BTN, [this, i, idx, f]() {
      this->entry_[i] = std::isnan(this->entry_[i]) ? f.steps[f.start] : f.steps[std::min(idx() + 1, f.n - 1)];
      this->force_ = true;
    });
  }
  // Save / clear, and how old the last saved test is.
  char last[48] = "No test logged yet";
  if (this->test_stamp_ > 0 && this->time_->now().is_valid()) {
    const uint32_t age = (uint32_t) this->time_->now().timestamp - this->test_stamp_;
    if (age < 3600)
      snprintf(last, sizeof(last), "Last test %u min ago", (unsigned) (age / 60));
    else if (age < 172800)
      snprintf(last, sizeof(last), "Last test %u h ago", (unsigned) (age / 3600));
    else
      snprintf(last, sizeof(last), "Last test %u days ago", (unsigned) (age / 86400));
  }
  it.print(34, 372, this->f_small_, MUTED, display::TextAlign::CENTER_LEFT, last);
  this->button_(it, 452, 348, 140, 56, "CLEAR", this->f_small_, INK, BTN, [this]() {
    for (float &e : this->entry_)
      e = NAN;
    this->force_ = true;
  });
  this->button_(it, 606, 348, 160, 56, "SAVE TEST", this->f_small_, INK, Color(14, 80, 58), [this]() {
    bool any = false;
    for (float e : this->entry_)
      any = any || !std::isnan(e);
    if (!any) {
      this->message_ = "Nothing entered";
      this->message_ms_ = millis();
      this->force_ = true;
      return;
    }
    auto out = [](float v, float scale) { return std::isnan(v) ? -999.0f : v * scale; };
    char b[96];
    snprintf(b, sizeof(b), "X,%.2f,%.2f,%.2f,%.1f,%.0f,%.0f", out(this->entry_[0], 1), out(this->entry_[1], 1),
             out(this->entry_[2], 1), out(this->entry_[3], 1), out(this->entry_[4], GH_PER_DEG),
             out(this->entry_[5], GH_PER_DEG));
    if (this->archive_->send_command(b)) {
      for (float &e : this->entry_)
        e = NAN;
      this->message_ = "Test saved";
    } else {
      this->message_ = "Controller not connected - not saved";
    }
    this->message_ms_ = millis();
    this->force_ = true;
  });
}

// Everything a page shows, as text: the page repaints only when it changes.
std::string PanelControls::signature_(int page) {
  char b[160];
  const bool msg = !this->message_.empty() && millis() - this->message_ms_ < 8000;
  const bool armed = !this->armed_.empty() && millis() - this->armed_ms_ < 6000;
  snprintf(b, sizeof(b), "%d|%u|%d|%s|%s|%.1f|%.0f|%.2f|%u", page, (unsigned) this->archive_->settings_version(),
           this->link_ ? 1 : 0, msg ? this->message_.c_str() : "", armed ? this->armed_.c_str() : "", this->temp_f_,
           this->tds_raw_, this->ph_, (unsigned) (this->test_stamp_ / 60));
  return b;
}

void PanelControls::draw(display::Display &it, int page, int dot_index, int dot_count, bool &dirty) {
  if (page < 0 || page > 2)
    return;
  // The controller's copy has caught up with what was sent: drop the
  // optimistic values and show its own.
  if (!this->pending_num_.empty() || !this->pending_text_.empty() || !this->pending_on_.empty()) {
    if (this->archive_->settings_version() != this->pending_version_) {
      this->pending_num_.clear();
      this->pending_text_.clear();
      this->pending_on_.clear();
    }
  }
  if (page != this->last_page_) {
    this->archive_->request_settings();  // a page just shown: fetch fresh values
  }
  const std::string sig = this->signature_(page);
  const bool full = dirty || this->force_ || page != this->last_page_ || sig != this->last_sig_[page];
  this->last_page_ = page;
  if (full) {
    dirty = false;
    this->force_ = false;
    this->last_sig_[page] = sig;
    this->buttons_[page].clear();
    static const char *const TITLES[3] = {"Settings", "Calibrate", "Water test"};
    this->chrome_(it, TITLES[page], dot_index, dot_count);
    if (page == SETTINGS)
      this->page_settings_(it);
    else if (page == CALIBRATE)
      this->page_calibrate_(it);
    else
      this->page_test_(it);
    this->last_minute_ = -1;
  }
  // The clock, on its own, once a minute.
  auto now = this->time_->now();
  const int minute = now.is_valid() ? now.hour * 60 + now.minute : -2;
  if (minute != this->last_minute_) {
    this->last_minute_ = minute;
    this->frect_(it, 700, 6, 90, 30, BG);
    if (now.is_valid())
      it.strftime(782, 20, this->f_small_, INK2, display::TextAlign::CENTER_RIGHT, "%H:%M", now);
    else
      it.print(782, 20, this->f_small_, MUTED, display::TextAlign::CENTER_RIGHT, "--:--");
  }
}

bool PanelControls::touch(int x, int y, int page) {
  if (page < 0 || page > 2)
    return false;
  for (auto &b : this->buttons_[page]) {
    if (x >= b.x && x < b.x + b.w && y >= b.y && y < b.y + b.h) {
      ESP_LOGD(TAG, "tap at %d,%d", x, y);
      b.act();
      this->force_ = true;
      return true;
    }
  }
  // A miss on a control page does nothing: a stray tap must not change page
  // half-way through a calibration.
  return true;
}

}  // namespace panel_controls
}  // namespace esphome
