#!/usr/bin/env python3
"""Generates packages/panel_p4_ui.yaml, the LVGL UI of the 10.1" P4 wall panel.

    python3 tools/gen_panel_p4_ui.py      (needs PyYAML)

Edit THIS file, never the generated YAML. The two tanks share one card
layout and one detail-screen layout; writing those twice by hand is how one
tank ends up with a fix the other never got.

The design is design/p4-panel/ (Gemini 3.8, approved 2026-10-29, revised by
REVISION-1.md): DESIGN.md has every colour, size and radius used below.

How the UI works
  - Widgets are built once, here, with neutral styles.
  - ONE interval lambda (every second) writes every label, bar, colour and
    flag from the globals in panel_p4_tank.yaml / panel_p4_feeds.yaml. State
    styling (stale, critical, night) is decided there, from data, every
    tick, so no widget can be left in a stale style by a missed event.
  - Values that are not known render as "--", never as a plausible number.
"""

from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parent.parent / "packages" / "panel_p4_ui.yaml"

# tools/p4_preview.py sets this to build the UI for ESPHome's SDL host
# platform, which has no MQTT: publishes become log lines and the night
# lambda is left to the preview's scenario.
PREVIEW = False


def publish(topic, payload):
    if PREVIEW:
        return {"logger.log": f"preview: would publish {payload} to {topic}"}
    return {"mqtt.publish": {"topic": topic, "payload": payload}}

# ---------------------------------------------------------------- palette
# DESIGN.md section 2.
C = {
    "canvas": 0x0B1015, "card1": 0x131B24, "card2": 0x19232F, "card3": 0x16202C,
    "btn": 0x1E293B, "btn_act": 0x212E3D, "border": 0x223142, "border2": 0x243447,
    "border_act": 0x334155,
    "text": 0xF8FAFC, "text2": 0xCBD5E1, "label": 0x94A3B8, "muted": 0x64748B,
    "cyan": 0x38BDF8, "cyan_deep": 0x0284C7, "cyan_bg": 0x0C4A6E,
    "heat": 0xFB923C, "heat_border": 0xEA580C, "heat_bg": 0x261711,
    "green": 0x10B981, "green_bg": 0x0F291E, "green_border": 0x059669, "band": 0x064E3B,
    "amber": 0xFBBF24, "amber_bg": 0x291B07, "amber_border": 0xD97706,
    "red": 0xEF4444, "red_bg": 0x2D0E12, "red_border": 0xDC2626,
    "stale_text": 0x64748B, "stale_border": 0x475569, "stale_bg": 0x0E141B,
    "track": 0x0F172A,
}


class Hex(int):
    """An int that YAML writes as 0xRRGGBB, so the output stays readable."""


yaml.SafeDumper.add_representer(
    Hex, lambda d, v: d.represent_scalar("tag:yaml.org,2002:int", f"0x{int(v):06X}"))
COL = {k: Hex(v) for k, v in C.items()}

# MDI codepoints, checked against @mdi/font 7.4.47's CSS.
ICON = {
    "fish": "\U000F023A", "fire": "\U000F0238", "fan": "\U000F0210",
    "bt": "\U000F00AF", "bt_off": "\U000F00B2", "wifi": "\U000F05A9",
    "wifi_off": "\U000F05AA", "alert": "\U000F0026", "octagon": "\U000F0029",
    "check": "\U000F05E0", "chevron": "\U000F0142", "back": "\U000F004D",
    "minus": "\U000F0374", "plus": "\U000F0415", "brain": "\U000F09D1",
    "sun": "\U000F0599", "night": "\U000F0594", "co2": "\U000F07E4",
    "bubbles": "\U000F05E3", "swap": "\U000F0BCE", "battery": "\U000F0079",
    "battery_alert": "\U000F0083", "filter": "\U000F0232", "water": "\U000F058C",
    "ha": "\U000F07D0", "heart": "\U000F05F6", "clock": "\U000F0150",
    "restart": "\U000F0709", "thermo": "\U000F050F", "water_minus": "\U000F1506",
    "water_plus": "\U000F150A",
}

TANKS = [
    # t: id prefix from the wrapper's vars; dual: second probe + gradient.
    # TDS/pH bands are the owner's targets (memory, 2026-09/10):
    #   75 gal: TDS 200-225, alert 260, never >300; pH 7.0-7.5.
    #   nano:   TDS under 300 (no lower bound set); pH >= 7.0 (emerald
    #           dwarf danios are the binding constraint; no upper bound set).
    # NaN = "no bound", drawn open-ended to the scale edge.
    dict(t="t75", name="75 GALLON", title="75 Gallon", tag="75 GAL", dual=True,
         water="62 gal", ph_src="Controller probe (BLE)",
         tds_lo=200, tds_hi=225, tds_alert=260, tds_min=150, tds_max=320,
         ph_lo=7.0, ph_hi=7.5, ph_min=6.4, ph_max=8.0, card_x=14),
    dict(t="t16", name="NANO", title="Nano", tag="SPEC 16", dual=False,
         water="14 gal", ph_src="Controller probe (Wi-Fi)",
         tds_lo="NAN", tds_hi=300, tds_alert=300, tds_min=150, tds_max=420,
         ph_lo=7.0, ph_hi="NAN", ph_min=6.4, ph_max=8.0, card_x=518),
]

# ------------------------------------------------------------ widget helpers


def _base(i, x=None, y=None, w=None, h=None, align=None, **st):
    d = {"id": i} if i else {}
    if align:
        d["align"] = align
    for k, v in (("x", x), ("y", y), ("width", w), ("height", h)):
        if v is not None:
            d[k] = v
    d.update(st)
    return d


def box(i, x, y, w, h, bg="card1", border="border", radius=12, bw=1, kids=(), align=None, **st):
    d = _base(i, x, y, w, h, align, bg_color=COL[bg], bg_opa="COVER",
              border_color=COL[border], border_width=bw, radius=radius,
              pad_all=0, scrollable=False, scrollbar_mode="OFF", **st)
    if kids:
        d["widgets"] = list(kids)
    return {"obj": d}


def label(i, text, font, color="text", x=None, y=None, w=None, align=None, **st):
    d = _base(i, x, y, w, None, align, text=text, text_font=font, text_color=COL[color], **st)
    return {"label": d}


def icon(i, name, size=18, color="cyan", x=None, y=None, align=None):
    return label(i, ICON[name], f"icon{size}", color, x, y, align=align)


def pill(i, text, color="green", bg="green_bg", border="green_border", font="f11",
         x=None, y=None, align=None, h=24):
    return box(i, x, y, "SIZE_CONTENT", h, bg=bg, border=border, radius=20,
               align=align, pad_left=10, pad_right=10,
               kids=[label(f"{i}_l", text, font, color, align="CENTER")])


def button(i, x, y, w, h, kids, bg="btn", border="border_act", radius=8, align=None, **actions):
    d = _base(i, x, y, w, h, align, bg_color=COL[bg], bg_opa="COVER",
              border_color=COL[border], border_width=1, radius=radius,
              shadow_width=0, pad_all=0, widgets=list(kids))
    d["pressed"] = {"bg_color": COL["btn_act"]}
    d.update(actions)
    return {"button": d}


def row(i, x, y, kids, gap=10, align=None, h=40, w="SIZE_CONTENT"):
    d = _base(i, x, y, w, h, align, bg_opa="TRANSP", border_width=0, pad_all=0,
              scrollable=False, scrollbar_mode="OFF",
              layout={"type": "FLEX", "flex_flow": "ROW", "pad_column": gap,
                      "flex_align_main": "START", "flex_align_cross": "CENTER",
                      "flex_align_track": "CENTER"},
              widgets=list(kids))
    return {"obj": d}


def track(i, x, y, w):
    """Target-range bar: track, the target band, and a value marker."""
    return box(i, x, y, w, 6, bg="track", border="track", radius=3, bw=0, kids=[
        box(f"{i}_band", 0, 0, 10, 6, bg="band", border="green_border", radius=3),
        box(f"{i}_mark", 0, -2, 4, 10, bg="green", border="green", radius=2, bw=0),
    ])


def bar(i, x, y, w, color, align=None):
    d = _base(i, x, y, w, 8, align, min_value=0, max_value=100, value=0,
              bg_color=COL["track"], radius=4,
              indicator={"bg_color": COL[color], "radius": 4})
    return {"bar": d}


def show_page(page):
    return [{"lvgl.page.show": {"id": page, "animation": "NONE"}}]

# ----------------------------------------------------------------- top bar


def top_bar():
    return [
        box("logo", 16, 12, 32, 32, bg="cyan_bg", border="cyan_deep", radius=8,
            kids=[icon(None, "fish", 18, "cyan", align="CENTER")]),
        label("brand", "TANK MONITOR", "f15", x=60, y=19),
        pill("status_pill", "ALL SYSTEMS NORMAL", font="f13", align="TOP_MID", y=12, h=32),
        row("top_right", -12, 8, align="TOP_RIGHT", h=40, kids=[
            pill("mqtt_pill", "MQTT", "text2", "card1", "border", font="f12", h=30),
            pill("ble_pill", "BLE 2/2", "text2", "card1", "border", font="f12", h=30),
            label("clock_lbl", "--:--", "f18"),
            label("date", "", "f12", "label"),
        ]),
        # Alert banner: covers the brand and status pill while any alert is
        # active. Hidden until the update lambda finds one.
        box("alert_banner", 8, 4, 820, 48, bg="red_bg", border="red_border", radius=10,
            hidden=True, kids=[
                icon("alert_icon", "octagon", 24, "red", x=14, align="LEFT_MID"),
                label("alert_title", "", "f15", x=50, y=6, w=560, long_mode="DOT"),
                label("alert_msg", "", "f12", "text2", x=50, y=26, w=560, long_mode="DOT"),
                button("alert_btn", -8, 0, 180, 36, align="RIGHT_MID", bg="red_border",
                       border="red", kids=[label("alert_btn_l", "OPEN", "f13", align="CENTER")],
                       on_click=[{"if": {
                           "condition": {"lambda": "return id(alert_target) == 1;"},
                           "then": show_page("page_t75"),
                           "else": [{"if": {
                               "condition": {"lambda": "return id(alert_target) == 2;"},
                               "then": show_page("page_t16")}}]}}]),
            ]),
    ]

# --------------------------------------------------------------- home cards


