"""The panel's own controls -- so a tank with no Home Assistant and no
Wi-Fi can still be set, calibrated and logged from the glass.

Three pages, drawn by this component and added to the 4.3" panel's display
by packages/panel_controls.yaml:
  0 Settings   target, probe offset, heater watts, fan start, CO2 schedule
  1 Calibrate  TDS against a standard; pH two-point when a probe reads
  2 Water test pH, ammonia, nitrite, nitrate, GH, KH -> the controller's log

Every change goes to the controller over the BLE link the panel already
holds (components/sd_archive -> components/tank_backup), by entity name,
and the pages show the controller's own values read back the same way.
"""

import esphome.codegen as cg
from esphome.components import font, time
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_TIME_ID

CODEOWNERS = ["@JoshuaSeidel"]
DEPENDENCIES = ["display", "font", "time"]

panel_controls_ns = cg.esphome_ns.namespace("panel_controls")
PanelControls = panel_controls_ns.class_("PanelControls", cg.Component)
sd_archive_ns = cg.esphome_ns.namespace("sd_archive")
SdArchive = sd_archive_ns.class_("SdArchive", cg.PollingComponent)

CONF_ARCHIVE = "archive"
FONTS = ("font_micro", "font_small", "font_med", "font_big")

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(PanelControls),
        cv.Required(CONF_ARCHIVE): cv.use_id(SdArchive),
        cv.Required(CONF_TIME_ID): cv.use_id(time.RealTimeClock),
        **{cv.Required(f): cv.use_id(font.Font) for f in FONTS},
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    cg.add(var.set_archive(await cg.get_variable(config[CONF_ARCHIVE])))
    cg.add(var.set_time(await cg.get_variable(config[CONF_TIME_ID])))
    fonts = [await cg.get_variable(config[f]) for f in FONTS]
    cg.add(var.set_fonts(*fonts))
