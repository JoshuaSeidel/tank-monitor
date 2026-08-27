#include "tank_webui.h"
#include "esphome/core/log.h"

namespace esphome {
namespace tank_webui {

static const char *const TAG = "tank_webui";

bool TankWebUI::canHandle(AsyncWebServerRequest *request) const {
  return request->method() == HTTP_GET &&
         (request->url() == "/tank.js" || request->url() == "/tank.css");
}

void TankWebUI::handleRequest(AsyncWebServerRequest *request) {
  const bool is_js = request->url() == "/tank.js";
  // Content type matters for the script tag: ESPHome emits it as
  // type=module, and a browser refuses a module served as text/plain.
  auto *response = request->beginResponse(200, is_js ? "text/javascript" : "text/css",
                                          is_js ? this->js_ : this->css_);
  // Immutable in practice -- the payload only changes on a firmware
  // update, which changes nothing a stale cache could serve wrongly for
  // long. Short max-age keeps a reflash visible without a hard refresh.
  response->addHeader("Cache-Control", "max-age=60");
  request->send(response);
}

void TankWebUI::dump_config() {
  ESP_LOGCONFIG(TAG, "Tank Web UI:");
  ESP_LOGCONFIG(TAG, "  Serving /tank.js (%u bytes) and /tank.css (%u bytes) from flash",
                (unsigned) strlen(this->js_), (unsigned) strlen(this->css_));
}

}  // namespace tank_webui
}  // namespace esphome