def tank_card(T):
    t, X = T["t"], T["card_x"]
    hero_kids = [
        label(f"{t}_temp", "--", "f58", x=14, y=16),
        label(f"{t}_unit", "°F", "f26", "cyan", x=140, y=40),
        box(f"{t}_sp_box", -12, 12, "SIZE_CONTENT", 26, bg="card1", border="border_act",
            radius=8, align="TOP_RIGHT", pad_left=10, pad_right=10,
            kids=[label(f"{t}_sp", "Setpoint --", "f13", "label", align="CENTER")]),
        label(f"{t}_probes", "", "f12", "label", align="TOP_RIGHT", x=-12, y=48),
        label(f"{t}_drift", "", "f12", "green", align="TOP_RIGHT", x=-12, y=68),
    ]
    act = lambda k, x, w, ic, cap, color: box(  # noqa: E731
        f"{t}_{k}_tile", x, 156, w, 58, bg="card3", border="border", radius=8, kids=[
            icon(f"{t}_{k}_icon", ic, 18, "muted", x=12, align="LEFT_MID"),
            label(f"{t}_{k}_cap", cap, "f11", "label", x=42, y=10),
            label(f"{t}_{k}_val", "--", "f15", x=42, y=28),
            bar(f"{t}_{k}_bar", -12, 0, 48, color, align="RIGHT_MID"),
        ])
    metric = lambda k, x, w, cap, unit: box(  # noqa: E731
        f"{t}_{k}_tile", x, 226, w, 88, bg="card3", border="border", radius=8, kids=[
            label(f"{t}_{k}_cap", cap, "f11", "label", x=12, y=10),
            label(f"{t}_{k}_tgt", "", "f11", "label", align="TOP_RIGHT", x=-12, y=10),
            label(f"{t}_{k}_val", "--", "f26", x=12, y=30),
            label(f"{t}_{k}_unit", unit, "f13", "label", x=80, y=42),
            label(f"{t}_{k}_side", "", "f12", "cyan", align="TOP_RIGHT", x=-12, y=40),
            track(f"{t}_{k}_trk", 12, 70, w - 24),
        ])
    return box(f"{t}_card", X, 66, 492, 406, bg="card1", border="border", radius=14, kids=[
        row(f"{t}_head", 16, 8, h=36, gap=10, kids=[
            label(f"{t}_title", T["name"], "f18"),
            pill(f"{t}_tag", T["tag"], "label", "card2", "border_act", h=22),
            box(f"{t}_stale", None, None, "SIZE_CONTENT", 22, bg="amber_bg",
                border="amber_border", radius=20, pad_left=10, pad_right=10, hidden=True,
                kids=[label(f"{t}_stale_l", "STALE", "f11", "amber", align="CENTER")]),
        ]),
        label(f"{t}_link", "BLE --", "f12", "cyan", align="TOP_RIGHT", x=-16, y=18),
        box(f"{t}_hero", 16, 48, 460, 96, bg="card2", border="border2", radius=10, kids=hero_kids),
        act("heat", 16, 222, "fire", "HEATER", "heat"),
        act("fan", 250, 226, "fan", "COOLING FAN", "cyan"),
        metric("tds", 16, 222, "TDS", "ppm"),
        metric("ph", 250, 226, "PH", "pH"),
        box(None, 16, 326, 460, 1, bg="border", border="border", radius=0, bw=0),
        row(f"{t}_foot", 16, 340, h=40, gap=16, kids=[
            label(f"{t}_f_lux", "-- lux", "f12", "label"),
            label(f"{t}_f_co2", "CO2 --", "f12", "label"),
            label(f"{t}_f_bub", "Bubbler --", "f12", "label"),
            label(f"{t}_f_model", "Model --", "f12", "label"),
        ]),
        button(f"{t}_details", 382, 338, 94, 42, on_click=show_page(f"page_{t}"), kids=[
            row(None, 0, 0, align="CENTER", gap=6, h=24, kids=[
                label(None, "Details", "f13"), icon(None, "chevron", 18, "text2")])]),
    ])


def strip():
    return [
        box("ro_card", 14, 484, 346, 104, bg="card1", border="border", radius=12, kids=[
            icon(None, "filter", 18, "cyan", x=14, y=12),
            label(None, "RO FILTER OUTPUT", "f13", x=40, y=14),
            pill("ro_pill", "--", "cyan", "cyan_bg", "cyan_deep", align="TOP_RIGHT", x=-12, y=10),
            label("ro_val", "--", "f26", x=14, y=38),
            label("ro_of", "/ -- gal", "f13", "label", x=70, y=48),
            label("ro_pct", "", "f12", "label", align="TOP_RIGHT", x=-14, y=48),
            bar("ro_bar", 14, 72, 318, "cyan_deep"),
            label("ro_reached", "", "f11", "muted", x=14, y=84),
            label("ro_total", "", "f11", "muted", align="TOP_RIGHT", x=-14, y=84),
        ]),
        box("wc_card", 370, 484, 388, 104, bg="card1", border="border", radius=12, kids=[
            icon(None, "swap", 18, "cyan", x=14, y=12),
            label(None, "WATER CHANGE METER", "f13", x=40, y=14),
            label("wc_batt_h", "--", "f12", "green", align="TOP_RIGHT", x=-14, y=14),
            label("wc_last_h", "", "f12", "text2", x=14, y=46),
            label("wc_mode_h", "", "f11", "muted", x=14, y=70),
            button("wc_open", -14, 12, 150, 48, align="RIGHT_MID", bg="cyan_deep",
                   border="cyan", on_click=show_page("page_wc"),
                   kids=[label(None, "WATER CHANGE", "f13", align="CENTER")]),
        ]),
        box("ha_card", 770, 484, 240, 104, bg="card1", border="border", radius=12, kids=[
            icon(None, "ha", 18, "cyan", x=14, y=12),
            label(None, "HOME ASSISTANT", "f13", x=40, y=14),
            label("ha_k1", "Days since loss", "f12", "label", x=14, y=44),
            label("ha_v1", "--", "f12", "text", align="TOP_RIGHT", x=-14, y=44),
            label("ha_k2", "Active alerts", "f12", "label", x=14, y=64),
            label("ha_v2", "--", "f12", "text", align="TOP_RIGHT", x=-14, y=64),
            label("ha_k3", "Civil dusk", "f12", "label", x=14, y=84),
            label("ha_v3", "--", "f12", "text", align="TOP_RIGHT", x=-14, y=84),
        ]),
    ]

# ------------------------------------------------------------- detail page


def detail_page(T):
    t, dual = T["t"], T["dual"]

    def sp_step(delta):
        return [{"lambda": (
            f"float base = std::isnan(id({t}_sp_pending)) ? id({t}_sp) : id({t}_sp_pending);\n"
            f"if (std::isnan(base)) return;\n"
            f"base = roundf((base + ({delta})) * 10.0f) / 10.0f;\n"
            f"id({t}_sp_pending) = std::min(80.0f, std::max(70.0f, base));\n")},
            {"script.execute": f"{t}_send_sp"}]

    probes = []
    if dual:
        probes = [
            box(None, 16, 44, 166, 70, bg="card2", border="border2", radius=8, kids=[
                label(None, "PROBE A", "f11", "label", x=12, y=10),
                label(f"{t}_d_pa", "--", "f26", x=12, y=30)]),
            box(None, 194, 44, 166, 70, bg="card2", border="border2", radius=8, kids=[
                label(None, "PROBE B", "f11", "label", x=12, y=10),
                label(f"{t}_d_pb", "--", "f26", x=12, y=30)]),
            box(None, 16, 124, 344, 52, bg="card3", border="border", radius=8, kids=[
                label(None, "A - B GRADIENT", "f11", "label", x=12, y=8),
                label(f"{t}_d_grad", "--", "f15", "cyan", x=12, y=24),
                label(f"{t}_d_drift", "", "f12", "green", align="RIGHT_MID", x=-12)]),
        ]
    else:
        probes = [
            box(None, 16, 44, 344, 70, bg="card2", border="border2", radius=8, kids=[
                label(None, "WATER TEMPERATURE PROBE", "f11", "label", x=12, y=10),
                label(f"{t}_d_pa", "--", "f26", x=12, y=30),
                label(f"{t}_d_drift", "", "f12", "green", align="RIGHT_MID", x=-12)]),
            box(None, 16, 124, 344, 52, bg="card3", border="border", radius=8, kids=[
                label(None, "CONTROL BAND", "f11", "label", x=12, y=8),
                label(f"{t}_d_grad", "--", "f15", "cyan", x=12, y=24)]),
        ]

    act_row = lambda k, y, ic, cap, color: box(  # noqa: E731
        f"{t}_d_{k}", 16, y, 344, 50, bg="card3", border="border", radius=8, kids=[
            icon(f"{t}_d_{k}_icon", ic, 18, "muted", x=12, align="LEFT_MID"),
            label(f"{t}_d_{k}_cap", cap, "f12", "label", x=42, y=8),
            label(f"{t}_d_{k}_sub", "", "f11", "muted", x=42, y=27),
            label(f"{t}_d_{k}_pct", "--", "f15", align="RIGHT_MID", x=-130),
            bar(f"{t}_d_{k}_bar", -12, 0, 104, color, align="RIGHT_MID"),
        ])

    tab = lambda i, mode, x, w, text: button(  # noqa: E731
        f"{t}_tab{i}", x, 12, w, 32, radius=8,
        on_click=[{"lambda": f"id({t}_chart_mode) = {mode}; id(redraw_charts) = true;"}],
        kids=[label(f"{t}_tab{i}_l", text, "f12", align="CENTER")])

    plot_kids = [box(f"{t}_grid{i}", 0, 34 * i + 17, 532, 1, bg="border", border="border",
                     radius=0, bw=0) for i in range(5)]
    plot_kids += [
        {"line": {"id": f"{t}_ln_sp", "points": ["0,0", "1,0"], "line_width": 2,
                  "line_color": COL["green"], "line_opa": "70%"}},
        {"line": {"id": f"{t}_ln_b", "points": ["0,0", "1,0"], "line_width": 2,
                  "line_color": COL["cyan_deep"], "line_rounded": True}},
        {"line": {"id": f"{t}_ln_a", "points": ["0,0", "1,0"], "line_width": 3,
                  "line_color": COL["cyan"], "line_rounded": True}},
        label(f"{t}_plot_empty", "Collecting history (one point every 15 min)", "f12",
              "muted", align="CENTER"),
    ]

    widgets = [
        button(f"{t}_home", 16, 10, 104, 44, on_click=show_page("page_home"), kids=[
            row(None, 0, 0, align="CENTER", gap=6, h=24, kids=[
                icon(None, "back", 18, "text2"), label(None, "Home", "f13")])]),
        row(None, 136, 10, h=44, gap=12, kids=[
            label(None, T["name"], "f18"),
            box(f"{t}_d_link", None, None, "SIZE_CONTENT", 26, bg="card1", border="border_act",
                radius=20, pad_left=10, pad_right=10,
                kids=[label(f"{t}_d_link_l", "BLE --", "f12", "cyan", align="CENTER")]),
        ]),
        row(None, -16, 10, align="TOP_RIGHT", h=44, gap=10, kids=[
            box(f"{t}_d_safety", None, None, "SIZE_CONTENT", 30, bg="green_bg",
                border="green_border", radius=20, pad_left=12, pad_right=12,
                kids=[label(f"{t}_d_safety_l", "SAFETY --", "f12", "green", align="CENTER")]),
            box(None, None, None, "SIZE_CONTENT", 30, bg="card1", border="border_act",
                radius=20, pad_left=12, pad_right=12,
                kids=[label(None, f"WATER ~{T['water'].upper()}", "f12", "text2", align="CENTER")]),
        ]),
        # ---- setpoint card
        box(None, 14, 66, 376, 204, bg="card1", border="border", radius=14, kids=[
            label(None, "TEMPERATURE SETPOINT", "f13", "label", x=16, y=16),
            label(f"{t}_d_swing", "", "f11", "cyan", align="TOP_RIGHT", x=-16, y=18),
            box(None, 16, 44, 344, 84, bg="card2", border="border2", radius=10, kids=[
                button(f"{t}_minus", 12, 0, 56, 56, align="LEFT_MID",
                       on_click=sp_step(-0.1), on_long_press_repeat=sp_step(-0.1),
                       kids=[icon(None, "minus", 24, "text", align="CENTER")]),
                label(f"{t}_d_sp", "--", "f42", align="CENTER", y=-10),
                label(f"{t}_d_band", "", "f12", "cyan", align="CENTER", y=26),
                button(f"{t}_plus", -12, 0, 56, 56, align="RIGHT_MID",
                       on_click=sp_step(0.1), on_long_press_repeat=sp_step(0.1),
                       kids=[icon(None, "plus", 24, "text", align="CENTER")]),
            ]),
            box(None, 16, 138, 344, 56, bg="card3", border="cyan_deep", radius=10, kids=[
                icon(None, "brain", 24, "cyan", x=12, align="LEFT_MID"),
                label(None, "Adaptive heating model", "f13", x=46, y=10),
                label(f"{t}_d_conf", "Confidence --", "f11", "label", x=46, y=30),
                button(f"{t}_learn", -8, 0, 128, 40, align="RIGHT_MID", radius=20,
                       on_click=[{"lambda": f"id({t}_learn) = !id({t}_learn);"},
                                 {"script.execute": f"{t}_send_learn"}],
                       kids=[label(f"{t}_learn_l", "LEARNING --", "f12", align="CENTER")]),
            ]),
        ]),
        # ---- probes + actuators card
        box(None, 14, 282, 376, 306, bg="card1", border="border", radius=14, kids=[
            label(None, "PROBES & HEATING" if dual else "PROBE & HEATING", "f13", "label", x=16, y=16),
            label(None, "CONTROLLER BLE", "f11", "cyan", align="TOP_RIGHT", x=-16, y=18),
            *probes,
            act_row("heat", 186, "fire", "HEATER", "heat"),
            act_row("fan", 244, "fan", "COOLING FAN", "cyan"),
        ]),
        # ---- TDS / pH
        box(None, 402, 66, 296, 116, bg="card1", border="border", radius=14, kids=[
            label(None, "TDS", "f13", "label", x=16, y=14),
            label(f"{t}_d_tds_st", "", "f12", "green", align="TOP_RIGHT", x=-16, y=16),
            label(f"{t}_d_tds", "--", "f32", x=16, y=36),
            label(f"{t}_d_tds_u", "ppm live", "f13", "label", x=96, y=52),
            label(f"{t}_d_tds_m", "", "f13", "cyan", align="TOP_RIGHT", x=-16, y=50),
            track(f"{t}_d_tds_trk", 16, 82, 264),
            label(f"{t}_d_tds_tgt", "", "f11", "muted", x=16, y=94),
        ]),
        box(None, 710, 66, 300, 116, bg="card1", border="border", radius=14, kids=[
            label(None, "PH", "f13", "label", x=16, y=14),
            label(f"{t}_d_ph_st", "", "f12", "green", align="TOP_RIGHT", x=-16, y=16),
            label(f"{t}_d_ph", "--", "f32", x=16, y=36),
            label(None, "pH", "f13", "label", x=100, y=52),
            label(f"{t}_d_ph_tgt", "", "f12", "text2", align="TOP_RIGHT", x=-16, y=50),
            track(f"{t}_d_ph_trk", 16, 82, 268),
            label(None, T["ph_src"], "f11", "muted", x=16, y=94),
        ]),
        # ---- 24 h chart
        box(None, 402, 192, 608, 266, bg="card1", border="border", radius=14, kids=[
            tab(0, 0, 16, 120, "Temperature"),
            tab(1, 1, 144, 70, "TDS"),
            tab(2, 2, 222, 60, "pH"),
            label(f"{t}_legend", "", "f11", "label", align="TOP_RIGHT", x=-16, y=22),
            *[label(f"{t}_yl{i}", "", "f11", "muted", x=12, y=56 + 34 * i + 10) for i in range(5)],
            box(f"{t}_plot", 60, 56, 532, 170, bg="canvas", border="border", radius=8,
                kids=plot_kids),
            label(None, "-24 h", "f11", "muted", x=60, y=232),
            label(None, "-18 h", "f11", "muted", x=60 + 133 - 14, y=232),
            label(None, "-12 h", "f11", "muted", x=60 + 266 - 14, y=232),
            label(None, "-6 h", "f11", "muted", x=60 + 399 - 12, y=232),
            label(None, "Now", "f11", "cyan", x=60 + 532 - 26, y=232),
        ]),
        # ---- light / CO2 / controller
        box(None, 402, 470, 608, 118, bg="card1", border="border", radius=14, kids=[
            icon(None, "sun", 18, "amber", x=16, y=16),
            label(None, "LIGHT", "f12", "label", x=42, y=18),
            label(f"{t}_d_lux", "--", "f18", x=16, y=48),
            label(f"{t}_d_sun", "", "f11", "muted", x=16, y=80, w=180, long_mode="WRAP"),
            icon(None, "co2", 18, "cyan", x=216, y=16),
            label(None, "CO2 & AERATION", "f12", "label", x=242, y=18),
            label(f"{t}_d_co2", "--", "f18", x=216, y=48),
            label(f"{t}_d_bub", "", "f12", "label", x=216, y=80),
            icon(None, "heart", 18, "green", x=416, y=16),
            label(None, "CONTROLLER", "f12", "label", x=442, y=18),
            label(f"{t}_d_safe2", "--", "f18", x=416, y=48),
            label(f"{t}_d_model", "", "f12", "label", x=416, y=80),
        ]),
    ]
    return {"id": f"page_{t}", "bg_color": COL["canvas"], "scrollable": False,
            "widgets": widgets}

