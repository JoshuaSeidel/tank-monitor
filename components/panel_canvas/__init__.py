"""An off-screen copy of the panel, so nothing is ever seen half-drawn.

The 4.3" RGB panel streams its framebuffer to the glass continuously, so
every clear-then-draw is watched live: a card blinks empty before its text
returns, a page change flashes black. Pages draw into this canvas instead
(a Display backed by a PSRAM buffer the size of the screen), and blit() then
copies the rows that changed to the real display in ONE call -- the glass
only ever shows finished frames.
"""

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_HEIGHT, CONF_ID, CONF_WIDTH

CODEOWNERS = ["@JoshuaSeidel"]
DEPENDENCIES = ["display", "psram"]

panel_canvas_ns = cg.esphome_ns.namespace("panel_canvas")
PanelCanvas = panel_canvas_ns.class_("PanelCanvas", cg.Component)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(PanelCanvas),
        cv.Optional(CONF_WIDTH, default=800): cv.int_range(min=1, max=2048),
        cv.Optional(CONF_HEIGHT, default=480): cv.int_range(min=1, max=2048),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    cg.add(var.set_size(config[CONF_WIDTH], config[CONF_HEIGHT]))
