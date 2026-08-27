import os

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import web_server_base
from esphome.const import CONF_ID

CODEOWNERS = ["@JoshuaSeidel"]
DEPENDENCIES = ["web_server_base"]
AUTO_LOAD = ["web_server_base"]

tank_webui_ns = cg.esphome_ns.namespace("tank_webui")
TankWebUI = tank_webui_ns.class_("TankWebUI", cg.Component)

CONF_WEB_SERVER_BASE_ID = "web_server_base_id"

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(TankWebUI),
        cv.GenerateID(CONF_WEB_SERVER_BASE_ID): cv.use_id(
            web_server_base.WebServerBase
        ),
    }
).extend(cv.COMPONENT_SCHEMA)


def _asset(name: str) -> str:
    """Read an asset from THIS component's directory.

    That directory is whatever external_components fetched -- the git
    checkout when pulled from a repo. Which is the whole point: the assets
    travel with the component instead of having to exist in the user's
    ESPHome config directory, so `git push` is the entire update path.
    """
    path = os.path.join(os.path.dirname(__file__), "assets", name)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    base = await cg.get_variable(config[CONF_WEB_SERVER_BASE_ID])
    cg.add(var.set_base(base))
    cg.add(var.set_js(_asset("tank.js")))
    cg.add(var.set_css(_asset("tank.css")))