# ------------------------------------------------------- water change page


def wc_page():
    pub = publish
    ro_step = lambda d: [  # noqa: E731
        {"lambda": (
            "float base = std::isnan(id(ro_target_pending)) ? id(ro_target) : id(ro_target_pending);\n"
            "if (std::isnan(base)) return;\n"
            f"id(ro_target_pending) = std::min(20.0f, std::max(0.5f, roundf((base + ({d})) * 2.0f) / 2.0f));\n")},
        {"script.execute": "ro_send_target"}]
    return {"id": "page_wc", "bg_color": COL["canvas"], "scrollable": False, "widgets": [
        button("wc_home", 16, 10, 104, 44, on_click=show_page("page_home"), kids=[
            row(None, 0, 0, align="CENTER", gap=6, h=24, kids=[
                icon(None, "back", 18, "text2"), label(None, "Home", "f13")])]),
        row(None, 136, 10, h=44, gap=12, kids=[
            label(None, "WATER CHANGE", "f18"),
            box("wc_state", None, None, "SIZE_CONTENT", 30, bg="cyan_bg", border="cyan_deep",
                radius=20, pad_left=12, pad_right=12,
                kids=[label("wc_state_l", "--", "f12", "cyan", align="CENTER")]),
        ]),
        row(None, -16, 10, align="TOP_RIGHT", h=44, gap=10, kids=[
            box("wc_batt_pill", None, None, "SIZE_CONTENT", 30, bg="green_bg",
                border="green_border", radius=20, pad_left=12, pad_right=12,
                kids=[label("wc_batt_l", "Hose battery --", "f12", "green", align="CENTER")]),
            box("wc_mqtt_pill", None, None, "SIZE_CONTENT", 30, bg="card1", border="border_act",
                radius=20, pad_left=12, pad_right=12,
                kids=[label("wc_mqtt_l", "MQTT --", "f12", "text2", align="CENTER")]),
        ]),
        button("wc_drain", 14, 66, 306, 56, on_click=[
            pub("water-flow-change/select/mode/command", "Draining"),
            {"lambda": "id(wc_draining) = true;"}],
            kids=[row(None, 0, 0, align="CENTER", gap=8, h=24, kids=[
                icon(None, "water_minus", 18, "heat"),
                label("wc_drain_l", "DRAINING", "f15")])]),
        button("wc_fill", 330, 66, 306, 56, on_click=[
            pub("water-flow-change/select/mode/command", "Refilling"),
            {"lambda": "id(wc_draining) = false;"}],
            kids=[row(None, 0, 0, align="CENTER", gap=8, h=24, kids=[
                icon(None, "water_plus", 18, "cyan"),
                label("wc_fill_l", "REFILLING", "f15")])]),
        box(None, 14, 134, 622, 388, bg="card1", border="border", radius=14, kids=[
            label(None, "75 GALLON", "f13", "label", x=20, y=18),
            label("wc_vol", "", "f12", "cyan", align="TOP_RIGHT", x=-20, y=20),
            label("wc_big_cap", "WATER REMOVED THIS CHANGE", "f11", "heat", x=20, y=96),
            label("wc_big", "--", "f58", x=20, y=116),
            label("wc_big_u", "gal", "f26", "cyan", x=150, y=146),
            label("wc_other", "", "f13", "label", x=20, y=186, w=300),
            {"arc": {"id": "wc_arc", "x": -24, "y": 40, "align": "TOP_RIGHT",
                     "width": 240, "height": 240, "rotation": 180, "start_angle": 0,
                     "end_angle": 180, "min_value": 0, "max_value": 1000, "value": 0,
                     "adjustable": False, "arc_width": 18, "arc_color": COL["btn"],
                     "arc_rounded": True,
                     "indicator": {"arc_width": 18, "arc_color": COL["heat"], "arc_rounded": True},
                     "knob": {"bg_opa": "TRANSP", "pad_all": 0}}},
            label("wc_pct", "--", "f32", align="TOP_RIGHT", x=-104, y=130),
            label(None, "OF TANK CHANGED", "f11", "label", align="TOP_RIGHT", x=-92, y=172),
            box(None, 20, 268, 582, 100, bg="card3", border="border", radius=10, kids=[
                label(None, "FLOW", "f11", "label", x=16, y=14),
                label("wc_rate", "--", "f18", "cyan", x=16, y=36),
                label("wc_flowing", "", "f11", "muted", x=16, y=66),
                label(None, "WATER ADDED", "f11", "label", x=210, y=14),
                label("wc_added", "--", "f18", x=210, y=36),
                label(None, "NET CHANGE", "f11", "label", x=404, y=14),
                label("wc_net", "--", "f18", x=404, y=36),
                label(None, "WATER REMOVED", "f11", "label", x=210, y=66),
                label("wc_removed2", "--", "f11", "text2", x=310, y=66),
            ]),
        ]),
        button("wc_new", 14, 534, 622, 56, bg="card1", border="heat_border",
               on_long_press=[pub("water-flow-change/button/new_water_change/command", "PRESS")],
               kids=[row(None, 0, 0, align="CENTER", gap=8, h=24, kids=[
                   icon(None, "restart", 18, "heat"),
                   label(None, "HOLD TO START A NEW WATER CHANGE", "f13", "heat")])]),
        box(None, 648, 66, 362, 380, bg="card1", border="border", radius=14, kids=[
            icon(None, "filter", 18, "cyan", x=18, y=18),
            label(None, "RO FILTER", "f15", x=46, y=19),
            box("ro_online_pill", -16, 14, "SIZE_CONTENT", 26, bg="cyan_bg", border="cyan_deep",
                radius=20, align="TOP_RIGHT", pad_left=10, pad_right=10,
                kids=[label("ro_online_l", "--", "f11", "cyan", align="CENTER")]),
            box(None, 16, 56, 330, 112, bg="card2", border="border2", radius=10, kids=[
                label(None, "THIS FILL", "f11", "label", x=14, y=12),
                label("ro_d_flow", "", "f12", "cyan", align="TOP_RIGHT", x=-14, y=12),
                label("ro_d_val", "--", "f32", x=14, y=34),
                label("ro_d_of", "", "f13", "label", align="TOP_RIGHT", x=-14, y=52),
                bar("ro_d_bar", 14, 88, 300, "cyan_deep"),
            ]),
            label(None, "Target reached", "f12", "label", x=18, y=184),
            label("ro_d_reached", "--", "f12", align="TOP_RIGHT", x=-18, y=184),
            label(None, "Lifetime produced", "f12", "label", x=18, y=208),
            label("ro_d_total", "--", "f12", align="TOP_RIGHT", x=-18, y=208),
            label(None, "FILL TARGET", "f11", "label", x=18, y=240),
            box(None, 16, 258, 330, 56, bg="card2", border="border2", radius=10, kids=[
                button("ro_minus", 6, 0, 48, 44, align="LEFT_MID", on_click=ro_step(-0.5),
                       kids=[icon(None, "minus", 18, "text", align="CENTER")]),
                label("ro_d_tgt", "--", "f18", align="CENTER"),
                button("ro_plus", -6, 0, 48, 44, align="RIGHT_MID", on_click=ro_step(0.5),
                       kids=[icon(None, "plus", 18, "text", align="CENTER")]),
            ]),
            button("ro_reset", 16, 324, 330, 44,
                   on_long_press=[pub("water-flow-ro/button/reset_fill/command", "PRESS")],
                   kids=[label(None, "HOLD TO RESET FILL COUNTER", "f12", "text2", align="CENTER")]),
        ]),
        box(None, 648, 458, 362, 130, bg="card1", border="border", radius=14, kids=[
            label(None, "HOSE METER", "f12", "label", x=18, y=16),
            label(None, "Battery", "f12", "label", x=18, y=44),
            label("wc_d_batt", "--", "f12", align="TOP_RIGHT", x=-18, y=44),
            label(None, "Last change started", "f12", "label", x=18, y=70),
            label("wc_d_last", "--", "f12", align="TOP_RIGHT", x=-18, y=70),
            label(None, "75 Gallon water volume", "f12", "label", x=18, y=96),
            label("wc_d_vol", "--", "f12", align="TOP_RIGHT", x=-18, y=96),
        ]),
    ]}

