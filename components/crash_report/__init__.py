"""Turns the last crash into something Home Assistant can show.

A crash reboots the board in well under a second, and everything that says
WHY -- the panic backtrace, which task the watchdog caught -- goes to the USB
serial console that nobody has plugged in. "Reset Reason" then says only
"task watchdog". This component keeps the evidence across the reboot and
publishes it:

  * ESPHome's own panic hook (esp32/crash_handler.cpp, on by default for
    ESP-IDF builds) already stores the faulting PC and backtrace in .noinit
    RAM, but only ever prints it to the log at boot or to a native-API
    client. This board talks MQTT, so the record is captured here from that
    log output and saved to NVS.
  * For a TASK WATCHDOG the panic backtrace is usually the idle task: the
    main loop is blocked, not running, when the watchdog fires. So the
    watchdog's ISR hook (esp_task_wdt_isr_user_handler) also records which
    unit of work the main loop was inside -- ESPHome publishes it in
    App.current_source_ for exactly this kind of attribution -- and for how
    long, plus the task running on each core.

The result survives power cuts (NVS) until the next crash replaces it or
"Clear Crash Report" is pressed.
"""

import esphome.codegen as cg
from esphome.components import logger
import esphome.config_validation as cv
from esphome.const import CONF_ID

CODEOWNERS = ["@tank-monitor"]
DEPENDENCIES = ["esp32", "logger"]

crash_report_ns = cg.esphome_ns.namespace("crash_report")
CrashReport = crash_report_ns.class_("CrashReport", cg.Component)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(CrashReport),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    # One log listener slot: the crash record only exists as log lines.
    logger.request_log_listener()
