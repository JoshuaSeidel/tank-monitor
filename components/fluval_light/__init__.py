import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import automation
from esphome.components import ble_client, binary_sensor, sensor, text_sensor, time as time_
from esphome.const import CONF_ID, CONF_LATITUDE, CONF_LONGITUDE, CONF_TIME_ID

CODEOWNERS = ["@tank-monitor"]
DEPENDENCIES = ["ble_client"]
AUTO_LOAD = ["binary_sensor", "sensor", "text_sensor"]

CONF_CHANNEL_COUNT = "channel_count"
CONF_CHANNEL_MIX = "channel_mix"
CONF_DAYLIGHT_EXPONENT = "daylight_exponent"
CONF_DOSE_CAP_HOURS = "dose_cap_hours"
CONF_CURVE_STEP = "curve_step"
CONF_CURVE_EDGE_STEP = "curve_edge_step"
CONF_PUSH_HOUR = "push_hour"
CONF_STATUS = "status"
CONF_CURVE = "curve"
CONF_POINTS = "points"
CONF_DOSE = "dose"
CONF_CONNECTED = "connected"
CONF_MODE = "mode"

fluval_light_ns = cg.esphome_ns.namespace("fluval_light")
FluvalLight = fluval_light_ns.class_(
    "FluvalLight", cg.PollingComponent, ble_client.BLEClientNode
)
PushCurveAction = fluval_light_ns.class_("PushCurveAction", automation.Action)
SyncClockAction = fluval_light_ns.class_("SyncClockAction", automation.Action)
SetModeAction = fluval_light_ns.class_("SetModeAction", automation.Action)


def _validate(config):
    mix = config[CONF_CHANNEL_MIX]
    count = config[CONF_CHANNEL_COUNT]
    if len(mix) != count:
        raise cv.Invalid(
            f"{CONF_CHANNEL_MIX} has {len(mix)} values but {CONF_CHANNEL_COUNT} is "
            f"{count}. A Pro schedule record carries exactly one level per channel; "
            f"a short list would write a frame the fixture silently rejects."
        )
    return config


CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(FluvalLight),
            # Where the tank is. The curve is real solar elevation at this
            # point, so a wrong hemisphere gives a confidently wrong day
            # rather than an error.
            cv.Required(CONF_LATITUDE): cv.float_range(min=-90, max=90),
            cv.Required(CONF_LONGITUDE): cv.float_range(min=-180, max=180),
            # Plant 4.0 is product 545: five emitters. Plant 3.0 and the
            # 4-channel fixtures use 4.
            cv.Optional(CONF_CHANNEL_COUNT, default=5): cv.int_range(min=4, max=5),
            # Per-channel level at solar noon, 0-100. Everything else on the
            # curve is this mix scaled by the sun.
            cv.Required(CONF_CHANNEL_MIX): cv.ensure_list(cv.int_range(min=0, max=100)),
            # g in (E/E_noon)^g. 1.0 is literal photometry and reads far too
            # dim for the first ninety minutes; 0.5 compresses it the way
            # vision does. See daylight.h.
            cv.Optional(CONF_DAYLIGHT_EXPONENT, default=0.5): cv.float_range(
                min=0.1, max=1.0
            ),
            # Full-equivalent hours per day. Scales BRIGHTNESS, not the
            # photoperiod -- the lamp still runs dawn to dusk. 0 = natural.
            cv.Optional(CONF_DOSE_CAP_HOURS, default=0.0): cv.float_range(
                min=0.0, max=24.0
            ),
            cv.Optional(CONF_CURVE_STEP, default=60): cv.int_range(min=5, max=240),
            cv.Optional(CONF_CURVE_EDGE_STEP, default=30): cv.int_range(min=5, max=120),
            # Hour of the nightly push, at :30. Must be dark: a curve that
            # half-arrives mid-afternoon is visible in the tank.
            cv.Optional(CONF_PUSH_HOUR, default=1): cv.int_range(min=0, max=5),
            cv.Optional(CONF_TIME_ID): cv.use_id(time_.RealTimeClock),
            cv.Optional(CONF_STATUS): text_sensor.text_sensor_schema(),
            cv.Optional(CONF_CURVE): text_sensor.text_sensor_schema(),
            cv.Optional(CONF_POINTS): sensor.sensor_schema(accuracy_decimals=0),
            cv.Optional(CONF_DOSE): sensor.sensor_schema(
                unit_of_measurement="h", accuracy_decimals=2
            ),
            cv.Optional(CONF_CONNECTED): binary_sensor.binary_sensor_schema(),
        }
    )
    .extend(cv.polling_component_schema("60s"))
    .extend(ble_client.BLE_CLIENT_SCHEMA),
    _validate,
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await ble_client.register_ble_node(var, config)

    cg.add(var.set_latitude(config[CONF_LATITUDE]))
    cg.add(var.set_longitude(config[CONF_LONGITUDE]))
    cg.add(var.set_channel_count(config[CONF_CHANNEL_COUNT]))
    cg.add(var.set_channel_mix(config[CONF_CHANNEL_MIX]))
    cg.add(var.set_daylight_exponent(config[CONF_DAYLIGHT_EXPONENT]))
    # Hours on the face, minutes inside -- the solar integral is a sum of
    # per-minute levels, so minutes is the unit that needs no rounding.
    cg.add(var.set_dose_cap_minutes(int(round(config[CONF_DOSE_CAP_HOURS] * 60))))
    cg.add(var.set_curve_step(config[CONF_CURVE_STEP]))
    cg.add(var.set_curve_edge_step(config[CONF_CURVE_EDGE_STEP]))
    cg.add(var.set_push_hour(config[CONF_PUSH_HOUR]))

    if CONF_TIME_ID in config:
        cg.add(var.set_time(await cg.get_variable(config[CONF_TIME_ID])))

    for key, setter in (
        (CONF_STATUS, var.set_status_sensor),
        (CONF_CURVE, var.set_curve_sensor),
    ):
        if key in config:
            cg.add(setter(await text_sensor.new_text_sensor(config[key])))
    for key, setter in (
        (CONF_POINTS, var.set_points_sensor),
        (CONF_DOSE, var.set_dose_sensor),
    ):
        if key in config:
            cg.add(setter(await sensor.new_sensor(config[key])))
    if CONF_CONNECTED in config:
        cg.add(
            var.set_connected_sensor(
                await binary_sensor.new_binary_sensor(config[CONF_CONNECTED])
            )
        )


ACTION_SCHEMA = cv.Schema({cv.GenerateID(): cv.use_id(FluvalLight)})


@automation.register_action(
    "fluval_light.push_curve", PushCurveAction, ACTION_SCHEMA, synchronous=True
)
async def push_curve_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    return cg.new_Pvariable(action_id, template_arg, paren)


@automation.register_action(
    "fluval_light.sync_clock", SyncClockAction, ACTION_SCHEMA, synchronous=True
)
async def sync_clock_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    return cg.new_Pvariable(action_id, template_arg, paren)


@automation.register_action(
    "fluval_light.set_mode",
    SetModeAction,
    ACTION_SCHEMA.extend({cv.Required(CONF_MODE): cv.templatable(cv.int_range(min=0, max=2))}),
    synchronous=True,
)
async def set_mode_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg, paren)
    # cg.uint8, matching TEMPLATABLE_VALUE(uint8_t, mode) in the header.
    # The third argument is the C++ type of the generated lambda's return
    # value; a mismatch compiles but warns, and later ESPHome makes it an
    # error.
    cg.add(var.set_mode(await cg.templatable(config[CONF_MODE], args, cg.uint8)))
    return var