# ------------------------------------------------------------ update lambda

UPDATE_COMMON = r"""
// ---------------------------------------------------------------- helpers
const uint32_t now_ms = millis();
auto txt = [](lv_obj_t *o, const char *fmt, ...) {
  char b[160];
  va_list ap; va_start(ap, fmt); vsnprintf(b, sizeof(b), fmt, ap); va_end(ap);
  if (strcmp(lv_label_get_text(o), b) != 0) lv_label_set_text(o, b);
};
auto col = [](lv_obj_t *o, uint32_t c) { lv_obj_set_style_text_color(o, lv_color_hex(c), 0); };
auto bg = [](lv_obj_t *o, uint32_t fill, uint32_t border) {
  lv_obj_set_style_bg_color(o, lv_color_hex(fill), 0);
  lv_obj_set_style_border_color(o, lv_color_hex(border), 0);
};
auto show = [](lv_obj_t *o, bool on) {
  if (on) lv_obj_remove_flag(o, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
};
auto age = [](uint32_t ms, char *b, size_t n) {
  const uint32_t s = ms / 1000;
  if (s < 90) snprintf(b, n, "%us", (unsigned) s);
  else if (s < 5400) snprintf(b, n, "%um", (unsigned) (s / 60));
  else snprintf(b, n, "%uh", (unsigned) (s / 3600));
};
// Place a target-range track's band and marker. NaN bound = open-ended.
auto range = [](lv_obj_t *trk, lv_obj_t *band, lv_obj_t *mark, float v,
                float lo, float hi, float mn, float mx, uint32_t mark_col) {
  const int w = lv_obj_get_width(trk);
  auto px = [&](float x) { return (int) roundf((std::min(mx, std::max(mn, x)) - mn) / (mx - mn) * (w - 4)); };
  const int a = std::isnan(lo) ? 0 : px(lo), b = std::isnan(hi) ? w : px(hi);
  lv_obj_set_pos(band, a, 0); lv_obj_set_width(band, std::max(4, b - a));
  if (std::isnan(v)) { lv_obj_add_flag(mark, LV_OBJ_FLAG_HIDDEN); return; }
  lv_obj_remove_flag(mark, LV_OBJ_FLAG_HIDDEN);
  lv_obj_set_pos(mark, px(v), -2);
  lv_obj_set_style_bg_color(mark, lv_color_hex(mark_col), 0);
};
const bool night = id(night_on);
const uint32_t C_TEXT = night ? 0x8C9CAE : 0xF8FAFC;
const uint32_t C_HEAD = night ? 0xC28238 : 0xF8FAFC;
const uint32_t C_UNIT = night ? 0x7D5627 : 0x38BDF8;
const uint32_t C_CARD = night ? 0x080D13 : 0x131B24;
const uint32_t C_CARD2 = night ? 0x0A1118 : 0x19232F;
const uint32_t C_BORDER = night ? 0x131C26 : 0x223142;
lv_obj_set_style_bg_color(id(page_home)->obj, lv_color_hex(night ? 0x040608 : 0x0B1015), 0);

// ----------------------------------------------------------- top bar
auto tnow = id(sntp_time).now();
if (tnow.is_valid()) {
  txt(id(clock_lbl), "%s", tnow.strftime("%-I:%M %p").c_str());
  txt(id(date), "%s", tnow.strftime("%a %b %-d").c_str());
}
const bool mqtt_ok = id(mqtt_up);
txt(id(mqtt_pill_l), mqtt_ok ? "MQTT Connected" : "MQTT Down");
col(id(mqtt_pill_l), mqtt_ok ? 0xCBD5E1 : 0xFBBF24);
bg(id(mqtt_pill), mqtt_ok ? 0x131B24 : 0x291B07, mqtt_ok ? 0x223142 : 0xD97706);
const bool l75 = id(t75_stamp_ms) != 0 && now_ms - id(t75_stamp_ms) < 45000;
const bool l16 = id(t16_stamp_ms) != 0 && now_ms - id(t16_stamp_ms) < 45000;
txt(id(ble_pill_l), "BLE %d/2", (int) l75 + (int) l16);
col(id(ble_pill_l), (l75 && l16) ? 0xCBD5E1 : 0xFBBF24);

// ------------------------------------------------------------ alerts
int n_crit = 0, n_warn = 0;
std::string top_title, top_msg;
bool top_is_crit = false;
for (auto &kv : id(alerts)) {
  // "level|title|message"
  const std::string &v = kv.second;
  const size_t a = v.find('|'), b = v.find('|', a == std::string::npos ? 0 : a + 1);
  if (a == std::string::npos || b == std::string::npos) continue;
  const bool crit = v.compare(0, a, "critical") == 0;
  if (crit) n_crit++; else n_warn++;
  if (top_title.empty() || (crit && !top_is_crit)) {
    top_title = v.substr(a + 1, b - a - 1);
    top_msg = v.substr(b + 1);
    top_is_crit = crit;
  }
}
const int n_alerts = n_crit + n_warn;
show(id(alert_banner), n_alerts > 0);
// The banner covers the left of the top bar; keep only the clock beside it.
show(id(mqtt_pill), n_alerts == 0);
show(id(ble_pill), n_alerts == 0);
if (n_alerts > 0) {
  txt(id(alert_title), "%s", top_title.c_str());
  txt(id(alert_msg), "%s", top_msg.c_str());
  bg(id(alert_banner), top_is_crit ? 0x2D0E12 : 0x291B07, top_is_crit ? 0xDC2626 : 0xD97706);
  col(id(alert_icon), top_is_crit ? 0xEF4444 : 0xFBBF24);
  const bool is75 = top_title.find("75") != std::string::npos;
  const bool is16 = !is75 && (top_title.find("Nano") != std::string::npos ||
                              top_title.find("nano") != std::string::npos);
  id(alert_target) = is75 ? 1 : (is16 ? 2 : 0);
  show(id(alert_btn), is75 || is16);
  txt(id(alert_btn_l), is75 ? "OPEN 75 GALLON" : "OPEN NANO");
}
{
  char b[64]; uint32_t fill, border, text;
  if (n_crit > 0) {
    snprintf(b, sizeof(b), "%d CRITICAL ALERT%s", n_crit, n_crit > 1 ? "S" : "");
    fill = 0x2D0E12; border = 0xDC2626; text = 0xEF4444;
  } else if (!l75 || !l16) {
    char a[12]; age(now_ms - (!l75 ? id(t75_stamp_ms) : id(t16_stamp_ms)), a, sizeof(a));
    const bool never = (!l75 ? id(t75_stamp_ms) : id(t16_stamp_ms)) == 0;
    if (never) snprintf(b, sizeof(b), "WAITING FOR %s LINK", !l75 ? "75 GALLON" : "NANO");
    else snprintf(b, sizeof(b), "%s LINK DOWN %s", !l75 ? "75 GALLON" : "NANO", a);
    fill = 0x291B07; border = 0xD97706; text = 0xFBBF24;
  } else if (n_warn > 0) {
    snprintf(b, sizeof(b), "%d WARNING%s", n_warn, n_warn > 1 ? "S" : "");
    fill = 0x291B07; border = 0xD97706; text = 0xFBBF24;
  } else {
    snprintf(b, sizeof(b), "ALL SYSTEMS NORMAL");
    fill = 0x0F291E; border = 0x059669; text = 0x10B981;
  }
  if (night) { fill = 0x080D13; border = 0x131C26; text = text == 0x10B981 ? 0x366B56 : text; }
  txt(id(status_pill_l), "%s", b);
  col(id(status_pill_l), text);
  bg(id(status_pill), fill, border);
}

// ----------------------------------------------------- bottom strip
{
  for (lv_obj_t *c : {id(ro_card), id(wc_card), id(ha_card)}) bg(c, C_CARD, C_BORDER);
  bg(id(wc_open), night ? 0x0A1118 : 0x0284C7, night ? 0x131C26 : 0x38BDF8);
  bg(id(logo), night ? 0x080D13 : 0x0C4A6E, night ? 0x131C26 : 0x0284C7);
  col(id(brand), C_TEXT);
  col(id(clock_lbl), C_TEXT);
  const bool ro_on = id(ro_online);
  if (!ro_on) { txt(id(ro_pill_l), "OFFLINE"); col(id(ro_pill_l), 0xFBBF24); bg(id(ro_pill), 0x291B07, 0xD97706); }
  else if (id(ro_flowing)) { txt(id(ro_pill_l), "FLOWING %.2f GPM", std::isnan(id(ro_rate)) ? 0.0f : id(ro_rate)); col(id(ro_pill_l), 0x38BDF8); bg(id(ro_pill), 0x0C4A6E, 0x0284C7); }
  else { txt(id(ro_pill_l), "IDLE"); col(id(ro_pill_l), 0x94A3B8); bg(id(ro_pill), 0x19232F, 0x334155); }
  if (std::isnan(id(ro_fill))) txt(id(ro_val), "--"); else txt(id(ro_val), "%.1f", id(ro_fill));
  lv_obj_update_layout(id(ro_val));
  lv_obj_align_to(id(ro_of), id(ro_val), LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -5);
  if (std::isnan(id(ro_target))) txt(id(ro_of), "/ -- gal"); else txt(id(ro_of), "/ %.1f gal", id(ro_target));
  const bool pct_ok = !std::isnan(id(ro_fill)) && !std::isnan(id(ro_target)) && id(ro_target) > 0;
  const int pct = pct_ok ? (int) roundf(id(ro_fill) / id(ro_target) * 100.0f) : 0;
  if (pct_ok) txt(id(ro_pct), "%d%% of target", pct); else txt(id(ro_pct), "");
  lv_bar_set_value(id(ro_bar), std::min(100, pct), LV_ANIM_OFF);
  txt(id(ro_reached), "Target reached: %s", id(ro_reached) ? "YES" : "NO");
  if (std::isnan(id(ro_total))) txt(id(ro_total), ""); else txt(id(ro_total), "Lifetime: %.0f gal", id(ro_total));

  if (!id(wc_online)) { txt(id(wc_batt_h), "Offline"); col(id(wc_batt_h), 0xFBBF24); }
  else if (std::isnan(id(wc_batt))) { txt(id(wc_batt_h), "Battery --"); col(id(wc_batt_h), 0x94A3B8); }
  else { txt(id(wc_batt_h), "Battery %.0f%%", id(wc_batt)); col(id(wc_batt_h), id(wc_batt_low) ? 0xFBBF24 : 0x10B981); }
  if (id(wc_last_start) == 0) txt(id(wc_last_h), "No change recorded yet");
  else {
    auto t = ESPTime::from_epoch_local(id(wc_last_start));
    const int days = tnow.is_valid() ? (int) ((tnow.timestamp - id(wc_last_start)) / 86400) : -1;
    if (days >= 0) txt(id(wc_last_h), "Last change: %s (%dd ago)", t.strftime("%b %-d").c_str(), days);
    else txt(id(wc_last_h), "Last change: %s", t.strftime("%b %-d").c_str());
  }
  txt(id(wc_mode_h), "Mode: %s  ·  %s", id(wc_draining) ? "Draining" : "Refilling",
      id(wc_flowing) ? "flowing" : "not flowing");

  if (std::isnan(id(ha_livestock_days)) || !mqtt_ok) txt(id(ha_v1), "--");
  else txt(id(ha_v1), "%.0f days", id(ha_livestock_days));
  if (!mqtt_ok) { txt(id(ha_v2), "--"); col(id(ha_v2), 0xF8FAFC); }
  else { txt(id(ha_v2), "%d", n_alerts); col(id(ha_v2), n_crit ? 0xEF4444 : (n_warn ? 0xFBBF24 : 0x10B981)); }
  auto dusk = id(sun_pa).sunset(-6.0);
  if (dusk.has_value()) txt(id(ha_v3), "%s", dusk->strftime("%-I:%M %p").c_str()); else txt(id(ha_v3), "--");
}

// ---------------------------------------------------- water change page
{
  const bool dr = id(wc_draining);
  bg(id(wc_drain), dr ? 0x261711 : 0x1E293B, dr ? 0xEA580C : 0x334155);
  bg(id(wc_fill), !dr ? 0x0C4A6E : 0x1E293B, !dr ? 0x0284C7 : 0x334155);
  col(id(wc_drain_l), dr ? 0xFB923C : 0x94A3B8);
  col(id(wc_fill_l), !dr ? 0x38BDF8 : 0x94A3B8);
  if (!id(wc_online)) txt(id(wc_state_l), "METER OFFLINE");
  else if (!id(wc_flowing)) txt(id(wc_state_l), "%s  ·  IDLE", dr ? "DRAINING" : "REFILLING");
  else if (std::isnan(id(wc_rate))) txt(id(wc_state_l), "%s", dr ? "DRAINING" : "REFILLING");
  else txt(id(wc_state_l), "%s  ·  %.1f GPM", dr ? "DRAINING" : "REFILLING", id(wc_rate));
  if (std::isnan(id(wc_batt))) txt(id(wc_batt_l), "Hose battery --");
  else txt(id(wc_batt_l), "Hose battery %.0f%%%s", id(wc_batt), id(wc_batt_low) ? " (LOW)" : "");
  col(id(wc_batt_l), id(wc_batt_low) ? 0xFBBF24 : 0x10B981);
  bg(id(wc_batt_pill), id(wc_batt_low) ? 0x291B07 : 0x0F291E, id(wc_batt_low) ? 0xD97706 : 0x059669);
  txt(id(wc_mqtt_l), mqtt_ok ? "MQTT Live" : "MQTT Down");
  const float big = dr ? id(wc_removed) : id(wc_added);
  txt(id(wc_big_cap), dr ? "WATER REMOVED THIS CHANGE" : "WATER ADDED THIS CHANGE");
  col(id(wc_big_cap), dr ? 0xFB923C : 0x38BDF8);
  if (std::isnan(big)) txt(id(wc_big), "--"); else txt(id(wc_big), "%.1f", big);
  lv_obj_update_layout(id(wc_big));
  lv_obj_align_to(id(wc_big_u), id(wc_big), LV_ALIGN_OUT_RIGHT_BOTTOM, 8, -10);
  if (std::isnan(id(wc_volume))) txt(id(wc_vol), "");
  else txt(id(wc_vol), "%.0f gal of water", id(wc_volume));
  if (std::isnan(id(wc_pct))) txt(id(wc_pct), "--"); else txt(id(wc_pct), "%.1f%%", id(wc_pct));
  lv_arc_set_value(id(wc_arc), std::isnan(id(wc_pct)) ? 0 : (int) std::min(1000.0f, id(wc_pct) * 10.0f));
  lv_obj_set_style_arc_color(id(wc_arc), lv_color_hex(dr ? 0xFB923C : 0x0284C7), LV_PART_INDICATOR);
  if (std::isnan(id(wc_rate))) txt(id(wc_rate), "--"); else txt(id(wc_rate), "%.2f gpm", id(wc_rate));
  txt(id(wc_flowing), "Flowing: %s", id(wc_flowing) ? "YES" : "NO");
  if (std::isnan(id(wc_added))) txt(id(wc_added), "--"); else txt(id(wc_added), "%.1f gal", id(wc_added));
  if (std::isnan(id(wc_removed))) txt(id(wc_removed2), "--"); else txt(id(wc_removed2), "%.1f gal", id(wc_removed));
  if (std::isnan(id(wc_net))) txt(id(wc_net), "--");
  else { txt(id(wc_net), "%+.1f gal", id(wc_net)); col(id(wc_net), id(wc_net) < -0.05f ? 0xFB923C : 0xF8FAFC); }
  if (!std::isnan(id(wc_removed)) && !std::isnan(id(wc_added)))
    txt(id(wc_other), dr ? "Added so far: %.1f gal" : "Removed this change: %.1f gal", dr ? id(wc_added) : id(wc_removed));
  else txt(id(wc_other), "");
  txt(id(ro_online_l), id(ro_online) ? "MQTT ONLINE" : "OFFLINE");
  if (std::isnan(id(ro_fill))) txt(id(ro_d_val), "--"); else txt(id(ro_d_val), "%.2f gal", id(ro_fill));
  const float tgt = std::isnan(id(ro_target_pending)) ? id(ro_target) : id(ro_target_pending);
  if (std::isnan(tgt)) { txt(id(ro_d_of), ""); txt(id(ro_d_tgt), "--"); }
  else {
    txt(id(ro_d_tgt), "%.1f gal", tgt);
    if (!std::isnan(id(ro_fill)) && tgt > 0) txt(id(ro_d_of), "of %.1f (%d%%)", tgt, (int) roundf(id(ro_fill) / tgt * 100));
    else txt(id(ro_d_of), "of %.1f", tgt);
  }
  lv_bar_set_value(id(ro_d_bar), (!std::isnan(id(ro_fill)) && !std::isnan(tgt) && tgt > 0)
                   ? std::min(100, (int) roundf(id(ro_fill) / tgt * 100)) : 0, LV_ANIM_OFF);
  if (id(ro_flowing) && !std::isnan(id(ro_rate))) txt(id(ro_d_flow), "Flowing  ·  %.2f gpm", id(ro_rate));
  else txt(id(ro_d_flow), "Not flowing");
  txt(id(ro_d_reached), id(ro_reached) ? "YES" : "NO");
  col(id(ro_d_reached), id(ro_reached) ? 0x10B981 : 0xF8FAFC);
  if (std::isnan(id(ro_total))) txt(id(ro_d_total), "--"); else txt(id(ro_d_total), "%.0f gal", id(ro_total));
  if (std::isnan(id(wc_batt))) txt(id(wc_d_batt), "--");
  else txt(id(wc_d_batt), "%.0f%%%s", id(wc_batt), id(wc_batt_low) ? "  LOW" : "");
  if (id(wc_last_start) == 0) txt(id(wc_d_last), "--");
  else txt(id(wc_d_last), "%s", ESPTime::from_epoch_local(id(wc_last_start)).strftime("%b %-d, %-I:%M %p").c_str());
  if (std::isnan(id(wc_volume))) txt(id(wc_d_vol), "--"); else txt(id(wc_d_vol), "%.1f gal", id(wc_volume));
}
"""

