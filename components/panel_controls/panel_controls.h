#pragma once

#include "esphome/core/component.h"
#include "esphome/components/display/display.h"
#include "esphome/components/font/font.h"
#include "esphome/components/time/real_time_clock.h"
#include "esphome/components/sd_archive/sd_archive.h"

#include <functional>
#include <map>
#include <string>
#include <vector>

namespace esphome {
namespace panel_controls {

/// Settings, calibration and water-test pages for the 4.3" panel. See
/// __init__.py. Drawing follows the board file's rules: one bulk row per
/// call (the driver is per-pixel otherwise) and no repaint unless something
/// on the page changed.
class PanelControls : public Component {
 public:
  enum Page { SETTINGS = 0, CALIBRATE = 1, TEST = 2 };

  void set_archive(sd_archive::SdArchive *a) { this->archive_ = a; }
  void set_time(time::RealTimeClock *t) { this->time_ = t; }
  void set_fonts(font::Font *micro, font::Font *small, font::Font *med, font::Font *big) {
    this->f_micro_ = micro;
    this->f_small_ = small;
    this->f_med_ = med;
    this->f_big_ = big;
  }
  float get_setup_priority() const override { return setup_priority::LATE; }

  /// What the panel already knows live from telemetry, handed in by the page
  /// lambda each frame: water temperature (degF), raw TDS, pH, the newest
  /// water test's time, and whether the controller link is up.
  void live(float temp_f, float tds_raw, float ph, uint32_t test_stamp, bool link) {
    this->temp_f_ = temp_f;
    this->tds_raw_ = tds_raw;
    this->ph_ = ph;
    this->test_stamp_ = test_stamp;
    this->link_ = link;
  }
  /// Draw `page` (index among all pages, and how many there are, for the dots).
  void draw(display::Display &it, int page, int dot_index, int dot_count, bool &dirty);
  /// A tap in the content area of `page`. True if this page took it.
  bool touch(int x, int y, int page);

 protected:
  struct Button {
    int x, y, w, h;
    std::function<void()> act;
  };

  // Settings and commands, by entity name.
  float num_(const std::string &name);
  std::string text_(const std::string &name);
  bool on_(const std::string &name);
  void set_num_(const std::string &name, float v);
  void press_(const std::string &name);
  void set_switch_(const std::string &name, bool on);
  void set_time_(const std::string &name, int minutes);
  void after_command_();

  // Drawing.
  void frect_(display::Display &it, int x, int y, int w, int h, Color c);
  void rr_(display::Display &it, int x, int y, int w, int h, int r, Color c);
  void button_(display::Display &it, int x, int y, int w, int h, const char *label, display::BaseFont *f, Color fg,
               Color bg, std::function<void()> act);
  void stepper_(display::Display &it, int x, int y, int w, const char *label, const std::string &value,
                const std::string &sub, std::function<void()> minus, std::function<void()> plus,
                const char *minus_label = "-", const char *plus_label = "+");
  void chrome_(display::Display &it, const char *title, int dot_index, int dot_count);
  void page_settings_(display::Display &it);
  void page_calibrate_(display::Display &it);
  void page_test_(display::Display &it);
  std::string signature_(int page);

  sd_archive::SdArchive *archive_{nullptr};
  time::RealTimeClock *time_{nullptr};
  font::Font *f_micro_{nullptr}, *f_small_{nullptr}, *f_med_{nullptr}, *f_big_{nullptr};

  float temp_f_{NAN}, tds_raw_{NAN}, ph_{NAN};
  uint32_t test_stamp_{0};
  bool link_{false};

  // Optimistic values: what was just sent, shown until the controller's
  // own copy comes back newer than the command.
  std::map<std::string, float> pending_num_;
  std::map<std::string, std::string> pending_text_;
  std::map<std::string, bool> pending_on_;
  uint32_t pending_version_{0};

  // A destructive button armed by its first tap; the second, within 6 s,
  // fires it. Empty when nothing is armed.
  std::string armed_;
  uint32_t armed_ms_{0};

  // Water test being entered: NAN = not tested.
  float entry_[6]{NAN, NAN, NAN, NAN, NAN, NAN};
  std::string message_;
  uint32_t message_ms_{0};

  std::vector<Button> buttons_[3];
  std::string last_sig_[3];
  int last_minute_{-1};
  int last_page_{-1};
  bool force_{false};
};

}  // namespace panel_controls
}  // namespace esphome
