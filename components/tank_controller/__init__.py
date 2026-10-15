import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import automation
from esphome.components import sensor, output, binary_sensor, time as time_
from esphome.const import (
    CONF_ID,
    CONF_TEMPERATURE,
    CONF_TIME_ID,
)

CONF_FAN = "fan"

CODEOWNERS = ["@tank-monitor"]
DEPENDENCIES = []
AUTO_LOAD = ["sensor", "output", "binary_sensor"]

CONF_ILLUMINANCE = "illuminance"
CONF_HEATER = "heater"
CONF_SETPOINT = "setpoint"
CONF_MIN_TEMPERATURE = "min_temperature"
CONF_MAX_TEMPERATURE = "max_temperature"
CONF_FULL_SCALE_LUX = "full_scale_lux"
CONF_RESPONSE_TIME = "response_time"
CONF_MAX_TIME_CONSTANT = "max_time_constant"
CONF_LEARNING = "learning"
CONF_FAN_DEADBAND = "fan_deadband"
CONF_CROSS_CHECK = "cross_check"
CONF_DISAGREEMENT_BAND = "disagreement_band"
CONF_AMBIENT = "ambient"
CONF_AMBIENT_TIMEOUT = "ambient_timeout"
CONF_AMBIENT_SOURCE = "ambient_source"
CONF_HEATER_RELAY = "heater_relay"
CONF_FAN_RELAY = "fan_relay"
CONF_TANK_VOLUME = "tank_volume"
CONF_WATER_VOLUME = "water_volume"
CONF_HEATER_POWER = "heater_power"
CONF_TANK_COVER = "tank_cover"
CONF_TANK_PLACEMENT = "tank_placement"

# Order matches COVER_* / PLACEMENT_* in tank_controller.h.
TANK_COVERS = {"open_top": 0, "lid": 1, "evaporation_cover": 2, "unknown": 3}
TANK_PLACEMENTS = {"open_room": 0, "enclosed_cabinet": 1}

tank_controller_ns = cg.esphome_ns.namespace("tank_controller")
TankController = tank_controller_ns.class_("TankController", cg.PollingComponent)

ResetLearningAction = tank_controller_ns.class_(
    "ResetLearningAction", automation.Action
)
SetSetpointAction = tank_controller_ns.class_("SetSetpointAction", automation.Action)
SetFanDeadbandAction = tank_controller_ns.class_(
    "SetFanDeadbandAction", automation.Action
)
SetDisagreementBandAction = tank_controller_ns.class_(
    "SetDisagreementBandAction", automation.Action
)
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


def _f_delta_to_c(f):
    """A temperature *difference* in Fahrenheit, to Celsius.

    Separate from _f_to_c on purpose: a deadband is a span, not a point, and
    the 32 offset does not apply. Running 0.25 degF through _f_to_c gives
    -17.6 degC, which the controller would clamp to zero -- a fan with no
    deadband at all, silently.
    """
    return f * 5.0 / 9.0


