#pragma once

#include "esphome/core/component.h"
#include "esphome/components/display/display.h"

namespace esphome {
namespace panel_canvas {

/// A Display that draws into RAM. See __init__.py.
class PanelCanvas : public display::Display {
 public:
  void set_size(int w, int h) {
    this->w_ = w;
    this->h_ = h;
  }
  void setup() override;
  void update() override {}
  // Before the display: the buffer must exist when pages first draw.
  float get_setup_priority() const override { return setup_priority::HARDWARE + 1.0f; }

  display::DisplayType get_display_type() override { return display::DISPLAY_TYPE_COLOR; }
  void draw_pixel_at(int x, int y, Color color) override;
  void draw_pixels_at(int x_start, int y_start, int w, int h, const uint8_t *ptr, display::ColorOrder order,
                      display::ColorBitness bitness, bool big_endian, int x_offset, int y_offset, int x_pad) override;

  /// Copy every row changed since the last blit to `real`, in one call.
  void blit(display::Display &real);

 protected:
  int get_width_internal() override { return this->w_; }
  int get_height_internal() override { return this->h_; }
  void touch_rows_(int y0, int y1) {
    if (y0 < this->dirty_y0_)
      this->dirty_y0_ = y0;
    if (y1 > this->dirty_y1_)
      this->dirty_y1_ = y1;
  }

  int w_{800}, h_{480};
  uint16_t *buf_{nullptr};
  // Rows [dirty_y0_, dirty_y1_) changed since the last blit.
  int dirty_y0_{1 << 30}, dirty_y1_{0};
};

}  // namespace panel_canvas
}  // namespace esphome
