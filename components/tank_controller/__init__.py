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
            cv.Optional(CONF_SETPOINT, default=25.0): cv.float_range(min=0, max=40),
            cv.Optional(CONF_MIN_TEMPERATURE, default=20.0): cv.float_range(min=0, max=40),
            cv.Optional(CONF_MAX_TEMPERATURE, default=30.0): cv.float_range(min=0, max=40),
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

    cg.add(var.set_min_temperature(config[CONF_MIN_TEMPERATURE]))
    cg.add(var.set_max_temperature(config[CONF_MAX_TEMPERATURE]))
    cg.add(var.set_setpoint(config[CONF_SETPOINT]))
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