def _validate(config):
    tank = config.get(CONF_TANK_VOLUME, 0.0)
    water = config.get(CONF_WATER_VOLUME, 0.0)
    if water and not tank:
        raise cv.Invalid("water_volume needs tank_volume (the tank's size gives its surface area)")
    if water and water > tank:
        raise cv.Invalid("water_volume cannot exceed tank_volume")
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
            # Explicit ceiling on the learned passive time constant (Tank Time
            # Constant), i.e. the floor on the loss coefficient ka. Optional.
            # With tank_volume set the band comes from the tank's physics and
            # this only overrides its ceiling; without it the ceiling is
            # 1000 min unless set here. 100 min to 20000 min (two weeks).
            cv.Optional(CONF_MAX_TIME_CONSTANT): cv.All(
                cv.positive_time_period_minutes,
                cv.Range(
                    min=cv.TimePeriod(minutes=100), max=cv.TimePeriod(minutes=20000)
                ),
            ),
            # The tank's physics. All optional, all FIRST-BOOT DEFAULTS: the
            # "Tank Volume", "Water Volume", "Heater Power", "Tank Cover" and
            # "Tank Placement" entities (control.yaml) change them at runtime
            # and the controller persists them, like the setpoint. With
            # tank_volume they set the thermal model's priors and bounds
            # from m*c and U*A -- see "What the tank's size says" in
            # tank_controller.cpp. Without it the model keeps its old priors.
            #
            # tank_volume: nominal size, US gallons (75 for a 75). Gives the
            # glass and water-surface areas.
            cv.Optional(CONF_TANK_VOLUME, default=0.0): cv.float_range(min=0.0, max=500.0),
            # water_volume: the water actually in it, US gallons, after
            # substrate and hardscape. Gives the heat capacity. 0 / omitted =
            # 85% of tank_volume.
            cv.Optional(CONF_WATER_VOLUME, default=0.0): cv.float_range(min=0.0, max=500.0),
            # heater_power: all heaters together at 100% duty, watts (2 x 150
            # = 300 on the 75). Gives the heater gain outright. 0 / omitted =
            # unknown: the gain is learned from the generic prior as before.
            cv.Optional(CONF_HEATER_POWER, default=0.0): cv.float_range(min=0.0, max=5000.0),
            # What is over the water: open_top, lid, evaporation_cover
            # (a lid with the gaps sealed), or unknown (the widest band).
            cv.Optional(CONF_TANK_COVER, default="unknown"): cv.enum(TANK_COVERS, lower=True),
            # What is around it: open_room, or enclosed_cabinet (the tank
            # sits inside a closed stand -- warmer air around it, a longer
            # time constant, and a room sensor that does not measure it).
            cv.Optional(CONF_TANK_PLACEMENT, default="open_room"): cv.enum(TANK_PLACEMENTS, lower=True),
            # The relays as switched (binary sensors published from the
            # slow_pwm outputs). When given the model learns from delivered
            # on-time, not commanded duty. control.yaml wires both.
            cv.Optional(CONF_HEATER_RELAY): cv.use_id(binary_sensor.BinarySensor),
            cv.Optional(CONF_FAN_RELAY): cv.use_id(binary_sensor.BinarySensor),
            # How far above setpoint the water must sit before the fan may
            # run, degF. First-boot default only: the "Fan Deadband" number
            # in control.yaml changes it at runtime and the controller
            # persists it. 2.0 matches FAN_DEADBAND_MAX_F in the component.
            cv.Optional(CONF_FAN_DEADBAND, default=0.25): cv.float_range(min=0.0, max=2.0),
            # A second DS18B20 on its own bus. Never controlled on: the loop
            # stays on `temperature`. If the two disagree by more than
            # disagreement_band (degF) for five minutes the heater goes off,
            # because one of them is lying and there is no telling which.
            cv.Optional(CONF_CROSS_CHECK): cv.use_id(sensor.Sensor),
            # First-boot default; the "Probe Disagreement Band" number
            # changes it live. 15.0 matches DISAGREE_BAND_MAX_F.
            cv.Optional(CONF_DISAGREEMENT_BAND, default=2.0): cv.float_range(min=0.0, max=15.0),
            # Optional room-air temperature sensor (Celsius state, like every
            # sensor this component reads). Never controlled on. While it
            # reports a plausible value, the model measures the tank's heat
            # loss against the room instead of against the setpoint, so the
            # room's daily swing identifies the loss coefficient (Tank Time
            # Constant) and the constant term only has to model the tank's
            # own heat. If it goes missing, stale (5 min) or implausible the
            # model falls back to the setpoint reference on the next tick,
            # with no step in the prediction. See "Where the model is
            # centred" in tank_controller.cpp.
            cv.Optional(CONF_AMBIENT): cv.use_id(sensor.Sensor),
            # How long one room reading stays good with no newer one. 10 min
            # suits a probe that reports every few seconds; a report-on-
            # change Zigbee sensor needs hours (packages/ambient_zigbee.yaml
            # sets 3h). A source that knows it is gone should publish NAN,
            # which ends it immediately regardless of this.
            cv.Optional(CONF_AMBIENT_TIMEOUT, default="10min"): cv.All(
                cv.positive_time_period_minutes,
                cv.Range(min=cv.TimePeriod(minutes=1), max=cv.TimePeriod(hours=12)),
            ),
            # Short label for logs and the "Model Reference" entity, which
            # reads "room: <this>" while the room is in use.
            cv.Optional(CONF_AMBIENT_SOURCE, default="room probe"): cv.All(
                cv.string_strict, cv.Length(min=1, max=20)
            ),
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
    if CONF_MAX_TIME_CONSTANT in config:
        cg.add(var.set_max_time_constant(config[CONF_MAX_TIME_CONSTANT].total_minutes))
    cg.add(
        var.set_physics_default(
            config[CONF_TANK_VOLUME],
            config[CONF_WATER_VOLUME],
            config[CONF_HEATER_POWER],
            TANK_COVERS[config[CONF_TANK_COVER]],
            TANK_PLACEMENTS[config[CONF_TANK_PLACEMENT]],
        )
    )
    if CONF_HEATER_RELAY in config:
        cg.add(var.set_heater_relay(await cg.get_variable(config[CONF_HEATER_RELAY])))
    if CONF_FAN_RELAY in config:
        cg.add(var.set_fan_relay(await cg.get_variable(config[CONF_FAN_RELAY])))
    cg.add(var.set_fan_deadband(_f_delta_to_c(config[CONF_FAN_DEADBAND])))
    cg.add(var.set_disagreement_band(_f_delta_to_c(config[CONF_DISAGREEMENT_BAND])))
    if CONF_CROSS_CHECK in config:
        cg.add(var.set_cross_check_sensor(await cg.get_variable(config[CONF_CROSS_CHECK])))
    if CONF_AMBIENT in config:
        cg.add(var.set_ambient_sensor(await cg.get_variable(config[CONF_AMBIENT])))
        cg.add(var.set_ambient_timeout(config[CONF_AMBIENT_TIMEOUT].total_minutes))
        cg.add(var.set_ambient_source(config[CONF_AMBIENT_SOURCE]))


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
    "tank_controller.set_fan_deadband",
    SetFanDeadbandAction,
    CONTROLLER_ACTION_SCHEMA.extend(
        {cv.Required(CONF_FAN_DEADBAND): cv.templatable(cv.float_)}
    ),
    synchronous=True,
)
async def set_fan_deadband_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg, paren)
    cg.add(var.set_value(await cg.templatable(config[CONF_FAN_DEADBAND], args, float)))
    return var


@automation.register_action(
    "tank_controller.set_disagreement_band",
    SetDisagreementBandAction,
    CONTROLLER_ACTION_SCHEMA.extend(
        {cv.Required(CONF_DISAGREEMENT_BAND): cv.templatable(cv.float_)}
    ),
    synchronous=True,
)
async def set_disagreement_band_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg, paren)
    cg.add(var.set_value(await cg.templatable(config[CONF_DISAGREEMENT_BAND], args, float)))
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