UPDATE_TANK = r"""
// =========================================================== tank @T@
{
  const bool live = id(@T@_stamp_ms) != 0 && now_ms - id(@T@_stamp_ms) < 45000;
  const bool ever = id(@T@_stamp_ms) != 0;
  const float temp = id(@T@_temp), sp = id(@T@_sp);
  const bool crit = live && (id(@T@_fault) ||
                    (!std::isnan(temp) && !std::isnan(sp) && fabsf(temp - sp) > 2.0f));
  // Card frame.
  if (!live) {
    lv_obj_set_style_bg_color(id(@T@_card), lv_color_hex(night ? 0x080D13 : 0x0E141B), 0);
    lv_obj_set_style_border_color(id(@T@_card), lv_color_hex(0x475569), 0);
    lv_obj_set_style_border_width(id(@T@_card), 1, 0);
  } else if (crit) {
    lv_obj_set_style_bg_color(id(@T@_card), lv_color_hex(C_CARD), 0);
    lv_obj_set_style_border_color(id(@T@_card), lv_color_hex(0xEF4444), 0);
    lv_obj_set_style_border_width(id(@T@_card), 2, 0);
  } else {
    lv_obj_set_style_bg_color(id(@T@_card), lv_color_hex(C_CARD), 0);
    lv_obj_set_style_border_color(id(@T@_card), lv_color_hex(C_BORDER), 0);
    lv_obj_set_style_border_width(id(@T@_card), 1, 0);
  }
  bg(id(@T@_hero), crit ? 0x2D0E12 : (live ? C_CARD2 : 0x0E141B), crit ? 0xDC2626 : (live ? (night ? 0x131C26 : 0x243447) : 0x475569));
  col(id(@T@_title), live ? C_TEXT : 0x94A3B8);
  show(id(@T@_tag), live);
  show(id(@T@_stale), !live);
  char a[12]; age(now_ms - id(@T@_stamp_ms), a, sizeof(a));
  if (live) {
    txt(id(@T@_link), "BLE Live  ·  %us ago", (unsigned) ((now_ms - id(@T@_stamp_ms)) / 1000));
    col(id(@T@_link), night ? 0x506173 : 0x38BDF8);
  } else if (!ever && id(@T@_stamp) == 0) {
    txt(id(@T@_link), "Waiting for Bluetooth link");
    col(id(@T@_link), 0xFBBF24);
    txt(id(@T@_stale_l), "NO DATA");
  } else {
    if (id(@T@_stamp) != 0) {
      txt(id(@T@_link), "Link lost  ·  values from %s",
          ESPTime::from_epoch_local(id(@T@_stamp)).strftime("%-I:%M:%S %p").c_str());
    } else {
      txt(id(@T@_link), "Bluetooth link lost");
    }
    col(id(@T@_link), 0xFBBF24);
    if (ever) txt(id(@T@_stale_l), "STALE %s", a); else txt(id(@T@_stale_l), "STALE");
  }

  // Hero temperature.
  if (std::isnan(temp)) txt(id(@T@_temp), "--"); else txt(id(@T@_temp), "%.1f", temp);
  col(id(@T@_temp), !live ? 0x64748B : (crit ? 0xEF4444 : C_HEAD));
  lv_obj_set_style_text_decor(id(@T@_temp), live || std::isnan(temp) ? LV_TEXT_DECOR_NONE : LV_TEXT_DECOR_STRIKETHROUGH, 0);
  col(id(@T@_unit), !live ? 0x475569 : (crit ? 0xEF4444 : C_UNIT));
  lv_obj_update_layout(id(@T@_temp));
  lv_obj_align_to(id(@T@_unit), id(@T@_temp), LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -8);
  const float swing = id(@T@_swing);
  if (std::isnan(sp)) txt(id(@T@_sp), "Setpoint --");
  else if (std::isnan(swing)) txt(id(@T@_sp), "Setpoint  %.1f °F", sp);
  else txt(id(@T@_sp), "Setpoint  %.1f °F  (±%.1f°)", sp, swing);
  col(id(@T@_sp), live ? (crit ? 0xEF4444 : (night ? 0x7D5627 : 0x38BDF8)) : 0x64748B);
  bg(id(@T@_sp_box), C_CARD, night ? 0x131C26 : 0x334155);
  if (@DUAL@) {
    const float tb = id(@T@_temp_b), g = id(@T@_grad);
    char pa[12], pb[12], pg[16];
    if (std::isnan(temp)) snprintf(pa, sizeof(pa), "--"); else snprintf(pa, sizeof(pa), "%.1f°", temp);
    if (std::isnan(tb)) snprintf(pb, sizeof(pb), "--"); else snprintf(pb, sizeof(pb), "%.1f°", tb);
    if (std::isnan(g)) snprintf(pg, sizeof(pg), "--"); else snprintf(pg, sizeof(pg), "%+.1f °F", g);
    txt(id(@T@_probes), "A  %s  ·  B  %s  ·  A-B  %s", pa, pb, pg);
  } else {
    txt(id(@T@_probes), "Single probe");
  }
  const float dr = id(@T@_drift);
  if (!live || std::isnan(dr)) { txt(id(@T@_drift), live ? "" : "Drift --"); col(id(@T@_drift), 0x64748B); }
  else {
    const bool falling = dr < -0.02f, rising = dr > 0.02f;
    txt(id(@T@_drift), "%+.2f °F/min  %s", dr, falling ? "(falling)" : (rising ? "(rising)" : "(stable)"));
    col(id(@T@_drift), crit && falling ? 0xEF4444 : (night ? 0x366B56 : 0x10B981));
  }

  // Heater / fan tiles.
  {
    const float h = id(@T@_heat), f = id(@T@_fan);
    const bool hon = id(@T@_heat_on), fon = id(@T@_fan_on);
    const bool hstall = crit && hon && h >= 99.0f && !std::isnan(dr) && dr < 0;
    if (!live) {
      txt(id(@T@_heat_val), "--  (unknown)"); txt(id(@T@_fan_val), "--  (unknown)");
      col(id(@T@_heat_val), 0xFBBF24); col(id(@T@_fan_val), 0xFBBF24);
      txt(id(@T@_heat_cap), "HEATER DUTY"); txt(id(@T@_fan_cap), "FAN DUTY");
      bg(id(@T@_heat_tile), 0x0E141B, 0x334155); bg(id(@T@_fan_tile), 0x0E141B, 0x334155);
      col(id(@T@_heat_icon), 0x475569); col(id(@T@_fan_icon), 0x475569);
    } else {
      txt(id(@T@_heat_cap), hstall ? "HEATER  NOT HEATING" : (hon ? "HEATER  ·  ON" : "HEATER  ·  IDLE"));
      txt(id(@T@_heat_val), "%.0f%% duty", std::isnan(h) ? 0.0f : h);
      col(id(@T@_heat_cap), hstall ? 0xEF4444 : (hon ? 0xFB923C : 0x94A3B8));
      col(id(@T@_heat_val), hstall ? 0xEF4444 : (hon ? (night ? 0xB47834 : 0xFB923C) : C_TEXT));
      bg(id(@T@_heat_tile), hstall ? 0x2D0E12 : (hon ? 0x261711 : (night ? 0x0A1118 : 0x16202C)),
         hstall ? 0xDC2626 : (hon ? 0xEA580C : C_BORDER));
      col(id(@T@_heat_icon), hon ? 0xFB923C : 0x64748B);
      txt(id(@T@_fan_cap), fon ? "FAN  ·  ON" : "FAN  ·  IDLE");
      txt(id(@T@_fan_val), "%.0f%% duty", std::isnan(f) ? 0.0f : f);
      col(id(@T@_fan_cap), fon ? 0x38BDF8 : 0x94A3B8);
      col(id(@T@_fan_val), C_TEXT);
      bg(id(@T@_fan_tile), fon ? 0x0C4A6E : (night ? 0x0A1118 : 0x16202C), fon ? 0x0284C7 : C_BORDER);
      col(id(@T@_fan_icon), fon ? 0x38BDF8 : 0x64748B);
    }
    lv_bar_set_value(id(@T@_heat_bar), live && !std::isnan(h) ? (int) h : 0, LV_ANIM_OFF);
    lv_bar_set_value(id(@T@_fan_bar), live && !std::isnan(f) ? (int) f : 0, LV_ANIM_OFF);
  }

  // TDS / pH tiles.
  {
    const float tds = id(@T@_tds), tm = id(@T@_tds_mean);
    const uint32_t vc = live ? C_TEXT : 0x64748B;
    if (std::isnan(tds)) txt(id(@T@_tds_val), "--"); else txt(id(@T@_tds_val), "%.0f", tds);
    col(id(@T@_tds_val), vc);
    lv_obj_update_layout(id(@T@_tds_val));
    lv_obj_align_to(id(@T@_tds_unit), id(@T@_tds_val), LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -5);
    if (std::isnan(tm)) txt(id(@T@_tds_side), ""); else txt(id(@T@_tds_side), "1 h avg %.0f", tm);
    const float lo = @TDS_LO@, hi = @TDS_HI@, al = @TDS_ALERT@;
    const float judge = std::isnan(tm) ? tds : tm;
    uint32_t tcol = 0x10B981; const char *ts = "In target";
    if (std::isnan(judge)) { tcol = 0x94A3B8; ts = ""; }
    else if (judge >= al) { tcol = 0xEF4444; ts = "Above alert"; }
    else if (!std::isnan(hi) && judge > hi) { tcol = 0xFBBF24; ts = "Above target"; }
    else if (!std::isnan(lo) && judge < lo) { tcol = 0xFBBF24; ts = "Below target"; }
    if (std::isnan(lo)) txt(id(@T@_tds_tgt), "Target < %.0f", hi);
    else txt(id(@T@_tds_tgt), "Target %.0f-%.0f", lo, hi);
    if (!live) { txt(id(@T@_tds_tgt), "CACHED"); col(id(@T@_tds_tgt), 0xFBBF24); }
    else col(id(@T@_tds_tgt), 0x94A3B8);
    range(id(@T@_tds_trk), id(@T@_tds_trk_band), id(@T@_tds_trk_mark), live ? judge : NAN,
          lo, hi, @TDS_MIN@, @TDS_MAX@, tcol);
    // Detail screen.
    if (std::isnan(tds)) txt(id(@T@_d_tds), "--"); else txt(id(@T@_d_tds), "%.0f", tds);
    col(id(@T@_d_tds), vc);
    lv_obj_update_layout(id(@T@_d_tds));
    lv_obj_align_to(id(@T@_d_tds_u), id(@T@_d_tds), LV_ALIGN_OUT_RIGHT_BOTTOM, 8, -6);
    if (std::isnan(tm)) txt(id(@T@_d_tds_m), ""); else txt(id(@T@_d_tds_m), "1 h mean %.0f", tm);
    txt(id(@T@_d_tds_st), "%s", live ? ts : "Stale");
    col(id(@T@_d_tds_st), live ? tcol : 0xFBBF24);
    if (std::isnan(lo)) txt(id(@T@_d_tds_tgt), "Target under %.0f ppm", hi);
    else txt(id(@T@_d_tds_tgt), "Target %.0f-%.0f  ·  alert %.0f ppm", lo, hi, al);
    range(id(@T@_d_tds_trk), id(@T@_d_tds_trk_band), id(@T@_d_tds_trk_mark), live ? judge : NAN,
          lo, hi, @TDS_MIN@, @TDS_MAX@, tcol);

    const float ph = id(@T@_ph);
    const bool ph_live = id(@T@_ph_ms) != 0 && now_ms - id(@T@_ph_ms) < 3600000;
    const float plo = @PH_LO@, phi = @PH_HI@;
    uint32_t pcol = 0x10B981; const char *ps = "In target";
    if (std::isnan(ph)) { pcol = 0x94A3B8; ps = ""; }
    else if (!std::isnan(plo) && ph < plo) { pcol = ph < plo - 0.2f ? 0xEF4444 : 0xFBBF24; ps = "Below target"; }
    else if (!std::isnan(phi) && ph > phi) { pcol = 0xFBBF24; ps = "Above target"; }
    if (std::isnan(ph)) txt(id(@T@_ph_val), "--"); else txt(id(@T@_ph_val), "%.2f", ph);
    col(id(@T@_ph_val), ph_live ? C_TEXT : 0x64748B);
    lv_obj_update_layout(id(@T@_ph_val));
    lv_obj_align_to(id(@T@_ph_unit), id(@T@_ph_val), LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -5);
    if (std::isnan(phi)) txt(id(@T@_ph_tgt), "Target >= %.1f", plo);
    else txt(id(@T@_ph_tgt), "Target %.1f-%.1f", plo, phi);
    if (!ph_live && !std::isnan(ph)) { txt(id(@T@_ph_tgt), "CACHED"); col(id(@T@_ph_tgt), 0xFBBF24); }
    else col(id(@T@_ph_tgt), 0x94A3B8);
    txt(id(@T@_ph_side), "%s", ph_live ? ps : "");
    col(id(@T@_ph_side), pcol);
    range(id(@T@_ph_trk), id(@T@_ph_trk_band), id(@T@_ph_trk_mark), ph_live ? ph : NAN,
          plo, phi, @PH_MIN@, @PH_MAX@, pcol);
    if (std::isnan(ph)) txt(id(@T@_d_ph), "--"); else txt(id(@T@_d_ph), "%.2f", ph);
    col(id(@T@_d_ph), ph_live ? C_TEXT : 0x64748B);
    txt(id(@T@_d_ph_st), "%s", ph_live ? ps : (std::isnan(ph) ? "No data" : "Stale"));
    col(id(@T@_d_ph_st), ph_live ? pcol : 0xFBBF24);
    if (std::isnan(phi)) txt(id(@T@_d_ph_tgt), "Target >= %.2f", plo);
    else txt(id(@T@_d_ph_tgt), "Target %.2f-%.2f", plo, phi);
    range(id(@T@_d_ph_trk), id(@T@_d_ph_trk_band), id(@T@_d_ph_trk_mark), ph_live ? ph : NAN,
          plo, phi, @PH_MIN@, @PH_MAX@, pcol);
  }

  // Footer + detail info card.
  {
    const float lux = id(@T@_lux);
    if (!live || std::isnan(lux)) txt(id(@T@_f_lux), "-- lux"); else txt(id(@T@_f_lux), "%.0f lux", lux);
    const int co2 = id(ha_co2_@T@), bub = id(ha_bubbler_@T@);
    txt(id(@T@_f_co2), "CO2 %s", co2 < 0 ? "--" : (co2 ? "On" : "Off"));
    col(id(@T@_f_co2), co2 == 1 ? (night ? 0x506173 : 0x38BDF8) : (night ? 0x506173 : 0x94A3B8));
    txt(id(@T@_f_bub), "Bubbler %s", bub < 0 ? "--" : (bub ? "On" : "Off"));
    col(id(@T@_f_bub), bub == 1 ? (night ? 0x506173 : 0x38BDF8) : (night ? 0x506173 : 0x94A3B8));
    const float conf = id(@T@_conf);
    if (!live) { txt(id(@T@_f_model), "Model --"); col(id(@T@_f_model), 0x94A3B8); }
    else if (id(@T@_fault)) { txt(id(@T@_f_model), "SAFETY TRIPPED"); col(id(@T@_f_model), 0xEF4444); }
    else if (std::isnan(conf)) txt(id(@T@_f_model), "Model --");
    else { txt(id(@T@_f_model), "Model  %.0f%%", conf); col(id(@T@_f_model), conf < 70 ? 0xFBBF24 : 0x94A3B8); }

    if (!live || std::isnan(lux)) txt(id(@T@_d_lux), "-- lux"); else txt(id(@T@_d_lux), "%.0f lux", lux);
    auto dawn = id(sun_pa).sunrise(-6.0); auto dusk = id(sun_pa).sunset(-6.0);
    if (dawn.has_value() && dusk.has_value())
      txt(id(@T@_d_sun), "Civil dawn  %s  ·  dusk  %s", dawn->strftime("%-I:%M").c_str(), dusk->strftime("%-I:%M").c_str());
    txt(id(@T@_d_co2), "CO2 %s", co2 < 0 ? "--" : (co2 ? "ON" : "OFF"));
    col(id(@T@_d_co2), co2 == 1 ? 0x38BDF8 : 0xF8FAFC);
    txt(id(@T@_d_bub), "Bubbler %s", bub < 0 ? "--" : (bub ? "on" : "off"));
    col(id(@T@_d_bub), bub == 1 ? 0x10B981 : 0x94A3B8);
    if (!live) { txt(id(@T@_d_safe2), "--"); col(id(@T@_d_safe2), 0x94A3B8); }
    else { txt(id(@T@_d_safe2), id(@T@_fault) ? "SAFETY TRIPPED" : "Safety OK"); col(id(@T@_d_safe2), id(@T@_fault) ? 0xEF4444 : 0x10B981); }
    if (std::isnan(conf)) txt(id(@T@_d_model), "Model confidence --");
    else txt(id(@T@_d_model), "Model confidence  %.0f%%", conf);
  }

  // Detail header + setpoint + actuators.
  {
    if (live) txt(id(@T@_d_link_l), "BLE Live  ·  %us ago", (unsigned) ((now_ms - id(@T@_stamp_ms)) / 1000));
    else txt(id(@T@_d_link_l), "Link lost  ·  %s", ever ? a : "no data yet");
    col(id(@T@_d_link_l), live ? 0x38BDF8 : 0xFBBF24);
    txt(id(@T@_d_safety_l), !live ? "SAFETY --" : (id(@T@_fault) ? "SAFETY TRIPPED" : "SAFETY OK"));
    col(id(@T@_d_safety_l), !live ? 0x94A3B8 : (id(@T@_fault) ? 0xEF4444 : 0x10B981));
    bg(id(@T@_d_safety), !live ? 0x131B24 : (id(@T@_fault) ? 0x2D0E12 : 0x0F291E),
       !live ? 0x334155 : (id(@T@_fault) ? 0xDC2626 : 0x059669));
    const float shown = std::isnan(id(@T@_sp_pending)) ? sp : id(@T@_sp_pending);
    if (std::isnan(shown)) txt(id(@T@_d_sp), "--"); else txt(id(@T@_d_sp), "%.1f", shown);
    col(id(@T@_d_sp), std::isnan(id(@T@_sp_pending)) ? 0xF8FAFC : 0xFBBF24);
    if (!std::isnan(id(@T@_sp_pending))) txt(id(@T@_d_band), "Sending...");
    else if (std::isnan(sp) || std::isnan(swing)) txt(id(@T@_d_band), "");
    else txt(id(@T@_d_band), "Control band  %.1f-%.1f °F", sp - swing, sp + swing);
    if (std::isnan(swing)) txt(id(@T@_d_swing), ""); else txt(id(@T@_d_swing), "SWING ±%.1f °F", swing);
    const float conf = id(@T@_conf);
    if (std::isnan(conf)) txt(id(@T@_d_conf), "Confidence --");
    else txt(id(@T@_d_conf), "Confidence  %.0f%%", conf);
    const bool ln = id(@T@_learn);
    txt(id(@T@_learn_l), ln ? "LEARNING ON" : "LEARNING OFF");
    col(id(@T@_learn_l), ln ? 0x10B981 : 0x94A3B8);
    bg(id(@T@_learn), ln ? 0x0F291E : 0x1E293B, ln ? 0x059669 : 0x334155);
    if (std::isnan(temp)) txt(id(@T@_d_pa), "--"); else txt(id(@T@_d_pa), "%.1f °F", temp);
    col(id(@T@_d_pa), live ? 0xF8FAFC : 0x64748B);
    //@DUAL{
    {
      const float tb = id(@T@_temp_b), g = id(@T@_grad);
      if (std::isnan(tb)) txt(id(@T@_d_pb), "--"); else txt(id(@T@_d_pb), "%.1f °F", tb);
      col(id(@T@_d_pb), live ? 0xF8FAFC : 0x64748B);
      if (std::isnan(g)) txt(id(@T@_d_grad), "--"); else txt(id(@T@_d_grad), "%+.2f °F", g);
    }
    //@DUAL}
    //@SINGLE{
    if (std::isnan(sp) || std::isnan(swing)) txt(id(@T@_d_grad), "--");
    else txt(id(@T@_d_grad), "%.1f-%.1f °F", sp - swing, sp + swing);
    //@SINGLE}
    if (!live || std::isnan(dr)) txt(id(@T@_d_drift), "");
    else txt(id(@T@_d_drift), "%+.2f °F/min", dr);
    const float h = id(@T@_heat), f = id(@T@_fan);
    const bool hon = id(@T@_heat_on), fon = id(@T@_fan_on);
    txt(id(@T@_d_heat_cap), hon ? "HEATER: DEMAND ON" : "HEATER: IDLE");
    col(id(@T@_d_heat_cap), hon ? 0xFB923C : 0x94A3B8);
    txt(id(@T@_d_heat_sub), "Duty cycle");
    if (!live || std::isnan(h)) txt(id(@T@_d_heat_pct), "--"); else txt(id(@T@_d_heat_pct), "%.0f%%", h);
    bg(id(@T@_d_heat), hon ? 0x261711 : 0x16202C, hon ? 0xEA580C : 0x223142);
    col(id(@T@_d_heat_icon), hon ? 0xFB923C : 0x64748B);
    lv_bar_set_value(id(@T@_d_heat_bar), live && !std::isnan(h) ? (int) h : 0, LV_ANIM_OFF);
    txt(id(@T@_d_fan_cap), fon ? "COOLING FAN: ON" : "COOLING FAN: OFF");
    col(id(@T@_d_fan_cap), fon ? 0x38BDF8 : 0x94A3B8);
    txt(id(@T@_d_fan_sub), "Duty cycle");
    if (!live || std::isnan(f)) txt(id(@T@_d_fan_pct), "--"); else txt(id(@T@_d_fan_pct), "%.0f%%", f);
    bg(id(@T@_d_fan), fon ? 0x0C4A6E : 0x16202C, fon ? 0x0284C7 : 0x223142);
    col(id(@T@_d_fan_icon), fon ? 0x38BDF8 : 0x64748B);
    lv_bar_set_value(id(@T@_d_fan_bar), live && !std::isnan(f) ? (int) f : 0, LV_ANIM_OFF);
  }
}
"""

