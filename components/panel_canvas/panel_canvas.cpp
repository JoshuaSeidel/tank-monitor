#include "panel_canvas.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"

#include <esp_heap_caps.h>
#include <algorithm>
#include <cstring>

namespace esphome {
namespace panel_canvas {

static const char *const TAG = "panel_canvas";

void PanelCanvas::setup() {
  this->buf_ = static_cast<uint16_t *>(
      heap_caps_malloc((size_t) this->w_ * this->h_ * 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (this->buf_ == nullptr) {
    ESP_LOGE(TAG, "No PSRAM for a %dx%d canvas", this->w_, this->h_);
    this->mark_failed();
    return;
  }
  memset(this->buf_, 0, (size_t) this->w_ * this->h_ * 2);
}

// Stored exactly as the RGB panel's framebuffer wants it (the board file's
// frect convention): RGB565, big-endian byte order.
void PanelCanvas::draw_pixel_at(int x, int y, Color color) {
  if (this->buf_ == nullptr || x < 0 || y < 0 || x >= this->w_ || y >= this->h_)
    return;
  this->buf_[y * this->w_ + x] = convert_big_endian(display::ColorUtil::color_to_565(color));
  this->touch_rows_(y, y + 1);
}

void PanelCanvas::draw_pixels_at(int x_start, int y_start, int w, int h, const uint8_t *ptr,
                                 display::ColorOrder order, display::ColorBitness bitness, bool big_endian,
                                 int x_offset, int y_offset, int x_pad) {
  if (this->buf_ == nullptr || w <= 0 || h <= 0)
    return;
  if (bitness != display::COLOR_BITNESS_565 || order != display::COLOR_ORDER_RGB || !big_endian) {
    display::Display::draw_pixels_at(x_start, y_start, w, h, ptr, order, bitness, big_endian, x_offset, y_offset,
                                     x_pad);
    return;
  }
  const int stride = x_offset + w + x_pad;
  for (int row = 0; row < h; row++) {
    const int y = y_start + row;
    if (y < 0 || y >= this->h_)
      continue;
    int x0 = x_start, n = w, src = (row + y_offset) * stride + x_offset;
    if (x0 < 0) {
      src -= x0;
      n += x0;
      x0 = 0;
    }
    if (x0 + n > this->w_)
      n = this->w_ - x0;
    if (n <= 0)
      continue;
    memcpy(this->buf_ + y * this->w_ + x0, ptr + src * 2, n * 2);
  }
  this->touch_rows_(std::max(0, y_start), std::min(this->h_, y_start + h));
}

void PanelCanvas::blit(display::Display &real) {
  if (this->buf_ == nullptr || this->dirty_y1_ <= this->dirty_y0_)
    return;
  // Whole rows are contiguous in the buffer, so the changed band goes out
  // as one esp_lcd_panel_draw_bitmap -- a single copy into the framebuffer.
  real.draw_pixels_at(0, this->dirty_y0_, this->w_, this->dirty_y1_ - this->dirty_y0_,
                      reinterpret_cast<const uint8_t *>(this->buf_ + this->dirty_y0_ * this->w_),
                      display::COLOR_ORDER_RGB, display::COLOR_BITNESS_565, true, 0, 0, 0);
  this->dirty_y0_ = 1 << 30;
  this->dirty_y1_ = 0;
}

}  // namespace panel_canvas
}  // namespace esphome
