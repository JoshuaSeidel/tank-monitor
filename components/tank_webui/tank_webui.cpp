#include "tank_webui.h"
#include "esphome/core/log.h"

namespace esphome {
namespace tank_webui {

static const char *const TAG = "tank_webui";

// url() is deprecated and REMOVED in ESPHome 2026.9.0. url_to() writes into
// a caller-supplied buffer instead of returning a std::string, which is the
// point: this runs on every HTTP request, and the old form heap-allocated a
// string just to compare it against two constants.
bool TankWebUI::canHandle(AsyncWebServerRequest *request) const {
  if (request->method() != HTTP_GET)
    return false;
  char url_buf[AsyncWebServerRequest::URL_BUF_SIZE];
  const auto url = request->url_to(url_buf);
  return url == "/tank.js" || url == "/tank.css";
}

void TankWebUI::handleRequest(AsyncWebServerRequest *request) {
  char url_buf[AsyncWebServerRequest::URL_BUF_SIZE];
  const bool is_js = request->url_to(url_buf) == "/tank.js";
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
