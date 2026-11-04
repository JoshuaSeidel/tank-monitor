import json
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
CONF_UI = "ui"
CONF_LAYOUT = "layout"

# "standard" is the page every HA-connected controller has always served.
# "standalone" is the whole-tank site for a tank with no Home Assistant:
# panel-style pages, history, water tests, settings and diagnostics. Its
# layout (the tank drawing's dimensions and positions) is handed to the
# script as a JSON prefix, so the drawing is configured in YAML like the
# panel's rather than edited into the asset.
UIS = {"standard": ("tank.js", "tank.css"), "standalone": ("standalone.js", "standalone.css")}

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(TankWebUI),
        cv.GenerateID(CONF_WEB_SERVER_BASE_ID): cv.use_id(
            web_server_base.WebServerBase
        ),
        cv.Optional(CONF_UI, default="standard"): cv.one_of(*UIS, lower=True),
        cv.Optional(CONF_LAYOUT, default={}): cv.Schema(
            {cv.string: cv.string}
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
    js, css = UIS[config[CONF_UI]]
    script = _asset(js)
    if config[CONF_UI] == "standalone":
        script = "const LAYOUT = " + json.dumps(dict(config[CONF_LAYOUT])) + ";\n" + script
    cg.add(var.set_js(script))
    cg.add(var.set_css(_asset(css)))