CHART_TANK = r"""
// ------------------------------------------------- chart, tank @T@
{
  const int mode = id(@T@_chart_mode);
  for (int i = 0; i < 3; i++) {
    lv_obj_t *tb = i == 0 ? id(@T@_tab0) : (i == 1 ? id(@T@_tab1) : id(@T@_tab2));
    lv_obj_t *tl = i == 0 ? id(@T@_tab0_l) : (i == 1 ? id(@T@_tab1_l) : id(@T@_tab2_l));
    lv_obj_set_style_bg_color(tb, lv_color_hex(i == mode ? 0x0284C7 : 0x1E293B), 0);
    lv_obj_set_style_border_color(tb, lv_color_hex(i == mode ? 0x38BDF8 : 0x334155), 0);
    lv_obj_set_style_text_color(tl, lv_color_hex(i == mode ? 0xF8FAFC : 0x94A3B8), 0);
  }
  const auto &A = mode == 0 ? id(@T@_hist_temp) : (mode == 1 ? id(@T@_hist_tds) : id(@T@_hist_ph));
  const auto &B = id(@T@_hist_temp_b);
  const bool use_b = @DUAL@ && mode == 0;
  const int n = id(@T@_hist_n);
  float lo = INFINITY, hi = -INFINITY;
  for (int i = 0; i < n; i++) {
    if (!std::isnan(A[i])) { lo = std::min(lo, A[i]); hi = std::max(hi, A[i]); }
    if (use_b && !std::isnan(B[i])) { lo = std::min(lo, B[i]); hi = std::max(hi, B[i]); }
  }
  const float sp = id(@T@_sp);
  if (mode == 0 && !std::isnan(sp)) { lo = std::min(lo, sp); hi = std::max(hi, sp); }
  const bool any = lo <= hi;
  // Minimum span per series so noise does not fill the plot.
  const float min_span = mode == 0 ? 2.0f : (mode == 1 ? 40.0f : 0.4f);
  if (any && hi - lo < min_span) { const float m = (hi + lo) / 2; lo = m - min_span / 2; hi = m + min_span / 2; }
  const float pad = (hi - lo) * 0.1f; lo -= pad; hi += pad;
  const char *fmt = mode == 1 ? "%.0f" : (mode == 2 ? "%.2f" : "%.1f°");
  lv_obj_t *yl[5] = {id(@T@_yl0), id(@T@_yl1), id(@T@_yl2), id(@T@_yl3), id(@T@_yl4)};
  for (int i = 0; i < 5; i++) {
    if (!any) { txt(yl[i], ""); continue; }
    // Grid line i sits at y = 34*i + 17 of 170: value at that height.
    const float v = hi - (hi - lo) * (34.0f * i + 17.0f) / 170.0f;
    txt(yl[i], fmt, v);
  }
  txt(id(@T@_legend), "%s", mode == 0 ? (@DUAL@ ? "Probe A  ·  Probe B  ·  Setpoint" : "Water  ·  Setpoint")
                                      : (mode == 1 ? "TDS ppm" : "pH"));
  show(id(@T@_plot_empty), n < 2);
  static lv_point_precise_t pa_@T@[96], pb_@T@[96], ps_@T@[2];
  auto build = [&](const std::array<float, 96> &S, lv_point_precise_t *pts) {
    int k = 0;
    for (int i = 0; i < n; i++) {
      if (std::isnan(S[i])) continue;
      // Newest sample at the right edge, 15 min per step across 24 h.
      pts[k].x = (lv_value_precise_t) (532 - (n - 1 - i) * 532.0f / 95.0f);
      pts[k].y = (lv_value_precise_t) ((hi - S[i]) / (hi - lo) * 170.0f);
      k++;
    }
    return k;
  };
  const int ka = any ? build(A, pa_@T@) : 0;
  lv_line_set_points(id(@T@_ln_a)->obj, pa_@T@, ka);
  const int kb = (any && use_b) ? build(B, pb_@T@) : 0;
  lv_line_set_points(id(@T@_ln_b)->obj, pb_@T@, kb);
  if (any && mode == 0 && !std::isnan(sp)) {
    const float y = (hi - sp) / (hi - lo) * 170.0f;
    ps_@T@[0] = {0, (lv_value_precise_t) y}; ps_@T@[1] = {532, (lv_value_precise_t) y};
    lv_line_set_points(id(@T@_ln_sp)->obj, ps_@T@, 2);
  } else {
    lv_line_set_points(id(@T@_ln_sp)->obj, ps_@T@, 0);
  }
}
"""


