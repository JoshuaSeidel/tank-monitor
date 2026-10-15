from esphome import automation, core, pins
import esphome.codegen as cg
from esphome.components import output
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_PERIOD, CONF_PIN

time_proportioning_ns = cg.esphome_ns.namespace("time_proportioning")
TimeProportioningOutput = time_proportioning_ns.class_(
    "TimeProportioningOutput", output.FloatOutput, cg.Component
)

CONF_MIN_ON_TIME = "min_on_time"
CONF_MIN_OFF_TIME = "min_off_time"
CONF_STATE_CHANGE_ACTION = "state_change_action"

CONFIG_SCHEMA = output.FLOAT_OUTPUT_SCHEMA.extend(
    {
        cv.Required(CONF_ID): cv.declare_id(TimeProportioningOutput),
        cv.Required(CONF_PIN): pins.gpio_output_pin_schema,
        # At a steady level d the relay makes one cycle per period: closed
        # d*period, open (1-d)*period -- the same contact rate slow_pwm gave.
        cv.Optional(CONF_PERIOD, default="900s"): cv.All(
            cv.positive_time_period_milliseconds,
            cv.Range(min=core.TimePeriod(seconds=10)),
        ),
        # Relay wear floors. A run shorter than these is lengthened, and the
        # extra (or missing) on-time is carried as credit, not lost.
        cv.Optional(CONF_MIN_ON_TIME, default="30s"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_MIN_OFF_TIME, default="30s"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_STATE_CHANGE_ACTION): automation.validate_automation(single=True),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await output.register_output(var, config)
    pin = await cg.gpio_pin_expression(config[CONF_PIN])
    cg.add(var.set_pin(pin))
    cg.add(var.set_period(config[CONF_PERIOD]))
    cg.add(var.set_min_on_time(config[CONF_MIN_ON_TIME]))
    cg.add(var.set_min_off_time(config[CONF_MIN_OFF_TIME]))
    if CONF_STATE_CHANGE_ACTION in config:
        await automation.build_automation(
            var.get_state_change_trigger(), [(bool, "state")], config[CONF_STATE_CHANGE_ACTION]
        )
