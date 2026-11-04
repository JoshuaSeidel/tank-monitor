"""Settings backup and restore, and firmware slots, for a tank with no
Home Assistant. Lives on the controller; the panel's SD card is where the
backups and firmware copies are kept (components/sd_archive).

  GET  /backup.json            every number, select, time, chosen switches,
                               the learned heat model and the water tests
  POST /restore?settings=1&model=1&tests=1   (multipart, one JSON file)
  GET  /firmware/slots.json    the running build and the one before it
  POST /firmware/rollback      boot the previous build
  GET  /firmware/current.bin   the running firmware image, for archiving
  GET  /peer.json              the panel's Wi-Fi address, as the panel
                               reported it over BLE

The panel pulls the backup, the slot info and the firmware over BLE -- the
two devices never talk over Wi-Fi. ble_request() is the server side of that
transfer; packages/standalone_controller.yaml wires it to a characteristic.
"""

import esphome.codegen as cg
from esphome.components import switch, web_server_base
import esphome.config_validation as cv
from esphome.const import CONF_ID

CODEOWNERS = ["@JoshuaSeidel"]
DEPENDENCIES = ["web_server_base"]
AUTO_LOAD = ["web_server_base", "json"]

tank_backup_ns = cg.esphome_ns.namespace("tank_backup")
TankBackup = tank_backup_ns.class_("TankBackup", cg.Component)
tank_controller_ns = cg.esphome_ns.namespace("tank_controller")
TankController = tank_controller_ns.class_("TankController", cg.PollingComponent)
tank_history_ns = cg.esphome_ns.namespace("tank_history")
TankHistory = tank_history_ns.class_("TankHistory", cg.PollingComponent)

CONF_WEB_SERVER_BASE_ID = "web_server_base_id"
CONF_CONTROLLER = "controller"
CONF_HISTORY = "history"
CONF_SWITCHES = "switches"

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(TankBackup),
        cv.GenerateID(CONF_WEB_SERVER_BASE_ID): cv.use_id(
            web_server_base.WebServerBase
        ),
        cv.Required(CONF_CONTROLLER): cv.use_id(TankController),
        cv.Required(CONF_HISTORY): cv.use_id(TankHistory),
        # Switches that are SETTINGS (a schedule enable, learning on/off),
        # as opposed to outlets that are simply on or off right now.
        cv.Optional(CONF_SWITCHES, default=[]): cv.ensure_list(
            cv.use_id(switch.Switch)
        ),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    base = await cg.get_variable(config[CONF_WEB_SERVER_BASE_ID])
    cg.add(var.set_base(base))
    cg.add(var.set_controller(await cg.get_variable(config[CONF_CONTROLLER])))
    cg.add(var.set_history(await cg.get_variable(config[CONF_HISTORY])))
    for sw in config[CONF_SWITCHES]:
        cg.add(var.add_switch(await cg.get_variable(sw)))
