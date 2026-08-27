#pragma once

#include "esphome/core/component.h"
#include "esphome/components/web_server_base/web_server_base.h"

namespace esphome {
namespace tank_webui {

/// Serves the custom web UI's script and stylesheet from this device.
///
/// The point of this component is delivery, not rendering. ESPHome's
/// `js_include` reads a file from the ESPHome config directory at build
/// time, and remote packages fetch only the YAML listed in `files:` -- so
/// a git-driven install could never supply it, and the assets had to be
/// hand-copied and hand-updated.
///
/// External *components*, however, are fetched from git in full. Putting
/// the assets inside this component and serving them over routes the
/// browser can reach turns `js_url: "/tank.js"` into a device-local URL:
/// no CDN, no internet, no copied files, and `git push` is the whole
/// update path again.
class TankWebUI : public Component, public AsyncWebHandler {
 public:
  void set_base(web_server_base::WebServerBase *base) { this->base_ = base; }
  void set_js(const char *js) { this->js_ = js; }
  void set_css(const char *css) { this->css_ = css; }

  void setup() override { this->base_->add_handler(this); }
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::WIFI; }

  bool canHandle(AsyncWebServerRequest *request) const override;
  void handleRequest(AsyncWebServerRequest *request) override;

 protected:
  web_server_base::WebServerBase *base_{nullptr};
  const char *js_{""};
  const char *css_{""};
};

}  // namespace tank_webui
}  // namespace esphome
