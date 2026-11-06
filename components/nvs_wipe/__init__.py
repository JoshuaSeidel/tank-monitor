"""Wipe a board's stored settings from the YAML -- no Wi-Fi, no web page,
no installer option needed.

  nvs_wipe:
    generation: 1

On boot the board compares `generation` with the one it last wiped for (a
marker kept in NVS). If they differ -- a chip that has never run this
firmware, or a generation raised in the YAML -- it erases the whole NVS
partition ONCE (every calibration, learned model, history, water test,
saved Wi-Fi and restored global), records the new generation, and restarts
clean on the YAML defaults. Same generation: nothing happens, so ordinary
updates keep everything.

To wipe again: raise the number, reflash.
"""

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_ID

CODEOWNERS = ["@JoshuaSeidel"]
DEPENDENCIES = ["esp32"]

nvs_wipe_ns = cg.esphome_ns.namespace("nvs_wipe")
NvsWipe = nvs_wipe_ns.class_("NvsWipe", cg.Component)

CONF_GENERATION = "generation"

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(NvsWipe),
        cv.Required(CONF_GENERATION): cv.int_range(min=1, max=1000000),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    cg.add(var.set_generation(config[CONF_GENERATION]))