def tank_code(tmpl, T):
    """Fill one tank into a C++ template. //@DUAL{ ... //@DUAL} blocks are
    kept only for the two-probe tank and //@SINGLE{ ... //@SINGLE} only for
    the one-probe tank: ESPHome resolves every id() in a lambda even inside
    a branch that can never run, so dead branches must not exist at all."""
    import re
    keep, drop = ("DUAL", "SINGLE") if T["dual"] else ("SINGLE", "DUAL")
    tmpl = re.sub(rf"[ \t]*//@{drop}{{.*?//@{drop}}}\n", "", tmpl, flags=re.S)
    tmpl = re.sub(rf"[ \t]*//@{keep}[{{}}]\n", "", tmpl)

    def num(v):
        return "NAN" if v == "NAN" else f"{float(v)}f"
    return (tmpl.replace("@T@", T["t"]).replace("@DUAL@", "true" if T["dual"] else "false")
            .replace("@TDS_LO@", num(T["tds_lo"])).replace("@TDS_HI@", num(T["tds_hi"]))
            .replace("@TDS_ALERT@", num(T["tds_alert"]))
            .replace("@TDS_MIN@", num(T["tds_min"])).replace("@TDS_MAX@", num(T["tds_max"]))
            .replace("@PH_LO@", num(T["ph_lo"])).replace("@PH_HI@", num(T["ph_hi"]))
            .replace("@PH_MIN@", num(T["ph_min"])).replace("@PH_MAX@", num(T["ph_max"])))

