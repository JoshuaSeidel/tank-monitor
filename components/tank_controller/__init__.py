import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import automation
from esphome.components import sensor, output, time as time_
from esphome.const import (
    CONF_ID,
    CONF_TEMPERATURE,
    CONF_TIME_ID,
)

CONF_FAN = "fan"

CODEOWNERS = ["@tank-monitor"]
DEPENDENCIES = []
AUTO_LOAD = ["sensor", "output"]

CONF_ILLUMINANCE = "illuminance"
CONF_HEATER = "heater"
CONF_SETPOINT = "setpoint"
CONF_MIN_TEMPERATURE = "min_temperature"
CONF_MAX_TEMPERATURE = "max_temperature"
CONF_FULL_SCALE_LUX = "full_scale_lux"
CONF_RESPONSE_TIME = "response_time"
CONF_LEARNING = "learning"

tank_controller_ns = cg.esphome_ns.namespace("tank_controller")
TankController = tank_controller_ns.class_("TankController", cg.PollingComponent)

ResetLearningAction = tank_controller_ns.class_(
    "ResetLearningAction", automation.Action
)
SetSetpointAction = tank_controller_ns.class_("SetSetpointAction", automation.Action)
SetLearningAction = tank_controller_ns.class_("SetLearningAction", automation.Action)
ImportModelAction = tank_controller_ns.class_("ImportModelAction", automation.Action)

# Prefixed to avoid shadowing CONF_HEATER, which this component already
# uses for its heater output. Redefining it silently broke the component's
# own schema.
CONF_IMP_HEATER = "heater_f_per_h"
CONF_IMP_FAN = "fan_f_per_h"
CONF_IMP_LIGHT = "light_f_per_h"
CONF_IMP_BIAS = "bias_f_per_h"
CONF_IMP_TC = "time_constant_min"
CONF_IMP_CONF = "confidence_pct"

def _f_to_c(f):
    """Every temperature in this component's config is Fahrenheit.

    The controller stores Celsius internally -- not from preference, but
    because the model's priors, clamps and residual guards are tuned in
    degC/min and hand-converting those constants is how a working
    controller quietly stops working. The unit is an implementation
    detail; nothing a user sets or reads is in it.
    """
    return (f - 32.0) * 5.0 / 9.0


def _validate(config):
    if config[CONF_MIN_TEMPERATURE] >= config[CONF_MAX_TEMPERATURE]:
        raise cv.Invalid("min_temperature must be below max_temperature")
    if not (
        config[CONF_MIN_TEMPERATURE]
        <= config[CONF_SETPOINT]
        <= config[CONF_MAX_TEMPERATURE]
    ):
        raise cv.Invalid("setpoint must lie between min_temperature and max_temperature")
    return config


CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(TankController),
            cv.Required(CONF_TEMPERATURE): cv.use_id(sensor.Sensor),
            cv.Optional(CONF_ILLUMINANCE): cv.use_id(sensor.Sensor),
            cv.Required(CONF_HEATER): cv.use_id(output.FloatOutput),
            cv.Optional(CONF_FAN): cv.use_id(output.FloatOutput),
            cv.Optional(CONF_TIME_ID): cv.use_id(time_.RealTimeClock),
            cv.Optional(CONF_SETPOINT, default=75.0): cv.float_range(min=32, max=110),
            cv.Optional(CONF_MIN_TEMPERATURE, default=68.0): cv.float_range(min=32, max=110),
            cv.Optional(CONF_MAX_TEMPERATURE, default=86.0): cv.float_range(min=32, max=110),
            cv.Optional(CONF_FULL_SCALE_LUX, default=2000.0): cv.positive_float,
            cv.Optional(CONF_RESPONSE_TIME, default="20min"): cv.positive_time_period_minutes,
            cv.Optional(CONF_LEARNING, default=True): cv.boolean,
        }
    ).extend(cv.polling_component_schema("30s")),
    _validate,
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    cg.add(var.set_temperature_sensor(await cg.get_variable(config[CONF_TEMPERATURE])))
    cg.add(var.set_heater(await cg.get_variable(config[CONF_HEATER])))

    if CONF_ILLUMINANCE in config:
        cg.add(
            var.set_illuminance_sensor(await cg.get_variable(config[CONF_ILLUMINANCE]))
        )
    if CONF_FAN in config:
        cg.add(var.set_fan(await cg.get_variable(config[CONF_FAN])))
        cg.add(var.set_fan_available(True))
    else:
        cg.add(var.set_fan_available(False))
    if CONF_TIME_ID in config:
        cg.add(var.set_time(await cg.get_variable(config[CONF_TIME_ID])))

    cg.add(var.set_min_temperature(_f_to_c(config[CONF_MIN_TEMPERATURE])))
    cg.add(var.set_max_temperature(_f_to_c(config[CONF_MAX_TEMPERATURE])))
    cg.add(var.set_setpoint(_f_to_c(config[CONF_SETPOINT])))
    cg.add(var.set_full_scale_lux(config[CONF_FULL_SCALE_LUX]))
    cg.add(var.set_response_time(config[CONF_RESPONSE_TIME].total_minutes))
    cg.add(var.set_learning_enabled(config[CONF_LEARNING]))


CONTROLLER_ACTION_SCHEMA = cv.Schema({cv.GenerateID(): cv.use_id(TankController)})


# synchronous=True: every action below calls a method and returns. None of
# them defer play_next_() to a callback, timer, or loop().
@automation.register_action(
    "tank_controller.reset_learning",
    ResetLearningAction,
    CONTROLLER_ACTION_SCHEMA,
    synchronous=True,
)
async def reset_learning_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    return cg.new_Pvariable(action_id, template_arg, paren)


@automation.register_action(
    "tank_controller.set_setpoint",
    SetSetpointAction,
    CONTROLLER_ACTION_SCHEMA.extend(
        {cv.Required(CONF_SETPOINT): cv.templatable(cv.float_)}
    ),
    synchronous=True,
)
async def set_setpoint_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg, paren)
    cg.add(var.set_value(await cg.templatable(config[CONF_SETPOINT], args, float)))
    return var


@automation.register_action(
    "tank_controller.set_learning",
    SetLearningAction,
    CONTROLLER_ACTION_SCHEMA.extend(
        {cv.Required(CONF_LEARNING): cv.templatable(cv.boolean)}
    ),
    synchronous=True,
)
async def set_learning_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg, paren)
    cg.add(var.set_value(await cg.templatable(config[CONF_LEARNING], args, bool)))
    return var


@automation.register_action(
    "tank_controller.import_model",
    ImportModelAction,
    CONTROLLER_ACTION_SCHEMA.extend(
        {
            cv.Required(CONF_IMP_HEATER): cv.templatable(cv.float_),
            cv.Required(CONF_IMP_FAN): cv.templatable(cv.float_),
            cv.Required(CONF_IMP_LIGHT): cv.templatable(cv.float_),
            cv.Required(CONF_IMP_BIAS): cv.templatable(cv.float_),
            cv.Required(CONF_IMP_TC): cv.templatable(cv.float_),
            cv.Required(CONF_IMP_CONF): cv.templatable(cv.float_),
        }
    ),
    synchronous=True,
)
async def import_model_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg, paren)
    for key, setter in (
        (CONF_IMP_HEATER, var.set_heater),
        (CONF_IMP_FAN, var.set_fan),
        (CONF_IMP_LIGHT, var.set_light),
        (CONF_IMP_BIAS, var.set_bias),
        (CONF_IMP_TC, var.set_tc),
        (CONF_IMP_CONF, var.set_confidence),
    ):
        cg.add(setter(await cg.templatable(config[key], args, float)))
    return var
