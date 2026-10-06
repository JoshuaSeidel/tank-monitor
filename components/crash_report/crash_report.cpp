#include "crash_report.h"

#include "esphome/core/application.h"
#include "esphome/core/build_info_data.h"
#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"
#include "esphome/components/logger/logger.h"

#ifdef USE_ESP32
#include <cstring>
#include <esp_attr.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <esp_task_wdt.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#ifdef USE_ESP32_CRASH_HANDLER
#include "esphome/components/esp32/crash_handler.h"
#endif
#endif

// ---------------------------------------------------------------------------
// Task-watchdog breadcrumb, written from the watchdog's own ISR.
// ---------------------------------------------------------------------------
// Lives in .noinit (as ESPHome's crash record does): survives the panic's
// software reset, garbage after a power cycle, validated by magic + build.
// IDF calls this from the watchdog interrupt just before it panics. That
// interrupt is allocated without ESP_INTR_FLAG_IRAM (task_wdt_impl_timergroup.c),
// so it never runs with the flash cache off; the hook still only copies a few
// words and two task names and does no work that could fail.
#ifdef USE_ESP32
namespace {
constexpr uint32_t TWDT_MAGIC = 0x54574454;  // "TWDT"
constexpr int CORES = CONFIG_FREERTOS_NUMBER_OF_CORES;
struct TwdtBreadcrumb {
  uint32_t magic;
  uint32_t build_time;
  uint32_t source;      // const LogString * the main loop was running, or 0
  uint32_t running_ms;  // how long that unit of work had been running
  uint32_t uptime_s;
  char task[CORES][CONFIG_FREERTOS_MAX_TASK_NAME_LEN];
};
TwdtBreadcrumb __attribute__((section(".noinit"))) s_twdt;  // NOLINT
// RAM mirror of the build stamp; the generated constant is in flash.
uint32_t s_build_time = static_cast<uint32_t>(esphome::ESPHOME_BUILD_TIME);  // NOLINT
}  // namespace

extern "C" void IRAM_ATTR esp_task_wdt_isr_user_handler(void) {
  s_twdt.magic = 0;
  const uint32_t now_ms = (uint32_t) (esp_timer_get_time() / 1000);
  s_twdt.build_time = s_build_time;
  s_twdt.source = reinterpret_cast<uint32_t>(esphome::App.get_current_source());
  s_twdt.running_ms = now_ms - esphome::App.get_loop_component_start_time();
  s_twdt.uptime_s = now_ms / 1000;
  for (int c = 0; c < CORES; c++) {
    const char *name = pcTaskGetName(xTaskGetCurrentTaskHandleForCore(c));
    int i = 0;
    for (; name != nullptr && i < CONFIG_FREERTOS_MAX_TASK_NAME_LEN - 1 && name[i] != '\0'; i++)
      s_twdt.task[c][i] = name[i];
    s_twdt.task[c][i] = '\0';
  }
  s_twdt.magic = TWDT_MAGIC;
}
#endif