# ------------------------------------------------------------------- fonts

TEXT_EXTRA = "°±·–—"
FONTS = [
    # id, size, weight, glyphs (None = Latin + extras)
    ("f58", 58, 800, "0123456789.-°F "),
    ("f42", 42, 800, "0123456789.-°F "),
    ("f32", 32, 800, None),
    ("f26", 26, 800, None),
    ("f18", 18, 800, None),
    ("f15", 15, 800, None),
    ("f13", 13, 700, None),
    ("f12", 12, 600, None),
    ("f11", 11, 700, None),
]
ICON_SIZES = (18, 24)


def fonts_yaml():
    out = []
    for fid, size, weight, glyphs in FONTS:
        d = {"file": {"type": "gfonts", "family": "Plus Jakarta Sans", "weight": weight},
             "id": fid, "size": size, "bpp": 4}
        if glyphs:
            d["glyphs"] = glyphs
        else:
            d["glyphsets"] = ["GF_Latin_Kernel"]
            d["glyphs"] = TEXT_EXTRA
        out.append(d)
    for s in ICON_SIZES:
        out.append({"file": {"type": "web", "url":
                             "https://cdn.jsdelivr.net/npm/@mdi/font@7.4.47/fonts/materialdesignicons-webfont.ttf"},
                    "id": f"icon{s}", "size": s, "bpp": 4, "glyphs": sorted(set(ICON.values()))})
    return out

# -------------------------------------------------------------------- main


def rename_widget_ids(text, names):
    """Widgets that would share an id with a data global get a _w suffix.

    The globals (panel_p4_tank.yaml / panel_p4_feeds.yaml) keep the plain
    name. In this file a plain `id: X` is always the widget's definition, and
    in the C++ a widget is only ever the object argument of an LVGL call or
    of the txt/col/bg/show helpers, so those are the only places renamed.
    """
    import re
    for n in names:
        text = re.sub(rf"(\bid: ){n}\b", rf"\g<1>{n}_w", text)
        text = re.sub(rf"(\b(?:txt|col|bg|show|lv_[a-z_]+)\()id\({n}\)", rf"\g<1>id({n}_w)", text)
        text = re.sub(rf"(lv_obj_align_to\(id\([a-z0-9_]+\), )id\({n}\)", rf"\g<1>id({n}_w)", text)
    return text



HEADER = """\
# GENERATED by tools/gen_panel_p4_ui.py -- do not edit by hand; edit the
# generator and rerun it. The 10.1" P4 wall panel's LVGL UI.
#
# Design: design/p4-panel/ (DESIGN.md, REVISION-1.md).
# Data:   packages/panel_p4_tank.yaml (t75, t16) and panel_p4_feeds.yaml.
"""


def build():
    """The generated YAML as text."""
    home = {"id": "page_home", "bg_color": COL["canvas"], "scrollable": False,
            "widgets": top_bar()[:-1] + [tank_card(T) for T in TANKS] + strip() + [top_bar()[-1]]}
    pages = [home] + [detail_page(T) for T in TANKS] + [wc_page()]

    doc = {
        "globals": [
            {"id": "night_on", "type": "bool", "restore_value": False, "initial_value": "false"},
            {"id": "alert_target", "type": "int", "restore_value": False, "initial_value": "0"},
            {"id": "redraw_charts", "type": "bool", "restore_value": False, "initial_value": "true"},
            {"id": "ro_target_pending", "type": "float", "restore_value": False, "initial_value": "NAN"},
        ] + [{"id": f"{T['t']}_chart_mode", "type": "int", "restore_value": False,
              "initial_value": "0"} for T in TANKS],
        "font": fonts_yaml(),
        "lvgl": {
            "displays": ["main_display"],
            "touchscreens": ["main_touch"],
            "color_depth": 16,
            "buffer_size": "25%",
            "bg_color": COL["canvas"],
            "page_wrap": False,
            "theme": {
                "label": {"text_font": "f13", "text_color": COL["text"]},
                "obj": {"pad_all": 0, "border_width": 0},
            },
            "top_layer": {"widgets": [
                # Eats the first touch while the screen is dimmed for the
                # night, so waking it can never also press a button.
                {"obj": {"id": "night_shield", "x": 0, "y": 0, "width": 1024, "height": 600,
                         "bg_opa": "TRANSP", "border_width": 0, "hidden": True,
                         "on_click": [{"lambda": "lv_obj_add_flag(id(night_shield), LV_OBJ_FLAG_HIDDEN);"}]}},
            ]},
            "pages": pages,
        },
        "script": [
            {"id": "ro_send_target", "mode": "restart", "then": [
                {"delay": "1500ms"},
                {"if": {"condition": {"lambda": "return !std::isnan(id(ro_target_pending));"},
                        "then": [publish("water-flow-ro/number/fill_target/command", "@ROPAYLOAD@"),
                            {"delay": "6s"},
                            {"lambda": "id(ro_target_pending) = NAN;"}]}}]},
        ],
        "interval": [
            {"interval": "1s", "then": [{"lambda": "@UPDATE@"}]},
            # Charts: once a minute, or at once after a tab tap.
            {"interval": "1s", "then": [{"lambda": "@CHART@"}]},
            # Night: the room is dark when the sun is below civil twilight
            # AND the 75's tank light reads off. Dims after 60 s untouched;
            # any touch wakes it (LVGL's own inactivity clock).
            {"interval": "2s", "then": [{"lambda": "@NIGHT@"}]},
        ],
    }

    text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=1000)
    update = UPDATE_COMMON + "".join(tank_code(UPDATE_TANK, T) for T in TANKS)
    chart = ("static uint32_t last = 0;\n"
             "if (!id(redraw_charts) && millis() - last < 60000) return;\n"
             "id(redraw_charts) = false; last = millis();\n"
             "auto txt = [](lv_obj_t *o, const char *fmt, ...) {\n"
             "  char b[64]; va_list ap; va_start(ap, fmt); vsnprintf(b, sizeof(b), fmt, ap); va_end(ap);\n"
             "  lv_label_set_text(o, b);\n};\n"
             "auto show = [](lv_obj_t *o, bool on) {\n"
             "  if (on) lv_obj_remove_flag(o, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);\n};\n"
             + "".join(tank_code(CHART_TANK, T) for T in TANKS))
    night = "return;  // preview: the scenario sets night_on\n" if PREVIEW else (
        "const double el = id(sun_pa).elevation();\n"
        "const float lux = id(t75_lux);\n"
        "const bool dark = el < -6.0 && (std::isnan(lux) || lux < 18.0f);\n"
        "const bool idle = lv_display_get_inactive_time(NULL) > 60000;\n"
        "const bool want = dark && idle;\n"
        "if (want == id(night_on)) return;\n"
        "id(night_on) = want;\n"
        "auto call = id(backlight).turn_on();\n"
        "call.set_brightness(want ? 0.10f : 1.0f);\n"
        "call.perform();\n"
        "if (want) lv_obj_remove_flag(id(night_shield), LV_OBJ_FLAG_HIDDEN);\n"
        "else lv_obj_add_flag(id(night_shield), LV_OBJ_FLAG_HIDDEN);\n"
        "ESP_LOGI(\"panel\", \"night mode %s\", want ? \"on\" : \"off\");\n")

    def block(code):
        return "|-\n" + "\n".join("          " + ln if ln else "" for ln in code.strip("\n").split("\n"))
    text = (text.replace("'@UPDATE@'", block(update))
                .replace("'@CHART@'", block(chart))
                .replace("'@NIGHT@'", block(night)))
    text = text.replace(
        "payload: '@ROPAYLOAD@'",
        "payload: !lambda |-\n"
        "            char b[12]; snprintf(b, sizeof(b), \"%.1f\", id(ro_target_pending));\n"
        "            return std::string(b);")
    text = rename_widget_ids(text, [f"{T['t']}_{k}" for T in TANKS
                                    for k in ("link", "temp", "sp", "drift", "learn")]
                             + ["ro_reached", "ro_total", "wc_added", "wc_flowing",
                                "wc_net", "wc_pct", "wc_rate"])
    if PREVIEW:
        text = text.replace("payload: '@ROPAYLOAD@'", "payload: ''")
        text = text.replace("- logger.log: 'preview: would publish @ROPAYLOAD@ to",
                            "- logger.log: 'preview: would publish target to")
    return HEADER + text


def main():
    text = build()
    OUT.write_text(text)
    print(f"wrote {OUT} ({len(text.splitlines())} lines)")


if __name__ == "__main__":
    main()
