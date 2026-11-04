"""On-device history and water-test log, for a tank with no Home Assistant.

Keeps two rings per series -- 288 five-minute means (24 h) and 720 hourly
means (30 days) -- and a log of the last 40 manual water tests, all saved to
flash so a reboot or power cut loses at most the half hour since the last
save. Serves them to the browser from this device:

  GET  /history.json?range=day|month
  GET  /tests.json
  POST /tests?ph=&nh3=&no2=&no3=&gh=&kh=   (blank = not tested)
  POST /tests/delete?t=<epoch>

Nothing here needs the internet except the clock, which comes from SNTP.
"""

import esphome.codegen as cg
from esphome.components import sensor, time, web_server_base
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_NAME, CONF_SENSOR, CONF_TIME_ID

CODEOWNERS = ["@JoshuaSeidel"]
DEPENDENCIES = ["web_server_base", "time"]
AUTO_LOAD = ["web_server_base"]

tank_history_ns = cg.esphome_ns.namespace("tank_history")
TankHistory = tank_history_ns.class_("TankHistory", cg.PollingComponent)

CONF_WEB_SERVER_BASE_ID = "web_server_base_id"
CONF_SERIES = "series"
CONF_SCALE = "scale"

# Stored as int16 of value * scale, so scale sets both the resolution and the
# ceiling: 100 keeps 0.01 degF and tops out at 327 degF.
SERIES_SCHEMA = cv.Schema(
    {
        cv.Required(CONF_NAME): cv.All(cv.string, cv.Length(min=1, max=12)),
        cv.Required(CONF_SENSOR): cv.use_id(sensor.Sensor),
        cv.Optional(CONF_SCALE, default=1.0): cv.positive_float,
    }
)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(TankHistory),
        cv.GenerateID(CONF_WEB_SERVER_BASE_ID): cv.use_id(
            web_server_base.WebServerBase
        ),
        cv.Required(CONF_TIME_ID): cv.use_id(time.RealTimeClock),
        cv.Required(CONF_SERIES): cv.All(
            cv.ensure_list(SERIES_SCHEMA), cv.Length(min=1, max=10)
        ),
    }
).extend(cv.polling_component_schema("30s"))


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    base = await cg.get_variable(config[CONF_WEB_SERVER_BASE_ID])
    cg.add(var.set_base(base))
    clock = await cg.get_variable(config[CONF_TIME_ID])
    cg.add(var.set_time(clock))
    for s in config[CONF_SERIES]:
        sens = await cg.get_variable(s[CONF_SENSOR])
        cg.add(var.add_series(s[CONF_NAME], sens, s[CONF_SCALE]))
