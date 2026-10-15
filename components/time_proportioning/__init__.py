"""Time-proportioning relay drive for the heater and fan.

An output platform (``output: - platform: time_proportioning``) that turns a
0-1 level into relay on/off time such that the time the relay is closed
equals the commanded level times the time elapsed -- across window
boundaries, level changes and new calls for heat. See
time_proportioning.h for the rule and why it replaced slow_pwm.
"""

CODEOWNERS = ["@tank-monitor"]
