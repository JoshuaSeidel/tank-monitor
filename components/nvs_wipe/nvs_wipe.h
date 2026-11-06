#pragma once

#include "esphome/core/component.h"

namespace esphome {
namespace nvs_wipe {

/// Erases NVS once per `generation` -- see __init__.py.
class NvsWipe : public Component {
 public:
  void set_generation(uint32_t g) { this->generation_ = g; }
  void setup() override;
  void dump_config() override;
  // Before every other component, so nothing has acted on stale settings by
  // the time the wipe restarts the board. Preferences are already loaded by
  // then; the restart is what drops them.
  float get_setup_priority() const override { return 5000.0f; }

 protected:
  uint32_t generation_{1};
  uint32_t stored_{0};
};

}  // namespace nvs_wipe
}  // namespace esphome