namespace esphome {
namespace crash_report {

static const char *const TAG = "crash_report";

static void copy_trunc(char *dst, size_t cap, const std::string &src) {
  const size_t n = std::min(src.size(), cap - 1);
  memcpy(dst, src.data(), n);
  dst[n] = '\0';
}

void CrashReport::setup() {
  this->pref_ = global_preferences->make_preference<Store>(fnv1_hash("crash_report_v1"));
  if (!this->pref_.load(&this->store_)) {
    this->store_ = Store{};
  }
  // NVS could hold anything after a layout change; never print past the end.
  this->store_.summary[sizeof(this->store_.summary) - 1] = '\0';
  this->store_.backtrace[sizeof(this->store_.backtrace) - 1] = '\0';

#ifdef USE_ESP32
  const esp_reset_reason_t rr = esp_reset_reason();
  const bool crashed = rr == ESP_RST_PANIC || rr == ESP_RST_TASK_WDT || rr == ESP_RST_INT_WDT || rr == ESP_RST_WDT;
  if (!crashed) {
    s_twdt.magic = 0;  // a clean boot: whatever is in .noinit is stale
    return;
  }

  std::string summary;
  // 1. ESPHome's panic record: reason, crashed core, PC and backtrace. It is
  //    only ever printed, so print it again with a listener attached.
#ifdef USE_ESP32_CRASH_HANDLER
  if (esp32::crash_handler_has_data() && logger::global_logger != nullptr) {
    logger::global_logger->add_log_callback(this, &CrashReport::on_log_);
    this->capturing_ = true;
    esp32::crash_handler_log();
    this->capturing_ = false;
    // Consumed: without this a later clean OTA reboot would report the same
    // crash again as if it were new.
    esp32::crash_handler_clear();
  }
#endif
  summary = this->cap_reason_.empty()
                ? std::string(rr == ESP_RST_TASK_WDT ? "Task watchdog" : rr == ESP_RST_PANIC ? "Panic" : "Watchdog")
                : this->cap_reason_;

  // 2. The watchdog breadcrumb: what the main loop was inside, for how long.
  if (s_twdt.magic == TWDT_MAGIC) {
    char b[160];
    const char *where = "between components";
    if (s_twdt.build_time == s_build_time && s_twdt.source != 0) {
      // Same firmware: the LogString pointer still names a string in this
      // image's flash.
      where = LOG_STR_ARG(reinterpret_cast<const LogString *>(s_twdt.source));
    } else if (s_twdt.source != 0) {
      where = "(older firmware; source unknown)";
    }
    int n = snprintf(b, sizeof(b), "; main loop stuck %.1f s in '%s' at uptime %u s; running:",
                     s_twdt.running_ms / 1000.0f, where, (unsigned) s_twdt.uptime_s);
    for (int c = 0; c < CORES && n > 0 && n < (int) sizeof(b); c++)
      n += snprintf(b + n, sizeof(b) - n, " CPU%d %.15s", c, s_twdt.task[c]);
    summary += b;
    s_twdt.magic = 0;
  }

  this->store_.count++;
  copy_trunc(this->store_.summary, sizeof(this->store_.summary), summary);
  copy_trunc(this->store_.backtrace, sizeof(this->store_.backtrace),
             this->cap_addrs_.empty() ? std::string("no backtrace captured") : this->cap_addrs_);
  this->fresh_ = true;
  this->save_();
  ESP_LOGE(TAG, "previous boot crashed: %s", this->store_.summary);
  ESP_LOGE(TAG, "  %s", this->store_.backtrace);
#endif
}

void CrashReport::on_log_(void *self, uint8_t level, const char *tag, const char *message, size_t len) {
  auto *me = static_cast<CrashReport *>(self);
  if (!me->capturing_ || tag == nullptr || strcmp(tag, "esp32.crash") != 0)
    return;
  me->capture_line_(message, len);
}

void CrashReport::capture_line_(const char *message, size_t len) {
  // The logger hands over the formatted line: colour code, "[E][tag:line]: ",
  // the text, and a colour reset. Keep only the text.
  std::string s(message, len);
  const size_t hdr = s.find("]: ");
  if (hdr != std::string::npos)
    s.erase(0, hdr + 3);
  const size_t esc = s.find('\033');
  if (esc != std::string::npos)
    s.erase(esc);
  while (!s.empty() && s.front() == ' ')
    s.erase(0, 1);

  auto first_hex = [&s]() -> std::string {
    const size_t p = s.find("0x");
    if (p == std::string::npos)
      return {};
    size_t e = p + 2;
    while (e < s.size() && isxdigit((unsigned char) s[e]))
      e++;
    return s.substr(p, e - p);
  };

  if (s.rfind("Reason: ", 0) == 0) {
    this->cap_reason_ = s.substr(8);
  } else if (s.rfind("Crashed core: ", 0) == 0) {
    this->cap_reason_ += " on core " + s.substr(14);
  } else if (s.rfind("Captured by a different firmware build", 0) == 0) {
    this->cap_reason_ += " (recorded by an older build; addresses are that build's)";
  } else if (s.rfind("PC:", 0) == 0 || s.rfind("pc:", 0) == 0) {
    this->cap_addrs_ += "PC " + first_hex();
  } else if (s.rfind("EXCVADDR", 0) == 0 || s.rfind("excvaddr", 0) == 0 || s.rfind("MTVAL", 0) == 0 ||
             s.rfind("mtval", 0) == 0) {
    this->cap_addrs_ += " fault@" + first_hex();
  } else if (s.rfind("BT", 0) == 0 || s.rfind("bt", 0) == 0) {
    const std::string h = first_hex();
    if (!h.empty())
      this->cap_addrs_ += (this->cap_addrs_.find(" BT") == std::string::npos ? " BT " : " ") + h;
  } else if (s.rfind("Other core", 0) == 0 || s.rfind("other core", 0) == 0) {
    // Lines after this belong to the other core's stack.
    if (s.find("addr2line") == std::string::npos)
      this->cap_addrs_ += " | other core BT";
  }
}

void CrashReport::save_() {
  this->pref_.save(&this->store_);
  // A crash record is exactly the thing that must not be lost to the next
  // crash before the periodic flush.
  global_preferences->sync();
}

std::string CrashReport::summary() const {
  return this->store_.count == 0 ? std::string("none recorded") : std::string(this->store_.summary);
}

std::string CrashReport::backtrace() const {
  return this->store_.count == 0 ? std::string("none recorded") : std::string(this->store_.backtrace);
}

void CrashReport::clear() {
  this->store_ = Store{};
  this->fresh_ = false;
  this->save_();
  ESP_LOGI(TAG, "crash report cleared");
}

void CrashReport::dump_config() {
  ESP_LOGCONFIG(TAG, "Crash report: %u recorded", (unsigned) this->store_.count);
  if (this->store_.count != 0) {
    ESP_LOGCONFIG(TAG, "  Last: %s", this->store_.summary);
    ESP_LOGCONFIG(TAG, "  %s", this->store_.backtrace);
  }
}

}  // namespace crash_report
}  // namespace esphome
