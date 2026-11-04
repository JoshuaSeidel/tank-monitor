"""Long-term archive on the panel's SD card, for a tank with no Home
Assistant.

  /sd/history/YYYY-MM.csv     a 5-minute row per slot, kept for good
  /sd/backups/YYYY-MM-DD.json the controller's settings backup, nightly
  /sd/firmware/<who>-<sha>.bin every controller and panel build that has
                              run, kept so any of them can be reinstalled

Served with CORS so the controller's web page can show and restore them:
  GET  /sd/status.json   GET /sd/list.json?dir=   GET /sd/file?path=[&dl=1]
  POST /sd/upload?dir=&name=  (raw body)   POST /sd/delete?path=
  POST /sd/backup-now

SPI on three plain GPIOs; chip-select is any output pin -- on the Waveshare
4.3" it is the CH422G expander's EXIO4, held low for good (the SD card is
the only device on that bus, and the IDF driver runs without a CS pin).
"""

from esphome import pins
import esphome.codegen as cg
from esphome.components import sensor, time, web_server_base
from esphome.components.esp32 import (
    add_idf_sdkconfig_option,
    include_builtin_idf_component,
    request_http_client,
)
import esphome.config_validation as cv
from esphome.const import (
    CONF_CS_PIN,
    CONF_ID,
    CONF_MISO_PIN,
    CONF_MOSI_PIN,
    CONF_NAME,
    CONF_SENSOR,
    CONF_TIME_ID,
)

CODEOWNERS = ["@JoshuaSeidel"]
DEPENDENCIES = ["web_server_base", "time", "esp32"]
AUTO_LOAD = ["web_server_base", "json"]

sd_archive_ns = cg.esphome_ns.namespace("sd_archive")
SdArchive = sd_archive_ns.class_("SdArchive", cg.PollingComponent)

CONF_WEB_SERVER_BASE_ID = "web_server_base_id"
CONF_CLK_PIN = "clk_pin"
CONF_CONTROLLER_HOST = "controller_host"
CONF_SERIES = "series"
CONF_DECIMALS = "decimals"

SERIES_SCHEMA = cv.Schema(
    {
        cv.Required(CONF_NAME): cv.All(cv.string, cv.Length(min=1, max=16)),
        cv.Required(CONF_SENSOR): cv.use_id(sensor.Sensor),
        cv.Optional(CONF_DECIMALS, default=1): cv.int_range(min=0, max=4),
    }
)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(SdArchive),
        cv.GenerateID(CONF_WEB_SERVER_BASE_ID): cv.use_id(
            web_server_base.WebServerBase
        ),
        cv.Required(CONF_TIME_ID): cv.use_id(time.RealTimeClock),
        cv.Required(CONF_CS_PIN): pins.gpio_output_pin_schema,
        cv.Required(CONF_MOSI_PIN): cv.int_range(min=0, max=48),
        cv.Required(CONF_MISO_PIN): cv.int_range(min=0, max=48),
        cv.Required(CONF_CLK_PIN): cv.int_range(min=0, max=48),
        # The controller's mDNS host name, without ".local".
        cv.Required(CONF_CONTROLLER_HOST): cv.string,
        cv.Required(CONF_SERIES): cv.All(
            cv.ensure_list(SERIES_SCHEMA), cv.Length(min=1, max=16)
        ),
    }
).extend(cv.polling_component_schema("30s"))


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    base = await cg.get_variable(config[CONF_WEB_SERVER_BASE_ID])
    cg.add(var.set_base(base))
    cg.add(var.set_time(await cg.get_variable(config[CONF_TIME_ID])))
    cg.add(var.set_cs_pin(await cg.gpio_pin_expression(config[CONF_CS_PIN])))
    cg.add(var.set_bus(config[CONF_MOSI_PIN], config[CONF_MISO_PIN], config[CONF_CLK_PIN]))
    cg.add(var.set_controller_host(config[CONF_CONTROLLER_HOST]))
    for s in config[CONF_SERIES]:
        sens = await cg.get_variable(s[CONF_SENSOR])
        cg.add(var.add_series(s[CONF_NAME], sens, s[CONF_DECIMALS]))

    # ESPHome strips these from every build; this component needs them back:
    # the SD-over-SPI driver, the SD protocol and FAT, and the HTTP client for
    # pulling backups and firmware from the controller.
    for comp in ("fatfs", "wear_levelling", "sdmmc", "esp_driver_sdmmc", "esp_driver_sdspi"):
        include_builtin_idf_component(comp)
    request_http_client()
    # File names like "controller-1a2b3c4d5e6f7a8b.bin" are not 8.3.
    add_idf_sdkconfig_option("CONFIG_FATFS_LFN_HEAP", True)
    add_idf_sdkconfig_option("CONFIG_FATFS_MAX_LFN", 64)
