#!/usr/bin/env python3
"""Generates packages/panel_p4_ui.yaml, the LVGL UI of the 10.1" P4 wall panel.

    python3 tools/gen_panel_p4_ui.py      (needs PyYAML)

Edit THIS file, never the generated YAML. The two tanks share one card
layout and one detail-screen layout; writing those twice by hand is how one
tank ends up with a fix the other never got.

The design is design/p4-panel/ (Gemini 3.8, approved 2026-10-29, revised by
REVISION-1.md). Positions below are measured off the mockup screenshots in
design/p4-panel/shots/; DESIGN.md has the colours, sizes and radii.
tools/p4_preview.py renders this UI on the desktop for comparison.

How the UI works
  - Widgets are built once, here, with neutral styles. Every widget id
    starts with w_ so it can never collide with a data global.
  - ONE interval lambda (every second) writes every label, bar, colour,
    position and flag from the globals in panel_p4_tank.yaml and
    panel_p4_feeds.yaml. State styling (stale, critical, night, the
    compact layout under the alert banner) is decided there, from data,
    every tick, so no widget can be left in a stale style by a missed event.
  - Values that are not known render as "--", never as a plausible number.
    Copy the mockups invented (light %, "CO2 off (Nov)") is left out: the
    panel only says what it has data for.
"""

import re
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
    "track": 0x0F172A, "violet": 0x818CF8,
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
    "minus": "\U000F0374", "plus": "\U000F0415", "brain": "\U000F09D1",
    "sun": "\U000F0599", "night": "\U000F0594", "co2": "\U000F07E4",
    "bubbles": "\U000F05E3", "swap": "\U000F04E1", "battery": "\U000F12A3",
    "filter": "\U000F0232", "water": "\U000F058C", "ha": "\U000F07D0",
    "shield": "\U000F0565", "check": "\U000F05E1", "minus_circle": "\U000F0377",
    "refresh": "\U000F0450", "play": "\U000F040D", "plus_circle": "\U000F0419",
    "radio": "\U000F043E",
}

TANKS = [
    # t: id prefix from the wrapper's vars; dual: second probe + gradient.
    # 75 gal targets are the owner's (memory, 2026-09/10): TDS 200-225,
    # alert 260, never >300; pH 7.0-7.5.
    # Nano targets come from its own history (HA statistics, 2026-09-05 to
    # 2026-10-29, daily 1 h TDS means): after the cycle it has lived at
    # 336-391 ppm, ~336-378 just after a water change, drifting up 1-2 ppm a
    # day to ~380-390 before the next one; nothing since the cycle has
    # reached 400 (the early-September cycle peaked at 431). So: target
    # 330-390, above 390 = a change is due, alert at 410. pH from the
    # calibrated probe (2026-10-24..29): 6.97-7.32; 7.0 is the emerald dwarf
    # danios' floor, 7.4 sits just above anything the probe has seen.
    dict(t="t75", name="75 GALLON", tag="COMMUNITY", dual=True,
         water="~62 GAL", ph_title="WATER PH LEVEL", ph_tile="WATER PH",
         tds_lo=200, tds_hi=225, tds_alert=260, tds_max=300, tds_scale=(150, 320),
         ph_lo=7.0, ph_hi=7.5, ph_scale=(6.8, 7.8), card_x=14),
    dict(t="t16", name="FLUVAL SPEC 16", tag="16 GAL • ~14 GAL WATER", dual=False,
         water="~14 GAL (16 GAL TANK)", ph_title="WATER PH (WI-FI)", ph_tile="PH (WI-FI)",
         tds_lo=330, tds_hi=390, tds_alert=410, tds_max="NAN", tds_scale=(280, 450),
         ph_lo=7.0, ph_hi=7.4, ph_scale=(6.8, 7.8), card_x=518),
]

# Home-card layouts: block positions relative to the card. NORMAL is the
# mockup's home screen; COMPACT is screen 5, where the alert banner pushes
# the cards down.
LAYOUT = {
    "normal": dict(card=(66, 406), head=12, lost=10, hero=(64, 92), act=(178, 52),
                   met=(248, 84), sep=350, foot=358, details=355, reconn=370),
    "compact": dict(card=(122, 356), head=8, lost=8, hero=(48, 80), act=(138, 52),
                    met=(200, 80), sep=292, foot=300, details=304, reconn=314),
}

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
    st.setdefault("bg_opa", "COVER")
    d = _base(i, x, y, w, h, align, bg_color=COL[bg],
              border_color=COL[border], border_width=bw, radius=radius,
              pad_all=0, scrollable=False, scrollbar_mode="OFF", **st)
    if kids:
        d["widgets"] = list(kids)
    return {"obj": d}


def label(i, text, font, color="text", x=None, y=None, w=None, align=None, **st):
    d = _base(i, x, y, w, None, align, text=text, text_font=font, text_color=COL[color], **st)
    return {"label": d}


def icon(i, name, size=18, color="cyan", x=None, y=None, align=None, **st):
    return label(i, ICON[name], f"icon{size}", color, x, y, align=align, **st)


def row(i, x, y, kids, gap=8, align=None, h=28, w="SIZE_CONTENT", **st):
    d = _base(i, x, y, w, h, align, bg_opa="TRANSP", border_width=0, pad_all=0,
              scrollable=False, scrollbar_mode="OFF",
              layout={"type": "FLEX", "flex_flow": "ROW", "pad_column": gap,
                      "flex_align_main": "START", "flex_align_cross": "CENTER",
                      "flex_align_track": "CENTER"},
              widgets=list(kids), **st)
    return {"obj": d}


def pill(i, kids, bg="card2", border="border_act", h=24, x=None, y=None, align=None,
         gap=6, pad=10, radius=20, **st):
    """A rounded box that sizes itself around a row of children."""
    d = _base(i, x, y, "SIZE_CONTENT", h, align, bg_color=COL[bg], bg_opa="COVER",
              border_color=COL[border], border_width=1, radius=radius,
              pad_left=pad, pad_right=pad, pad_top=0, pad_bottom=0,
              scrollable=False, scrollbar_mode="OFF",
              layout={"type": "FLEX", "flex_flow": "ROW", "pad_column": gap,
                      "flex_align_main": "CENTER", "flex_align_cross": "CENTER",
                      "flex_align_track": "CENTER"},
              widgets=list(kids), **st)
    return {"obj": d}


def dot(i, color="cyan", size=8):
    return box(i, None, None, size, size, bg=color, border=color, radius=size, bw=0)


def button(i, x, y, w, h, kids, bg="btn", border="border_act", radius=8, align=None, **actions):
    d = _base(i, x, y, w, h, align, bg_color=COL[bg], bg_opa="COVER",
              border_color=COL[border], border_width=1, radius=radius,
              shadow_width=0, pad_all=0, widgets=list(kids))
    d["pressed"] = {"bg_color": COL["btn_act"]}
    d.update(actions)
    return {"button": d}


def track(i, x, y, w):
    """Target-range bar: track, the target band, and a value marker."""
    return box(i, x, y, w, 6, bg="track", border="track", radius=3, bw=0, kids=[
        box(f"{i}_band", 0, 0, 10, 6, bg="band", border="green_border", radius=3),
        box(f"{i}_mark", 0, -2, 6, 10, bg="green", border="green", radius=3, bw=0),
    ])


def bar(i, x, y, w, color, align=None, h=8):
    d = _base(i, x, y, w, h, align, min_value=0, max_value=100, value=0,
              bg_color=COL["track"], radius=4, border_width=1, border_color=COL["border2"],
              indicator={"bg_color": COL[color], "radius": 4})
    return {"bar": d}


def show_page(page):
    return [{"lvgl.page.show": {"id": page, "animation": "NONE"}}]


def back_button():
    return button(None, 16, 10, 92, 44, on_click=show_page("w_page_home"), kids=[
        row(None, 0, 0, align="CENTER", gap=8, h=24, kids=[
            label(None, "←", "f15", "text2"), label(None, "Home", "f13")])])

# ----------------------------------------------------------------- top bar


def top_bar():
    return [
        box("w_logo", 18, 16, 32, 32, bg="cyan_bg", border="cyan_deep", radius=8,
            kids=[icon(None, "fish", 18, "cyan", align="CENTER")]),
        label("w_brand", "TANK MONITOR", "f15", x=60, y=23),
        pill("w_status", [dot("w_status_dot", "green"), label("w_status_l", "", "f13", "green")],
             bg="green_bg", border="green_border", h=30, x=262, y=17, pad=14),
        row("w_top_right", -16, 16, align="TOP_RIGHT", h=32, gap=12, kids=[
            pill("w_mqtt_pill", [icon("w_mqtt_i", "wifi", 18, "label"),
                                 label("w_mqtt_l", "MQTT", "f12", "text2")],
                 bg="card1", border="border_act", h=26, radius=6, pad=8),
            pill("w_ble_pill", [icon("w_ble_i", "bt", 18, "label"),
                                label("w_ble_l", "BLE", "f12", "text2")],
                 bg="card1", border="border_act", h=26, radius=6, pad=8),
            pill("w_wake", [icon(None, "sun", 18, "amber"),
                            label(None, "WAKE SCREEN", "f13", "amber", text_decor="UNDERLINE")],
                 bg="card1", border="border_act", h=34, radius=8, pad=14, hidden=True),
            label("w_clock", "--:--", "f18"),
            label("w_date", "", "f12", "label"),
        ]),
    ]


def alert_banner():
    # Screen 5: a full-width bar under the top bar; the cards move down
    # (LAYOUT["compact"]) while it shows.
    return box("w_alert", 14, 58, 996, 56, bg="red_bg", border="red_border", radius=10,
               hidden=True, kids=[
                   box("w_alert_disc", 16, 0, 32, 32, bg="red", border="red", radius=16,
                       bw=0, align="LEFT_MID",
                       kids=[label(None, "!", "f18", "text", align="CENTER")]),
                   label("w_alert_title", "", "f15", x=62, y=9, w=740, long_mode="DOT"),
                   label("w_alert_msg", "", "f12", "text2", x=62, y=31, w=740, long_mode="DOT"),
                   button("w_alert_btn", -8, 0, 162, 42, align="RIGHT_MID", bg="red",
                          border="red", kids=[row(None, 0, 0, align="CENTER", gap=8, h=24, kids=[
                              label(None, "→", "f15"),
                              label("w_alert_btn_l", "OPEN", "f13")])],
                          on_click=[{"if": {
                              "condition": {"lambda": "return id(alert_target) == 1;"},
                              "then": show_page("w_page_t75"),
                              "else": [{"if": {
                                  "condition": {"lambda": "return id(alert_target) == 2;"},
                                  "then": show_page("w_page_t16")}}]}}]),
               ])

# --------------------------------------------------------------- home cards


def tank_card(T):
    t, X, L = T["t"], T["card_x"], LAYOUT["normal"]
    w = f"w_{t}"
    hero = box(f"{w}_hero", 16, L["hero"][0], 460, L["hero"][1], bg="card2", border="border2",
               radius=10, kids=[
                   label(f"{w}_temp", "--", "f58", x=16, align="LEFT_MID", y=2),
                   label(f"{w}_unit", "°F", "f26", "cyan", x=150, y=40),
                   pill(f"{w}_sp", [label(f"{w}_sp_k", "Setpoint:", "f13", "text"),
                                    label(f"{w}_sp_v", "--", "f13", "cyan"),
                                    label(f"{w}_sp_s", "", "f12", "label")],
                        bg="card1", border="border_act", h=26, radius=6, pad=10, gap=6,
                        align="TOP_RIGHT", x=-14, y=10),
                   row(f"{w}_probe_row", -14, 40, align="TOP_RIGHT", h=22, gap=8, kids=[
                       label(f"{w}_probes", "", "f12", "label"),
                       pill(f"{w}_grad", [label(f"{w}_grad_l", "", "f12", "cyan")],
                            bg="card1", border="cyan_deep", h=20, radius=4, pad=6,
                            hidden=not T["dual"]),
                   ]),
                   label(f"{w}_drift", "", "f12", "green", align="TOP_RIGHT", x=-14, y=64),
               ])
    act = lambda k, x, wd, ic, color: box(  # noqa: E731
        f"{w}_{k}", x, L["act"][0], wd, L["act"][1], bg="card3", border="border", radius=8,
        kids=[
            icon(f"{w}_{k}_i", ic, 18, "muted", x=12, align="LEFT_MID"),
            label(f"{w}_{k}_cap", "", "f11", "label", x=38, y=8),
            label(f"{w}_{k}_val", "--", "f15", x=38, y=25),
            bar(f"{w}_{k}_bar", -12, 13, 36, color, align="TOP_RIGHT"),
        ])
    metric = lambda k, x, wd, cap, unit: box(  # noqa: E731
        f"{w}_{k}", x, L["met"][0], wd, L["met"][1], bg="card3", border="border", radius=8,
        kids=[
            label(f"{w}_{k}_cap", cap, "f11", "label", x=12, y=10),
            label(f"{w}_{k}_tgt", "", "f11", "label", align="TOP_RIGHT", x=-12, y=10),
            label(f"{w}_{k}_val", "--", "f26", x=12, y=27),
            label(f"{w}_{k}_unit", unit, "f13", "label", x=80, y=40),
            label(f"{w}_{k}_side", "", "f12", "cyan", align="TOP_RIGHT", x=-12, y=38),
            track(f"{w}_{k}_trk", 12, 66, wd - 24),
        ])
    foot_item = lambda k, ic, color: row(None, None, None, h=24, gap=4, kids=[  # noqa: E731
        icon(f"{w}_fi_{k}", ic, 18, color), label(f"{w}_f_{k}", "--", "f12", "label")])
    return box(f"{w}_card", X, L["card"][0], 492, L["card"][1], bg="card1", border="border",
               radius=14, kids=[
                   row(f"{w}_head", 16, L["head"], h=36, gap=10, kids=[
                       label(f"{w}_title", T["name"], "f18"),
                       pill(f"{w}_tag", [label(None, T["tag"], "f11", "label")],
                            bg="card2", border="border_act", h=20, radius=4, pad=8),
                   ]),
                   row(f"{w}_link", -16, L["head"] + 4, align="TOP_RIGHT", h=28, gap=6, kids=[
                       dot(f"{w}_link_dot", "cyan"),
                       label(f"{w}_link_l", "BLE --", "f12", "cyan"),
                   ]),
                   # Screen 6: the link-lost banner replaces the header row.
                   box(f"{w}_lost", 16, L["lost"], 460, 44, bg="amber_bg", border="amber_border",
                       radius=8, hidden=True, kids=[
                           icon(None, "bt_off", 18, "amber", x=12, align="LEFT_MID"),
                           label(f"{w}_lost_t", "BLUETOOTH LINK LOST", "f12", "amber", x=40, y=6),
                           label(f"{w}_lost_s", "", "f11", "text2", x=40, y=24),
                           pill(f"{w}_lost_p", [label(f"{w}_lost_pl", "STALE", "f12", "amber")],
                                bg="amber_bg", border="amber", h=24, align="RIGHT_MID", x=-10),
                       ]),
                   hero,
                   pill(f"{w}_frozen", [label(None, "STALE FROZEN DATA", "f11", "text2")],
                        bg="border_act", border="border_act", h=18, radius=4, pad=8,
                        x=30, y=L["hero"][0] - 9, hidden=True),
                   act("heat", 16, 225, "fire", "heat"),
                   act("fan", 250, 226, "fan", "cyan"),
                   metric("tds", 16, 225, "TDS (PURITY)", "ppm"),
                   metric("ph", 250, 226, T["ph_tile"], "pH"),
                   box(f"{w}_sep", 16, L["sep"], 460, 1, bg="border", border="border", radius=0, bw=0),
                   row(f"{w}_foot", 16, L["foot"], h=40, gap=14, kids=[
                       foot_item("lux", "sun", "amber"), foot_item("co2", "co2", "muted"),
                       foot_item("bub", "bubbles", "muted"), foot_item("model", "brain", "muted"),
                   ]),
                   button(f"{w}_details", 388, L["details"], 88, 38,
                          on_click=show_page(f"w_page_{t}"), kids=[
                              row(None, 0, 0, align="CENTER", gap=6, h=24, kids=[
                                  label(None, "Details", "f13"), label(None, "›", "f15", "text2")])]),
                   label(f"{w}_reconn", "Auto-reconnecting…", "f12", "muted", x=-16,
                         align="TOP_RIGHT", y=L["reconn"], hidden=True),
               ])


def strip():
    return [
        box("w_ro_card", 14, 484, 346, 104, bg="card1", border="border", radius=12, kids=[
            icon(None, "filter", 18, "cyan", x=14, y=12),
            label(None, "RO FILTER OUTPUT", "f13", x=40, y=14),
            pill("w_ro_pill", [label("w_ro_pill_l", "--", "f11", "cyan")], bg="cyan_bg",
                 border="cyan_deep", h=20, radius=4, pad=8, align="TOP_RIGHT", x=-14, y=12),
            label("w_ro_val", "--", "f26", x=14, y=38),
            label("w_ro_of", "/ -- gal", "f13", "label", x=70, y=48),
            label("w_ro_pct", "", "f12", "label", align="TOP_RIGHT", x=-14, y=48),
            bar("w_ro_bar", 14, 72, 318, "cyan_deep", h=6),
            label("w_ro_reached", "", "f11", "muted", x=14, y=84),
            label("w_ro_total", "", "f11", "muted", align="TOP_RIGHT", x=-14, y=84),
        ]),
        box("w_wc_card", 370, 484, 388, 104, bg="card1", border="cyan_deep", radius=12, kids=[
            icon(None, "swap", 18, "cyan", x=14, y=12),
            label(None, "WATER CHANGE METER", "f13", x=40, y=14),
            row(None, -14, 10, align="TOP_RIGHT", h=24, gap=6, kids=[
                icon("w_wc_batt_i", "battery", 18, "green"),
                label("w_wc_batt", "--", "f12", "green"),
                pill("w_wc_ready", [label("w_wc_ready_l", "--", "f11", "text2")],
                     bg="card2", border="border_act", h=20, radius=4, pad=8),
            ]),
            label("w_wc_last", "", "f12", "text2", x=14, y=44),
            label("w_wc_vol_h", "", "f11", "muted", x=14, y=62),
            label("w_wc_mode_h", "", "f11", "muted", x=14, y=80),
            button("w_wc_open", -14, 6, 152, 40, align="RIGHT_MID", bg="cyan_deep",
                   border="cyan", on_click=show_page("w_page_wc"),
                   kids=[row(None, 0, 0, align="CENTER", gap=8, h=24, kids=[
                       icon(None, "play", 18, "text"), label(None, "START CHANGE", "f13")])]),
            label("w_wc_flow_h", "", "f11", "muted", align="TOP_RIGHT", x=-14, y=80),
        ]),
        box("w_ha_card", 770, 484, 240, 104, bg="card1", border="border", radius=12, kids=[
            icon("w_ha_i", "ha", 18, "cyan", x=14, y=12),
            label(None, "HOME ASSISTANT", "f12", x=38, y=15),
            pill("w_ha_pill", [label("w_ha_pill_l", "--", "f11", "green")], bg="green_bg",
                 border="green_border", h=20, radius=4, pad=6, align="TOP_RIGHT", x=-10, y=12),
            label("w_ha_k1", "Livestock Loss:", "f12", "label", x=14, y=44),
            label("w_ha_v1", "--", "f12", "green", align="TOP_RIGHT", x=-14, y=44),
            label("w_ha_k2", "Civil Dusk:", "f12", "label", x=14, y=63),
            label("w_ha_v2", "--", "f12", "text", align="TOP_RIGHT", x=-14, y=63),
            label("w_ha_k3", "Active Alerts:", "f12", "label", x=14, y=82),
            label("w_ha_v3", "--", "f12", "cyan", align="TOP_RIGHT", x=-14, y=82),
            label("w_ha_alert", "", "f12", "red", x=14, y=50, w=212, long_mode="DOT", hidden=True),
        ]),
    ]

# ------------------------------------------------------------- detail page

PLOT_W, PLOT_H = 512, 148


def detail_page(T):
    t, dual = T["t"], T["dual"]
    w = f"w_{t}"

    def sp_step(delta):
        return [{"lambda": (
            f"float base = std::isnan(id({t}_sp_pending)) ? id({t}_sp) : id({t}_sp_pending);\n"
            f"if (std::isnan(base)) return;\n"
            f"base = roundf((base + ({delta})) * 10.0f) / 10.0f;\n"
            f"id({t}_sp_pending) = std::min(80.0f, std::max(70.0f, base));\n")},
            {"script.execute": f"{t}_send_sp"}]

    if dual:
        probes = [
            box(None, 16, 46, 166, 70, bg="card2", border="border2", radius=8, kids=[
                label(None, "PROBE A", "f11", "label", x=12, y=10),
                label(f"{w}_d_pa", "--", "f26", x=12, y=30),
                label(f"{w}_d_pa_u", "°F", "f15", "cyan", x=80, y=38)]),
            box(None, 194, 46, 166, 70, bg="card2", border="border2", radius=8, kids=[
                label(None, "PROBE B", "f11", "label", x=12, y=10),
                label(f"{w}_d_pb", "--", "f26", x=12, y=30),
                label(f"{w}_d_pb_u", "°F", "f15", "cyan", x=80, y=38)]),
            box(None, 16, 126, 344, 52, bg="card3", border="border", radius=8, kids=[
                label(None, "Thermal Gradient (A − B)", "f12", "text2", x=14, y=8),
                label(f"{w}_d_grad", "--", "f15", "cyan", x=14, y=26),
                label(f"{w}_d_drift", "", "f12", "green", align="RIGHT_MID", x=-14)]),
        ]
    else:
        probes = [
            box(None, 16, 46, 344, 116, bg="card2", border="border2", radius=8, kids=[
                label(None, "PRIMARY TEMPERATURE PROBE", "f11", "label", x=14, y=14),
                label(f"{w}_d_pa", "--", "f32", x=14, y=36),
                label(f"{w}_d_pa_u", "°F", "f18", "cyan", x=100, y=48),
                label(None, "Single probe", "f11", "muted", x=14, y=84),
                pill(f"{w}_d_drift_box", [label(f"{w}_d_drift", "", "f12", "text2")],
                     bg="card1", border="border_act", h=30, radius=6, pad=10,
                     align="TOP_RIGHT", x=-14, y=36),
                label(f"{w}_d_aligned", "", "f11", "green", align="TOP_RIGHT", x=-14, y=84),
            ]),
        ]

    act_row = lambda k, y, ic, color: box(  # noqa: E731
        f"{w}_d_{k}", 16, y, 344, 50, bg="card3", border="border", radius=8, kids=[
            icon(f"{w}_d_{k}_i", ic, 18, "muted", x=14, align="LEFT_MID"),
            label(f"{w}_d_{k}_cap", "", "f12", "label", x=44, y=8),
            label(f"{w}_d_{k}_sub", "", "f11", "muted", x=44, y=27),
            label(f"{w}_d_{k}_pct", "--", "f15", align="RIGHT_MID", x=-96),
            bar(f"{w}_d_{k}_bar", -14, 0, 76, color, align="RIGHT_MID"),
        ])

    tab = lambda i, mode, x, wd, text: button(  # noqa: E731
        f"{w}_tab{i}", x, 12, wd, 30, radius=6,
        on_click=[{"lambda": f"id({t}_chart_mode) = {mode}; id(redraw_charts) = true;"}],
        kids=[label(f"{w}_tab{i}_l", text, "f12", align="CENTER")])

    legend_item = lambda k, color: row(f"{w}_lg_{k}", None, None, h=20, gap=6, kids=[  # noqa: E731
        box(None, None, None, 14, 3, bg=color, border=color, radius=2, bw=0),
        label(f"{w}_lg_{k}_l", "", "f11", "label")])

    plot = box(f"{w}_plot", 16, 52, 576, 178, bg="canvas", border="border", radius=8, kids=[
        *[label(f"{w}_yl{i}", "", "f11", "muted", x=10, y=10 + 37 * i - 7) for i in range(5)],
        box(f"{w}_area", 52, 10, PLOT_W, PLOT_H, bg="canvas", border="canvas", radius=0, bw=0,
            bg_opa="TRANSP", kids=[
                *[box(None, 0, 37 * i, PLOT_W, 1, bg="border", border="border", radius=0, bw=0)
                  for i in range(5)],
                {"line": {"id": f"{w}_ln_sp", "points": ["0,0", "1,0"], "line_width": 2,
                          "line_color": COL["green"], "line_opa": "70%"}},
                {"line": {"id": f"{w}_ln_b", "points": ["0,0", "1,0"], "line_width": 2,
                          "line_color": COL["violet"], "line_rounded": True}},
                {"line": {"id": f"{w}_ln_a", "points": ["0,0", "1,0"], "line_width": 3,
                          "line_color": COL["cyan"], "line_rounded": True}},
                label(f"{w}_plot_empty", "Collecting history (one point every 15 min)",
                      "f12", "muted", align="CENTER"),
            ]),
    ])

    widgets = [
        back_button(),
        row(None, 122, 10, h=44, gap=14, kids=[
            label(None, f"{T['name']} DETAIL", "f18"),
            pill(f"{w}_d_link", [dot(f"{w}_d_link_dot", "cyan"),
                                 label(f"{w}_d_link_l", "BLE --", "f12", "cyan")],
                 bg="card1", border="border_act", h=26, radius=6, pad=10),
        ]),
        row(None, -16, 10, align="TOP_RIGHT", h=44, gap=10, kids=[
            pill(f"{w}_d_safety", [icon(f"{w}_d_safety_i", "shield", 18, "green"),
                                   label(f"{w}_d_safety_l", "SAFETY --", "f12", "green")],
                 bg="green_bg", border="green_border", h=28, radius=6, pad=10),
            pill(None, [label(None, f"NET VOLUME: {T['water']}", "f12", "text2")],
                 bg="card1", border="border_act", h=28, radius=6, pad=10),
        ]),
        # ---- setpoint card
        box(None, 14, 66, 376, 200, bg="card1", border="border", radius=14, kids=[
            label(None, "TEMPERATURE SETPOINT CONTROL", "f12", "text2", x=16, y=16),
            pill(f"{w}_d_swing", [label(f"{w}_d_swing_l", "", "f11", "cyan")], bg="card1",
                 border="cyan_deep", h=22, radius=4, pad=6, align="TOP_RIGHT", x=-16, y=14),
            box(None, 16, 42, 344, 80, bg="card2", border="border2", radius=10, kids=[
                button(f"{w}_minus", 12, 0, 56, 56, align="LEFT_MID",
                       on_click=sp_step(-0.1), on_long_press_repeat=sp_step(-0.1),
                       kids=[icon(None, "minus", 24, "text", align="CENTER")]),
                label(f"{w}_d_sp", "--", "f42", align="CENTER", y=-8),
                label(f"{w}_d_band", "", "f11", "cyan", align="CENTER", y=24),
                button(f"{w}_plus", -12, 0, 56, 56, align="RIGHT_MID",
                       on_click=sp_step(0.1), on_long_press_repeat=sp_step(0.1),
                       kids=[icon(None, "plus", 24, "text", align="CENTER")]),
            ]),
            box(None, 16, 132, 344, 56, bg="cyan_bg", border="cyan_deep", radius=10, kids=[
                icon(None, "brain", 24, "cyan", x=12, align="LEFT_MID"),
                label(None, "Adaptive Thermal Model", "f13", x=46, y=10),
                label(f"{w}_d_conf", "Confidence --", "f11", "text2", x=46, y=30),
                button(f"{w}_learn", -10, 0, 110, 38, align="RIGHT_MID", radius=19,
                       on_click=[{"lambda": f"id({t}_learn) = !id({t}_learn);"},
                                 {"script.execute": f"{t}_send_learn"}],
                       kids=[label(f"{w}_learn_l", "LEARNING --", "f12", align="CENTER")]),
            ]),
        ]),
        # ---- probes + actuators card
        box(None, 14, 278, 376, 310, bg="card1", border="border", radius=14, kids=[
            label(None, "DUAL PROBES & ACTUATOR HARDWARE" if dual
                  else "SINGLE PROBE & THERMAL ACTUATORS", "f12", "text2", x=16, y=17),
            label(None, "CONTROLLER BLE", "f11", "cyan", align="TOP_RIGHT", x=-16, y=18),
            *probes,
            act_row("heat", 192, "fire", "heat"),
            act_row("fan", 250, "fan", "cyan"),
        ]),
        # ---- TDS / pH
        box(None, 402, 66, 296, 116, bg="card1", border="border", radius=14, kids=[
            label(None, "TDS LIVE & 1-HOUR MEAN", "f12", "text2", x=16, y=14),
            label(f"{w}_d_tds_st", "", "f12", "green", align="TOP_RIGHT", x=-16, y=15),
            label(f"{w}_d_tds", "--", "f32", x=16, y=34),
            label(f"{w}_d_tds_u", "ppm live", "f13", "label", x=96, y=50),
            label(f"{w}_d_tds_m", "", "f13", "cyan", align="TOP_RIGHT", x=-16, y=48),
            track(f"{w}_d_tds_trk", 16, 78, 264),
            label(f"{w}_d_tds_t1", "", "f11", "muted", x=16, y=92),
            label(f"{w}_d_tds_t2", "", "f11", "amber", align="TOP_MID", x=40, y=92),
            label(f"{w}_d_tds_t3", "", "f11", "red", align="TOP_RIGHT", x=-16, y=92),
        ]),
        box(None, 710, 66, 300, 116, bg="card1", border="border", radius=14, kids=[
            label(None, T["ph_title"], "f12", "text2", x=16, y=14),
            label(f"{w}_d_ph_st", "", "f12", "green", align="TOP_RIGHT", x=-16, y=15),
            label(f"{w}_d_ph", "--", "f32", x=16, y=34),
            label(f"{w}_d_ph_u", "pH", "f13", "label", x=100, y=50),
            label(f"{w}_d_ph_tgt", "", "f13", "text", align="TOP_RIGHT", x=-16, y=48),
            track(f"{w}_d_ph_trk", 16, 78, 268),
            label(f"{w}_d_ph_t1", "", "f11", "muted", x=16, y=92),
            label(f"{w}_d_ph_t2", "", "f11", "muted", align="TOP_MID", y=92),
            label(f"{w}_d_ph_t3", "", "f11", "muted", align="TOP_RIGHT", x=-16, y=92),
        ]),
        # ---- 24 h chart
        box(None, 402, 192, 608, 258, bg="card1", border="border", radius=14, kids=[
            tab(0, 0, 16, 128, "Temperature (24h)"),
            tab(1, 1, 150, 82, "TDS (24h)"),
            tab(2, 2, 238, 72, "pH (24h)"),
            row(None, -16, 13, align="TOP_RIGHT", h=26, gap=12, kids=[
                legend_item("a", "cyan"), legend_item("b", "violet"), legend_item("sp", "green")]),
            plot,
            *[label(f"{w}_xl{i}", txt, "f11", "cyan" if i == 4 else "muted",
                    x=16 + 52 + int(PLOT_W * i / 4) - (14 if i < 4 else 26), y=234)
              for i, txt in enumerate(["-24h", "-18h", "-12h", "-6h", "Now"])],
        ]),
        # ---- light / CO2 / safety
        box(None, 402, 462, 608, 126, bg="card1", border="border", radius=14, kids=[
            icon(None, "sun", 18, "amber", x=16, y=16),
            label(None, "LIGHT & PHOTOPERIOD", "f12", "text2", x=40, y=18),
            label(f"{w}_d_lux", "--", "f18", x=16, y=52),
            label(f"{w}_d_sun", "", "f11", "muted", x=16, y=92, w=190, long_mode="WRAP"),
            icon(None, "co2", 18, "cyan", x=214, y=16),
            label(None, "CO2 & AERATION", "f12", "text2", x=238, y=18),
            row(None, 214, 48, h=28, gap=6, kids=[
                label(None, "CO2:", "f18", "label"), label(f"{w}_d_co2", "--", "f18"),
                label(f"{w}_d_co2_n", "", "f12", "muted")]),
            row(None, 214, 88, h=24, gap=6, kids=[
                icon(f"{w}_d_bub_i", "check", 18, "green"),
                label(f"{w}_d_bub", "", "f12", "green")]),
            icon(None, "shield", 18, "green", x=430, y=16),
            label(None, "SAFETY & SYSTEM", "f12", "text2", x=454, y=18),
            label(f"{w}_d_safe2", "--", "f18", x=430, y=52),
            label(f"{w}_d_ctrl", "", "f11", "muted", x=430, y=92),
        ]),
    ]
    return {"id": f"w_page_{t}", "bg_color": COL["canvas"], "scrollable": False,
            "widgets": widgets}

# ------------------------------------------------------- water change page


def wc_page():
    ro_step = lambda d: [  # noqa: E731
        {"lambda": (
            "float base = std::isnan(id(ro_target_pending)) ? id(ro_target) : id(ro_target_pending);\n"
            "if (std::isnan(base)) return;\n"
            f"id(ro_target_pending) = std::min(20.0f, std::max(0.5f, roundf((base + ({d})) * 2.0f) / 2.0f));\n")},
        {"script.execute": "ro_send_target"}]
    set_mode = lambda name, drain: [  # noqa: E731
        publish("water-flow-change/select/mode/command", name),
        {"lambda": f"id(wc_draining) = {'true' if drain else 'false'};"}]
    stat = lambda x, cap, vid, sid, vcolor: [  # noqa: E731
        label(None, cap, "f11", "label", x=x, y=12),
        label(vid, "--", "f18", vcolor, x=x, y=32),
        label(sid, "", "f11", "muted", x=x, y=58)]
    return {"id": "w_page_wc", "bg_color": COL["canvas"], "scrollable": False, "widgets": [
        back_button(),
        row(None, 122, 10, h=44, gap=14, kids=[
            label(None, "WATER CHANGE MANAGER", "f18"),
            pill("w_wc_state", [dot("w_wc_state_dot", "cyan"),
                                label("w_wc_state_l", "--", "f12", "cyan")],
                 bg="cyan_bg", border="cyan_deep", h=30, pad=12),
        ]),
        row(None, -16, 10, align="TOP_RIGHT", h=44, gap=10, kids=[
            pill("w_wc_batt_pill", [icon("w_wc_batt_pi", "battery", 18, "green"),
                                    label("w_wc_batt_l", "Hose Batt: --", "f12", "green")],
                 bg="green_bg", border="green_border", h=28, radius=6, pad=10),
            pill("w_wc_mqtt_pill", [icon(None, "wifi", 18, "cyan"),
                                    label("w_wc_mqtt_l", "MQTT --", "f12", "cyan")],
                 bg="cyan_bg", border="cyan_deep", h=28, radius=6, pad=10),
        ]),
        box(None, 14, 66, 622, 58, bg="card1", border="border", radius=12, kids=[
            button("w_wc_drain", 4, 0, 304, 48, align="LEFT_MID", on_click=set_mode("Draining", True),
                   kids=[row(None, 0, 0, align="CENTER", gap=8, h=24, kids=[
                       icon("w_wc_drain_i", "radio", 18, "heat"),
                       label("w_wc_drain_l", "MODE: DRAINING", "f15", "heat")])]),
            button("w_wc_fill", -4, 0, 304, 48, align="RIGHT_MID", on_click=set_mode("Refilling", False),
                   kids=[row(None, 0, 0, align="CENTER", gap=8, h=24, kids=[
                       icon("w_wc_fill_i", "radio", 18, "label"),
                       label("w_wc_fill_l", "SWITCH TO REFILL", "f15", "label")])]),
        ]),
        box(None, 14, 134, 622, 388, bg="card1", border="border", radius=14, kids=[
            label(None, "SELECTED TANK: 75 GALLON", "f12", "text2", x=20, y=18),
            label("w_wc_vol", "", "f11", "cyan", align="TOP_RIGHT", x=-20, y=20),
            row(None, 20, 120, h=20, gap=4, kids=[
                icon("w_wc_big_i", "water", 18, "heat"),
                label("w_wc_big_cap", "WATER REMOVED THIS CHANGE", "f11", "heat")]),
            label("w_wc_big", "--", "f58", x=20, y=142),
            label("w_wc_big_u", "gal", "f26", "cyan", x=150, y=170),
            {"arc": {"id": "w_wc_arc", "x": -46, "y": 110, "align": "TOP_RIGHT",
                     "width": 200, "height": 200, "rotation": 180, "start_angle": 0,
                     "end_angle": 180, "min_value": 0, "max_value": 1000, "value": 0,
                     "adjustable": False, "arc_width": 16, "arc_color": COL["btn"],
                     "arc_rounded": True,
                     "indicator": {"arc_width": 16, "arc_color": COL["heat"], "arc_rounded": True},
                     "knob": {"bg_opa": "TRANSP", "pad_all": 0}}},
            label("w_wc_pct", "--", "f32", align="TOP_RIGHT", x=-96, y=180),
            label(None, "OF TANK CHANGED", "f11", "label", align="TOP_RIGHT", x=-96, y=218),
            box(None, 20, 298, 582, 84, bg="card3", border="border", radius=10, kids=[
                *stat(14, "REALTIME FLOW", "w_wc_rate", "w_wc_flowing", "cyan"),
                *stat(204, "WATER ADDED", "w_wc_added", "w_wc_added_s", "text"),
                *stat(394, "NET WATER CHANGE", "w_wc_net", "w_wc_net_s", "heat"),
            ]),
        ]),
        button("w_wc_switch", 14, 534, 308, 56, on_click=[{"if": {
            "condition": {"lambda": "return id(wc_draining);"},
            "then": set_mode("Refilling", False), "else": set_mode("Draining", True)}}],
            kids=[row(None, 0, 0, align="CENTER", gap=8, h=24, kids=[
                icon(None, "swap", 18, "text2"),
                label("w_wc_switch_l", "SWITCH MODE", "f13", "text2")])]),
        button("w_wc_new", 334, 534, 302, 56, bg="card1", border="cyan_deep",
               on_long_press=[publish("water-flow-change/button/new_water_change/command", "PRESS")],
               kids=[row(None, 0, 0, align="CENTER", gap=8, h=24, kids=[
                   icon(None, "refresh", 18, "cyan"),
                   label(None, "NEW WATER CHANGE", "f13", "cyan"),
                   label(None, "(hold)", "f11", "muted")])]),
        box(None, 648, 66, 362, 384, bg="card1", border="border", radius=14, kids=[
            icon(None, "filter", 18, "cyan", x=18, y=20),
            label(None, "RO FILTER SYSTEM", "f15", x=46, y=21),
            pill("w_ro_on", [label("w_ro_on_l", "--", "f11", "cyan")], bg="cyan_bg",
                 border="cyan_deep", h=20, radius=4, pad=8, align="TOP_RIGHT", x=-16, y=20),
            box(None, 16, 62, 330, 104, bg="card2", border="border2", radius=10, kids=[
                label(None, "BATCH FILL VOLUME", "f11", "label", x=14, y=14),
                label("w_ro_d_flow", "", "f12", "cyan", align="TOP_RIGHT", x=-14, y=14),
                label("w_ro_d_val", "--", "f32", x=14, y=36),
                label("w_ro_d_u", "gal", "f18", "cyan", x=80, y=48),
                label("w_ro_d_of", "", "f13", "text2", align="TOP_RIGHT", x=-14, y=50),
                bar("w_ro_d_bar", 14, 84, 300, "cyan_deep", h=6),
            ]),
            label(None, "Target Reached:", "f12", "label", x=18, y=184),
            label("w_ro_d_reached", "--", "f12", align="TOP_RIGHT", x=-18, y=184),
            label(None, "Flow State:", "f12", "label", x=18, y=206),
            label("w_ro_d_state", "--", "f12", align="TOP_RIGHT", x=-18, y=206),
            label(None, "Lifetime Total:", "f12", "label", x=18, y=228),
            label("w_ro_d_total", "--", "f12", align="TOP_RIGHT", x=-18, y=228),
            box(None, 16, 252, 330, 56, bg="card1", border="border_act", radius=8, kids=[
                button("w_ro_minus", 6, 0, 48, 44, align="LEFT_MID", on_click=ro_step(-0.5),
                       kids=[icon(None, "minus", 18, "text", align="CENTER")]),
                row(None, 0, 0, align="CENTER", gap=8, h=24, kids=[
                    icon(None, "plus_circle", 18, "text2"),
                    label("w_ro_d_tgt", "SET TARGET (--)", "f13", "text2")]),
                button("w_ro_plus", -6, 0, 48, 44, align="RIGHT_MID", on_click=ro_step(0.5),
                       kids=[icon(None, "plus", 18, "text", align="CENTER")]),
            ]),
            button("w_ro_reset", 16, 316, 330, 56, bg="card1",
                   on_long_press=[publish("water-flow-ro/button/reset_fill/command", "PRESS")],
                   kids=[row(None, 0, 0, align="CENTER", gap=8, h=24, kids=[
                       icon(None, "refresh", 18, "text2"),
                       label(None, "RESET FILL COUNTER", "f13", "text2"),
                       label(None, "(hold)", "f11", "muted")])]),
        ]),
        box(None, 648, 460, 362, 128, bg="card1", border="border", radius=14, kids=[
            label(None, "SYSTEM & BATTERY CONTEXT", "f12", "text2", x=18, y=16),
            label(None, "Hose Sensor Battery", "f12", "label", x=18, y=46),
            label("w_wc_d_batt", "--", "f12", align="TOP_RIGHT", x=-18, y=46),
            label(None, "Last Water Change", "f12", "label", x=18, y=72),
            label("w_wc_d_last", "--", "f12", align="TOP_RIGHT", x=-18, y=72),
            label(None, "75 Gallon Actual Volume", "f12", "label", x=18, y=98),
            label("w_wc_d_vol", "--", "f12", align="TOP_RIGHT", x=-18, y=98),
        ]),
    ]}

# ------------------------------------------------------------ update lambda

UPDATE_COMMON = r"""
// ---------------------------------------------------------------- helpers
const uint32_t now_ms = millis();
auto txt = [](lv_obj_t *o, const char *fmt, ...) {
  char b[200];
  va_list ap; va_start(ap, fmt); vsnprintf(b, sizeof(b), fmt, ap); va_end(ap);
  if (strcmp(lv_label_get_text(o), b) != 0) lv_label_set_text(o, b);
};
auto col = [](lv_obj_t *o, uint32_t c) { lv_obj_set_style_text_color(o, lv_color_hex(c), 0); };
auto bg = [](lv_obj_t *o, uint32_t fill, uint32_t border) {
  lv_obj_set_style_bg_color(o, lv_color_hex(fill), 0);
  lv_obj_set_style_border_color(o, lv_color_hex(border), 0);
};
auto fill = [](lv_obj_t *o, uint32_t c) { lv_obj_set_style_bg_color(o, lv_color_hex(c), 0); };
auto show = [](lv_obj_t *o, bool on) {
  if (on) lv_obj_remove_flag(o, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
};
// "4m 12s", "38s", "2h 5m"
auto age = [](uint32_t ms, char *b, size_t n) {
  const uint32_t s = ms / 1000;
  if (s < 60) snprintf(b, n, "%us", (unsigned) s);
  else if (s < 3600) snprintf(b, n, "%um %us", (unsigned) (s / 60), (unsigned) (s % 60));
  else snprintf(b, n, "%uh %um", (unsigned) (s / 3600), (unsigned) (s / 60 % 60));
};
auto age_short = [](uint32_t ms, char *b, size_t n) {
  const uint32_t s = ms / 1000;
  if (s < 90) snprintf(b, n, "%us", (unsigned) s);
  else if (s < 5400) snprintf(b, n, "%um", (unsigned) (s / 60));
  else snprintf(b, n, "%uh", (unsigned) (s / 3600));
};
// 1420 -> "1,420"
auto thou = [](float v, char *b, size_t n) {
  const long x = lroundf(v);
  if (x >= 1000) snprintf(b, n, "%ld,%03ld", x / 1000, x % 1000); else snprintf(b, n, "%ld", x);
};
// Place a target-range track's band and marker. NaN bound = open-ended.
auto range = [](lv_obj_t *trk, lv_obj_t *band, lv_obj_t *mark, float v,
                float lo, float hi, float mn, float mx, uint32_t mark_col) {
  const int w = lv_obj_get_width(trk);
  auto px = [&](float x) { return (int) roundf((std::min(mx, std::max(mn, x)) - mn) / (mx - mn) * (w - 6)); };
  const int a = std::isnan(lo) ? 0 : px(lo), b = std::isnan(hi) ? w : px(hi);
  lv_obj_set_pos(band, a, 0); lv_obj_set_width(band, std::max(6, b - a));
  if (std::isnan(v)) { lv_obj_add_flag(mark, LV_OBJ_FLAG_HIDDEN); return; }
  lv_obj_remove_flag(mark, LV_OBJ_FLAG_HIDDEN);
  lv_obj_set_pos(mark, px(v), -2);
  lv_obj_set_style_bg_color(mark, lv_color_hex(mark_col), 0);
};
// Band judgement shared by tiles and detail cards:
// 0 in band, 1 near / above target (amber), 2 out / at alert (red), -1 unknown.
auto judge = [](float v, float lo, float hi, float alert, float near) {
  if (std::isnan(v)) return -1;
  if (!std::isnan(alert) && v >= alert) return 2;
  if (!std::isnan(hi) && v > hi) return (std::isnan(alert) && v > hi + near) ? 2 : 1;
  if (!std::isnan(lo) && v < lo) return v < lo - near ? 2 : 1;
  return 0;
};
const uint32_t J_COL[] = {0x10B981, 0xFBBF24, 0xEF4444};
const bool night = id(night_on);
const uint32_t C_TEXT = night ? 0x8C9CAE : 0xF8FAFC;
const uint32_t C_HEAD = night ? 0xC28238 : 0xF8FAFC;
const uint32_t C_UNIT = night ? 0x7D5627 : 0x38BDF8;
const uint32_t C_CARD = night ? 0x080D13 : 0x131B24;
const uint32_t C_CARD2 = night ? 0x0A1118 : 0x19232F;
const uint32_t C_CARD3 = night ? 0x0A1118 : 0x16202C;
const uint32_t C_BORDER = night ? 0x131C26 : 0x223142;
const uint32_t C_LABEL = night ? 0x506173 : 0x94A3B8;
const uint32_t C_CYAN = night ? 0x506173 : 0x38BDF8;
lv_obj_set_style_bg_color(id(w_page_home)->obj, lv_color_hex(night ? 0x040608 : 0x0B1015), 0);
auto tnow = id(sntp_time).now();
const bool mqtt_ok = id(mqtt_up);
const bool l75 = id(t75_stamp_ms) != 0 && now_ms - id(t75_stamp_ms) < 45000;
const bool l16 = id(t16_stamp_ms) != 0 && now_ms - id(t16_stamp_ms) < 45000;

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
// Link-down warnings are the panel's own; they count with HA's warnings.
const int n_links_down = (int) !l75 + (int) !l16;
const bool compact = n_alerts > 0;
show(id(w_alert), compact);
if (compact) {
  std::string up = top_title;
  for (auto &c : up) c = toupper((unsigned char) c);
  txt(id(w_alert_title), "%s", up.c_str());
  txt(id(w_alert_msg), "%s", top_msg.c_str());
  bg(id(w_alert), top_is_crit ? 0x2D0E12 : 0x291B07, top_is_crit ? 0xEF4444 : 0xD97706);
  fill(id(w_alert_disc), top_is_crit ? 0xEF4444 : 0xD97706);
  const bool is75 = top_title.find("75") != std::string::npos;
  const bool is16 = !is75 && (top_title.find("Nano") != std::string::npos ||
                              top_title.find("nano") != std::string::npos);
  id(alert_target) = is75 ? 1 : (is16 ? 2 : 0);
  show(id(w_alert_btn), is75 || is16);
  fill(id(w_alert_btn), top_is_crit ? 0xEF4444 : 0xD97706);
  txt(id(w_alert_btn_l), is75 ? "OPEN 75 GALLON" : "OPEN NANO");
}

// ----------------------------------------------------------- top bar
if (tnow.is_valid()) {
  txt(id(w_clock), "%s", tnow.strftime("%-I:%M %p").c_str());
  txt(id(w_date), "%s", tnow.strftime("%a %b %-d").c_str());
}
show(id(w_date), !night);
show(id(w_wake), night);
show(id(w_mqtt_pill), !night && !compact && n_links_down == 0);
show(id(w_ble_pill), !night && !compact);
txt(id(w_mqtt_l), mqtt_ok ? "MQTT Connected" : "MQTT Down");
col(id(w_mqtt_l), mqtt_ok ? 0xCBD5E1 : 0xFBBF24);
col(id(w_mqtt_i), mqtt_ok ? 0x94A3B8 : 0xFBBF24);
if (l75 && l16) { txt(id(w_ble_l), "Dual BLE Active"); col(id(w_ble_l), 0xCBD5E1); col(id(w_ble_i), 0x94A3B8); }
else if (l75 || l16) { txt(id(w_ble_l), "%s Connected", l75 ? "75G" : "Nano"); col(id(w_ble_l), 0x38BDF8); col(id(w_ble_i), 0x38BDF8); }
else { txt(id(w_ble_l), "BLE Down"); col(id(w_ble_l), 0xFBBF24); col(id(w_ble_i), 0xFBBF24); }
bg(id(w_logo), night ? 0x080D13 : 0x0C4A6E, night ? 0x131C26 : 0x0284C7);
col(id(w_brand), C_TEXT);
col(id(w_clock), C_TEXT);
{
  char b[120]; uint32_t fl, bd, tx;
  if (night) {
    snprintf(b, sizeof(b), "NIGHT MODE (Lights off · tap to wake) • 10%% DISPLAY BACKLIGHT");
    fl = 0x080D13; bd = 0x7D5627; tx = 0xC28238;
  } else if (n_crit > 0) {
    snprintf(b, sizeof(b), "%d CRITICAL ALERT%s ACTIVE — IMMEDIATE ACTION REQUIRED", n_crit, n_crit > 1 ? "S" : "");
    fl = 0x2D0E12; bd = 0xDC2626; tx = 0xEF4444;
  } else if (n_links_down > 0) {
    const bool down75 = !l75;
    const uint32_t st = down75 ? id(t75_stamp_ms) : id(t16_stamp_ms);
    if (st == 0) snprintf(b, sizeof(b), "WAITING FOR %s BLE LINK", down75 ? "75 GALLON" : "NANO");
    else { char a[16]; age(now_ms - st, a, sizeof(a));
           snprintf(b, sizeof(b), "%d CONNECTION WARNING: %s BLE LINK DOWN (%s)", n_links_down,
                    down75 ? "75 GALLON" : "NANO", a); }
    fl = 0x291B07; bd = 0xD97706; tx = 0xFBBF24;
  } else if (n_warn > 0) {
    snprintf(b, sizeof(b), "%d WARNING%s ACTIVE", n_warn, n_warn > 1 ? "S" : "");
    fl = 0x291B07; bd = 0xD97706; tx = 0xFBBF24;
  } else {
    snprintf(b, sizeof(b), "ALL SYSTEMS NORMAL • 0 ALERTS");
    fl = 0x0F291E; bd = 0x059669; tx = 0x10B981;
  }
  txt(id(w_status_l), "%s", b);
  col(id(w_status_l), tx);
  bg(id(w_status), fl, bd);
  fill(id(w_status_dot), tx);
}

// ----------------------------------------------------- bottom strip
{
  for (lv_obj_t *c : {id(w_ro_card), id(w_ha_card)}) bg(c, C_CARD, C_BORDER);
  bg(id(w_wc_card), C_CARD, night ? 0x131C26 : 0x0284C7);
  bg(id(w_wc_open), night ? 0x0A1118 : 0x0284C7, night ? 0x131C26 : 0x38BDF8);
  char t1[16], t2[16];
  // RO
  const bool ro_on = id(ro_online);
  if (!ro_on) { txt(id(w_ro_pill_l), "OFFLINE"); col(id(w_ro_pill_l), 0xFBBF24); bg(id(w_ro_pill), 0x291B07, 0xD97706); }
  else if (id(ro_flowing)) { txt(id(w_ro_pill_l), "FLOWING • %.2f GPM", std::isnan(id(ro_rate)) ? 0.0f : id(ro_rate)); col(id(w_ro_pill_l), C_CYAN); bg(id(w_ro_pill), night ? 0x080D13 : 0x0C4A6E, night ? 0x131C26 : 0x0284C7); }
  else { txt(id(w_ro_pill_l), "IDLE"); col(id(w_ro_pill_l), C_LABEL); bg(id(w_ro_pill), C_CARD2, night ? 0x131C26 : 0x334155); }
  if (std::isnan(id(ro_fill))) txt(id(w_ro_val), "--"); else txt(id(w_ro_val), "%.1f", id(ro_fill));
  col(id(w_ro_val), C_TEXT);
  lv_obj_update_layout(id(w_ro_val));
  lv_obj_align_to(id(w_ro_of), id(w_ro_val), LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -5);
  if (std::isnan(id(ro_target))) txt(id(w_ro_of), "/ -- gal"); else txt(id(w_ro_of), "/ %.1f gal", id(ro_target));
  const bool pct_ok = !std::isnan(id(ro_fill)) && !std::isnan(id(ro_target)) && id(ro_target) > 0;
  const int pct = pct_ok ? (int) roundf(id(ro_fill) / id(ro_target) * 100.0f) : 0;
  if (pct_ok) txt(id(w_ro_pct), "%d%% of Target", pct); else txt(id(w_ro_pct), "");
  lv_bar_set_value(id(w_ro_bar), std::min(100, pct), LV_ANIM_OFF);
  txt(id(w_ro_reached), "Target Reached: %s", id(ro_reached) ? "YES" : "NO");
  if (std::isnan(id(ro_total))) txt(id(w_ro_total), "");
  else { thou(id(ro_total), t1, sizeof(t1)); txt(id(w_ro_total), "Total: %s gal", t1); }
  // Water-change meter
  const bool wc_on = id(wc_online);
  if (!wc_on || std::isnan(id(wc_batt))) { txt(id(w_wc_batt), "--"); col(id(w_wc_batt), C_LABEL); col(id(w_wc_batt_i), C_LABEL); }
  else { const uint32_t c = id(wc_batt_low) ? 0xFBBF24 : (night ? 0x366B56 : 0x10B981);
         txt(id(w_wc_batt), "%.0f%%", id(wc_batt)); col(id(w_wc_batt), c); col(id(w_wc_batt_i), c); }
  show(id(w_wc_ready), !night);
  if (!wc_on) { txt(id(w_wc_ready_l), "OFFLINE"); col(id(w_wc_ready_l), 0xFBBF24); }
  else if (id(wc_flowing)) { txt(id(w_wc_ready_l), id(wc_draining) ? "DRAINING" : "REFILLING"); col(id(w_wc_ready_l), 0x38BDF8); }
  else { txt(id(w_wc_ready_l), "READY"); col(id(w_wc_ready_l), 0xCBD5E1); }
  if (id(wc_last_start) == 0) txt(id(w_wc_last), "Last Change: none recorded yet");
  else {
    auto t = ESPTime::from_epoch_local(id(wc_last_start));
    const int days = tnow.is_valid() ? (int) ((tnow.timestamp - id(wc_last_start)) / 86400) : -1;
    if (days >= 0) txt(id(w_wc_last), "Last Change: %s (%dd ago)", t.strftime("%b %-d").c_str(), days);
    else txt(id(w_wc_last), "Last Change: %s", t.strftime("%b %-d").c_str());
  }
  col(id(w_wc_last), night ? 0x8C9CAE : 0xCBD5E1);
  if (std::isnan(id(wc_volume))) txt(id(w_wc_vol_h), "75 Gal Net Volume: --");
  else txt(id(w_wc_vol_h), "75 Gal Net Volume: ~%.0f gal", id(wc_volume));
  if (!wc_on) txt(id(w_wc_mode_h), "Mode: meter offline");
  else txt(id(w_wc_mode_h), "Mode: %s (%s)", id(wc_flowing) ? (id(wc_draining) ? "Draining" : "Refilling") : "Standby",
           id(wc_draining) ? "Drain" : "Refill");
  if (std::isnan(id(wc_rate))) txt(id(w_wc_flow_h), ""); else txt(id(w_wc_flow_h), "Flow: %.1f gpm", id(wc_flowing) ? id(wc_rate) : 0.0f);
  // Home Assistant
  const int issues = n_alerts + n_links_down;
  if (!mqtt_ok) { txt(id(w_ha_pill_l), "MQTT DOWN"); col(id(w_ha_pill_l), 0xFBBF24); bg(id(w_ha_pill), 0x291B07, 0xD97706); }
  else if (n_crit) { txt(id(w_ha_pill_l), "%d CRITICAL", n_crit); col(id(w_ha_pill_l), 0xEF4444); bg(id(w_ha_pill), 0x2D0E12, 0xDC2626); }
  else if (issues) { txt(id(w_ha_pill_l), "%d WARNING%s", issues, issues > 1 ? "S" : ""); col(id(w_ha_pill_l), 0xFBBF24); bg(id(w_ha_pill), 0x291B07, 0xD97706); }
  else { txt(id(w_ha_pill_l), "SYNC OK"); col(id(w_ha_pill_l), night ? 0x366B56 : 0x10B981); bg(id(w_ha_pill), night ? 0x080D13 : 0x0F291E, night ? 0x131C26 : 0x059669); }
  const bool ha_alert_mode = mqtt_ok && issues > 0;
  if (n_crit) bg(id(w_ha_card), night ? 0x080D13 : 0x1A1114, 0xDC2626);
  else if (ha_alert_mode) bg(id(w_ha_card), night ? 0x080D13 : 0x1A1610, 0xD97706);
  show(id(w_ha_alert), ha_alert_mode);
  show(id(w_ha_k1), !ha_alert_mode); show(id(w_ha_v1), !ha_alert_mode);
  show(id(w_ha_k2), !ha_alert_mode); show(id(w_ha_v2), !ha_alert_mode);
  auto dusk = id(sun_pa).sunset(-6.0);
  if (ha_alert_mode) {
    if (n_alerts) txt(id(w_ha_alert), "%s", top_title.c_str());
    else {
      const uint32_t st = !l75 ? id(t75_stamp_ms) : id(t16_stamp_ms);
      char a[12]; age_short(now_ms - st, a, sizeof(a));
      if (st) txt(id(w_ha_alert), "%s BLE Link Down (%s)", !l75 ? "75G" : "Nano", a);
      else txt(id(w_ha_alert), "%s BLE Link Down", !l75 ? "75G" : "Nano");
    }
    col(id(w_ha_alert), n_crit ? 0xEF4444 : 0xFBBF24);
    if (std::isnan(id(ha_livestock_days))) txt(id(w_ha_k3), "Losses: --");
    else txt(id(w_ha_k3), "Losses: %.0fd clean", id(ha_livestock_days));
    if (dusk.has_value()) txt(id(w_ha_v3), "Dusk: %s", dusk->strftime("%-I:%M %p").c_str()); else txt(id(w_ha_v3), "");
    col(id(w_ha_v3), 0x94A3B8);
  } else {
    txt(id(w_ha_k1), "Livestock Loss:"); txt(id(w_ha_k2), "Civil Dusk:"); txt(id(w_ha_k3), "Active Alerts:");
    if (std::isnan(id(ha_livestock_days)) || !mqtt_ok) txt(id(w_ha_v1), "--");
    else txt(id(w_ha_v1), "%.0f days clean", id(ha_livestock_days));
    col(id(w_ha_v1), night ? 0x366B56 : 0x10B981);
    if (dusk.has_value()) txt(id(w_ha_v2), "%s", dusk->strftime("%-I:%M %p").c_str()); else txt(id(w_ha_v2), "--");
    col(id(w_ha_v2), C_TEXT);
    if (!mqtt_ok) txt(id(w_ha_v3), "--"); else txt(id(w_ha_v3), "%d Warnings", n_warn);
    col(id(w_ha_v3), C_CYAN);
  }
  (void) t2;
}

// ---------------------------------------------------- water change page
{
  const bool dr = id(wc_draining);
  char t1[16];
  bg(id(w_wc_drain), dr ? 0x261711 : 0x1E293B, dr ? 0xEA580C : 0x334155);
  bg(id(w_wc_fill), !dr ? 0x0C4A6E : 0x1E293B, !dr ? 0x0284C7 : 0x334155);
  txt(id(w_wc_drain_l), dr ? "MODE: DRAINING (ACTIVE)" : "SWITCH TO DRAIN");
  txt(id(w_wc_fill_l), !dr ? "MODE: REFILLING (ACTIVE)" : "SWITCH TO REFILL");
  col(id(w_wc_drain_l), dr ? 0xFB923C : 0x64748B); col(id(w_wc_drain_i), dr ? 0xFB923C : 0x64748B);
  col(id(w_wc_fill_l), !dr ? 0x38BDF8 : 0x64748B); col(id(w_wc_fill_i), !dr ? 0x38BDF8 : 0x64748B);
  txt(id(w_wc_switch_l), dr ? "SWITCH MODE (REFILL)" : "SWITCH MODE (DRAIN)");
  if (!id(wc_online)) txt(id(w_wc_state_l), "METER OFFLINE");
  else if (!id(wc_flowing)) txt(id(w_wc_state_l), "%s • IDLE", dr ? "DRAINING" : "REFILLING");
  else if (std::isnan(id(wc_rate))) txt(id(w_wc_state_l), "%s ACTIVE", dr ? "DRAINING" : "REFILLING");
  else txt(id(w_wc_state_l), "%s ACTIVE • %.1f GPM", dr ? "DRAINING" : "REFILLING", id(wc_rate));
  if (std::isnan(id(wc_batt))) txt(id(w_wc_batt_l), "Hose Batt: --");
  else txt(id(w_wc_batt_l), "Hose Batt: %.0f%% (%s)", id(wc_batt), id(wc_batt_low) ? "LOW" : "OK");
  col(id(w_wc_batt_l), id(wc_batt_low) ? 0xFBBF24 : 0x10B981);
  col(id(w_wc_batt_pi), id(wc_batt_low) ? 0xFBBF24 : 0x10B981);
  bg(id(w_wc_batt_pill), id(wc_batt_low) ? 0x291B07 : 0x0F291E, id(wc_batt_low) ? 0xD97706 : 0x059669);
  txt(id(w_wc_mqtt_l), mqtt_ok ? "MQTT Live" : "MQTT Down");
  const float big = dr ? id(wc_removed) : id(wc_added);
  txt(id(w_wc_big_cap), dr ? "WATER REMOVED THIS CHANGE" : "WATER ADDED THIS CHANGE");
  col(id(w_wc_big_cap), dr ? 0xFB923C : 0x38BDF8); col(id(w_wc_big_i), dr ? 0xFB923C : 0x38BDF8);
  if (std::isnan(big)) txt(id(w_wc_big), "--"); else txt(id(w_wc_big), "%.1f", big);
  lv_obj_update_layout(id(w_wc_big));
  lv_obj_align_to(id(w_wc_big_u), id(w_wc_big), LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -10);
  if (std::isnan(id(wc_volume))) txt(id(w_wc_vol), ""); else txt(id(w_wc_vol), "Actual Net Volume: ~%.0f Gal", id(wc_volume));
  if (std::isnan(id(wc_pct))) txt(id(w_wc_pct), "--"); else txt(id(w_wc_pct), "%.1f%%", id(wc_pct));
  lv_arc_set_value(id(w_wc_arc), std::isnan(id(wc_pct)) ? 0 : (int) std::min(1000.0f, id(wc_pct) * 10.0f));
  lv_obj_set_style_arc_color(id(w_wc_arc), lv_color_hex(dr ? 0xFB923C : 0x0284C7), LV_PART_INDICATOR);
  if (std::isnan(id(wc_rate))) txt(id(w_wc_rate), "--"); else txt(id(w_wc_rate), "%.1f gpm", id(wc_flowing) ? id(wc_rate) : 0.0f);
  txt(id(w_wc_flowing), "Flowing: %s", id(wc_flowing) ? "YES" : "NO");
  col(id(w_wc_flowing), id(wc_flowing) ? 0x10B981 : 0x64748B);
  if (std::isnan(id(wc_added))) txt(id(w_wc_added), "--"); else txt(id(w_wc_added), "%.1f gal", id(wc_added));
  txt(id(w_wc_added_s), dr ? "Refill inactive" : "Refilling");
  if (std::isnan(id(wc_net))) txt(id(w_wc_net), "--"); else txt(id(w_wc_net), "%+.1f gal", id(wc_net));
  col(id(w_wc_net), !std::isnan(id(wc_net)) && id(wc_net) < -0.05f ? 0xFB923C : 0xF8FAFC);
  txt(id(w_wc_net_s), "%s", !std::isnan(id(wc_net)) && id(wc_net) < -0.05f ? "Current deficit"
                      : (!std::isnan(id(wc_net)) && id(wc_net) > 0.05f ? "Current surplus" : "Balanced"));
  // RO card
  txt(id(w_ro_on_l), id(ro_online) ? "MQTT Online" : "Offline");
  if (std::isnan(id(ro_fill))) txt(id(w_ro_d_val), "--"); else txt(id(w_ro_d_val), "%.1f", id(ro_fill));
  lv_obj_update_layout(id(w_ro_d_val));
  lv_obj_align_to(id(w_ro_d_u), id(w_ro_d_val), LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -5);
  const float tgt = std::isnan(id(ro_target_pending)) ? id(ro_target) : id(ro_target_pending);
  if (std::isnan(tgt)) { txt(id(w_ro_d_of), ""); txt(id(w_ro_d_tgt), "SET TARGET (--)"); }
  else {
    txt(id(w_ro_d_tgt), "SET TARGET (%.1f GAL)", tgt);
    col(id(w_ro_d_tgt), std::isnan(id(ro_target_pending)) ? 0xCBD5E1 : 0xFBBF24);
    if (!std::isnan(id(ro_fill)) && tgt > 0) txt(id(w_ro_d_of), "Target: %.1f gal (%d%%)", tgt, (int) roundf(id(ro_fill) / tgt * 100));
    else txt(id(w_ro_d_of), "Target: %.1f gal", tgt);
  }
  lv_bar_set_value(id(w_ro_d_bar), (!std::isnan(id(ro_fill)) && !std::isnan(tgt) && tgt > 0)
                   ? std::min(100, (int) roundf(id(ro_fill) / tgt * 100)) : 0, LV_ANIM_OFF);
  if (id(ro_flowing) && !std::isnan(id(ro_rate))) txt(id(w_ro_d_flow), "Flowing • %.2f gpm", id(ro_rate));
  else txt(id(w_ro_d_flow), "Not flowing");
  txt(id(w_ro_d_reached), id(ro_reached) ? "YES" : "NO (In Progress)");
  col(id(w_ro_d_reached), id(ro_reached) ? 0x10B981 : 0x38BDF8);
  if (id(ro_flowing) && !std::isnan(id(ro_rate))) txt(id(w_ro_d_state), "Flowing (%.2f gpm)", id(ro_rate));
  else txt(id(w_ro_d_state), "%s", id(ro_online) ? "Idle" : "Offline");
  col(id(w_ro_d_state), id(ro_flowing) ? 0x10B981 : 0x94A3B8);
  if (std::isnan(id(ro_total))) txt(id(w_ro_d_total), "--");
  else { thou(id(ro_total), t1, sizeof(t1)); txt(id(w_ro_d_total), "%s gal produced", t1); }
  if (std::isnan(id(wc_batt))) txt(id(w_wc_d_batt), "--");
  else txt(id(w_wc_d_batt), "%.0f%% (Low Batt: %s)", id(wc_batt), id(wc_batt_low) ? "YES" : "NO");
  col(id(w_wc_d_batt), id(wc_batt_low) ? 0xFBBF24 : 0x10B981);
  if (id(wc_last_start) == 0) txt(id(w_wc_d_last), "--");
  else {
    const int days = tnow.is_valid() ? (int) ((tnow.timestamp - id(wc_last_start)) / 86400) : -1;
    auto t = ESPTime::from_epoch_local(id(wc_last_start));
    if (days >= 0) txt(id(w_wc_d_last), "%s (%dd ago)", t.strftime("%b %-d").c_str(), days);
    else txt(id(w_wc_d_last), "%s", t.strftime("%b %-d").c_str());
  }
  if (std::isnan(id(wc_volume))) txt(id(w_wc_d_vol), "--"); else txt(id(w_wc_d_vol), "~%.1f gal", id(wc_volume));
}
"""

UPDATE_TANK = r"""
// =========================================================== tank @T@
{
  const bool live = id(@T@_stamp_ms) != 0 && now_ms - id(@T@_stamp_ms) < 45000;
  const bool ever = id(@T@_stamp_ms) != 0;
  const bool stale = !live;
  const float temp = id(@T@_temp), sp = id(@T@_sp), swing = id(@T@_swing), dr = id(@T@_drift);
  const bool crit = live && (id(@T@_fault) ||
                    (!std::isnan(temp) && !std::isnan(sp) && fabsf(temp - sp) > 2.0f));
  char a[16]; age(now_ms - id(@T@_stamp_ms), a, sizeof(a));
  char as[12]; age_short(now_ms - id(@T@_stamp_ms), as, sizeof(as));

  // ---- layout: normal, or compact under the alert banner
  {
    static int last = -1;
    if (last != (int) compact) {
      last = compact;
      @LAYOUT@
    }
  }

  // ---- card frame and header
  if (stale) bg(id(w_@T@_card), night ? 0x080D13 : 0x0E141B, 0x475569);
  else if (crit) bg(id(w_@T@_card), night ? 0x080D13 : 0x1A1114, 0xEF4444);
  else bg(id(w_@T@_card), C_CARD, C_BORDER);
  lv_obj_set_style_border_width(id(w_@T@_card), crit ? 2 : 1, 0);
  show(id(w_@T@_head), !stale);
  show(id(w_@T@_link), !stale);
  show(id(w_@T@_lost), stale);
  show(id(w_@T@_frozen), stale && ever);
  col(id(w_@T@_title), crit ? 0xEF4444 : C_TEXT);
  if (live) {
    txt(id(w_@T@_link_l), "BLE Live • %us ago", (unsigned) ((now_ms - id(@T@_stamp_ms)) / 1000));
    col(id(w_@T@_link_l), C_CYAN); fill(id(w_@T@_link_dot), C_CYAN);
  } else {
    txt(id(w_@T@_lost_t), "%s", ever ? "BLUETOOTH LINK LOST" : "WAITING FOR BLUETOOTH LINK");
    if (id(@T@_stamp) != 0)
      txt(id(w_@T@_lost_s), "Showing values from %s • offline %s",
          ESPTime::from_epoch_local(id(@T@_stamp)).strftime("%-I:%M:%S").c_str(), ever ? a : "since boot");
    else
      txt(id(w_@T@_lost_s), "No data from the controller since the panel started");
    if (ever) txt(id(w_@T@_lost_pl), "STALE %s", as); else txt(id(w_@T@_lost_pl), "NO DATA");
  }

  // ---- hero
  bg(id(w_@T@_hero), crit ? 0x2D0E12 : (live ? C_CARD2 : 0x0E141B),
     crit ? 0xDC2626 : (live ? (night ? 0x131C26 : 0x243447) : 0x475569));
  if (std::isnan(temp)) txt(id(w_@T@_temp), "--"); else txt(id(w_@T@_temp), "%.1f", temp);
  col(id(w_@T@_temp), stale ? 0x64748B : (crit ? 0xEF4444 : C_HEAD));
  lv_obj_set_style_text_decor(id(w_@T@_temp), stale && !std::isnan(temp) ? LV_TEXT_DECOR_STRIKETHROUGH : LV_TEXT_DECOR_NONE, 0);
  col(id(w_@T@_unit), stale ? 0x475569 : (crit ? 0xEF4444 : C_UNIT));
  lv_obj_update_layout(id(w_@T@_temp));
  lv_obj_align_to(id(w_@T@_unit), id(w_@T@_temp), LV_ALIGN_OUT_RIGHT_BOTTOM, 8, -8);
  txt(id(w_@T@_sp_k), "%s", compact || stale ? "Target:" : "Setpoint:");
  if (std::isnan(sp)) txt(id(w_@T@_sp_v), "--"); else txt(id(w_@T@_sp_v), "%.1f °F", sp);
  if (stale) txt(id(w_@T@_sp_s), "(Unknown)");
  else if (crit && !std::isnan(temp) && !std::isnan(sp)) txt(id(w_@T@_sp_s), "(%+.1f° %s)", temp - sp, temp < sp ? "Deficit" : "Over");
  else if (std::isnan(swing)) txt(id(w_@T@_sp_s), ""); else txt(id(w_@T@_sp_s), "(±%.1f°)", swing);
  col(id(w_@T@_sp_k), stale ? 0x64748B : C_TEXT);
  col(id(w_@T@_sp_v), stale ? 0x64748B : (crit ? 0xEF4444 : C_CYAN));
  col(id(w_@T@_sp_s), crit ? 0xEF4444 : 0x64748B);
  bg(id(w_@T@_sp), C_CARD, crit ? 0xEF4444 : (night ? 0x131C26 : 0x334155));
  //@DUAL{
  {
    const float tb = id(@T@_temp_b), g = id(@T@_grad);
    char pa[12], pb[12];
    if (std::isnan(temp)) snprintf(pa, sizeof(pa), "--"); else snprintf(pa, sizeof(pa), "%.1f°", temp);
    if (std::isnan(tb)) snprintf(pb, sizeof(pb), "--"); else snprintf(pb, sizeof(pb), "%.1f°", tb);
    if (stale) txt(id(w_@T@_probes), "Dual Probe • Stale");
    else txt(id(w_@T@_probes), "A: %s  •  B: %s  •", pa, pb);
    show(id(w_@T@_grad), !stale);
    if (std::isnan(g)) txt(id(w_@T@_grad_l), "Δ --"); else txt(id(w_@T@_grad_l), "Δ %+.1f °F", g);
    col(id(w_@T@_grad_l), crit ? 0xEF4444 : C_CYAN);
    bg(id(w_@T@_grad), C_CARD, crit ? 0xDC2626 : (night ? 0x131C26 : 0x0284C7));
  }
  //@DUAL}
  //@SINGLE{
  txt(id(w_@T@_probes), "%s", stale ? "Single Probe • Stale" : "Single Probe Active");
  //@SINGLE}
  col(id(w_@T@_probes), stale ? 0x64748B : (crit ? 0xEF4444 : C_LABEL));
  if (stale) { txt(id(w_@T@_drift), "Drift: -- °F/min (Frozen)"); col(id(w_@T@_drift), 0xFBBF24); }
  else if (std::isnan(dr)) txt(id(w_@T@_drift), "");
  else {
    const bool falling = dr < -0.02f, rising = dr > 0.02f;
    const char *arrow = dr < -0.005f ? "↘" : (dr > 0.005f ? "↗" : "→");
    if (crit && falling) txt(id(w_@T@_drift), "%s %+.2f °F/min (RAPID FALL)", arrow, dr);
    else txt(id(w_@T@_drift), "%s %+.2f °F/min (%s)", arrow, dr, falling ? "Falling" : (rising ? "Rising" : "Stable"));
    col(id(w_@T@_drift), crit && falling ? 0xEF4444 : (night ? 0x366B56 : (dr < -0.005f ? 0x94A3B8 : 0x10B981)));
  }

  // ---- heater / fan tiles
  {
    const float h = id(@T@_heat), f = id(@T@_fan);
    const bool hon = id(@T@_heat_on), fon = id(@T@_fan_on);
    const bool hstall = crit && hon && h >= 99.0f && !std::isnan(dr) && dr < 0;
    if (stale) {
      txt(id(w_@T@_heat_cap), "HEATER DUTY"); txt(id(w_@T@_fan_cap), "FAN DUTY");
      txt(id(w_@T@_heat_val), "--%% (UNKNOWN)"); txt(id(w_@T@_fan_val), "--%% (UNKNOWN)");
      col(id(w_@T@_heat_val), 0xFBBF24); col(id(w_@T@_fan_val), 0xFBBF24);
      col(id(w_@T@_heat_cap), 0x94A3B8); col(id(w_@T@_fan_cap), 0x94A3B8);
      bg(id(w_@T@_heat), 0x0E141B, 0x334155); bg(id(w_@T@_fan), 0x0E141B, 0x334155);
      show(id(w_@T@_heat_i), false); show(id(w_@T@_fan_i), false);
      show(id(w_@T@_heat_bar), false); show(id(w_@T@_fan_bar), false);
    } else {
      show(id(w_@T@_heat_i), true); show(id(w_@T@_fan_i), true);
      show(id(w_@T@_heat_bar), true); show(id(w_@T@_fan_bar), true);
      txt(id(w_@T@_heat_cap), "%s", hstall ? "HEATER (STALLED)" : (hon ? "HEATER (DEMAND ON)" : "HEATER (IDLE)"));
      if (hstall) txt(id(w_@T@_heat_val), "%.0f%% • NO HEAT", h);
      else if (hon) txt(id(w_@T@_heat_val), "%.0f%% Duty", std::isnan(h) ? 0.0f : h);
      else txt(id(w_@T@_heat_val), "%.0f%% Duty (OFF)", std::isnan(h) ? 0.0f : h);
      col(id(w_@T@_heat_cap), hstall ? 0xEF4444 : (hon ? 0xFB923C : C_LABEL));
      col(id(w_@T@_heat_val), hstall ? 0xEF4444 : (hon ? (night ? 0xB47834 : 0xFB923C) : C_TEXT));
      bg(id(w_@T@_heat), hstall ? 0x3B1216 : (hon ? (night ? 0x150E0A : 0x261711) : C_CARD3),
         hstall ? 0xEF4444 : (hon ? (night ? 0x7D5627 : 0xEA580C) : C_BORDER));
      col(id(w_@T@_heat_i), hstall ? 0xEF4444 : (hon ? 0xFB923C : 0x64748B));
      txt(id(w_@T@_fan_cap), "%s", fon ? "COOLING FAN (ON)" : "COOLING FAN");
      if (fon) txt(id(w_@T@_fan_val), "%.0f%% Duty", std::isnan(f) ? 0.0f : f);
      else txt(id(w_@T@_fan_val), "%.0f%% Duty (OFF)", std::isnan(f) ? 0.0f : f);
      col(id(w_@T@_fan_cap), fon ? 0x38BDF8 : C_LABEL);
      col(id(w_@T@_fan_val), C_TEXT);
      bg(id(w_@T@_fan), fon ? 0x0C4A6E : C_CARD3, fon ? 0x0284C7 : C_BORDER);
      col(id(w_@T@_fan_i), fon ? 0x38BDF8 : 0x64748B);
    }
    lv_bar_set_value(id(w_@T@_heat_bar), live && !std::isnan(h) ? (int) h : 0, LV_ANIM_OFF);
    lv_bar_set_value(id(w_@T@_fan_bar), live && !std::isnan(f) ? (int) f : 0, LV_ANIM_OFF);
  }

  // ---- TDS / pH tiles and detail cards
  {
    const float tds = id(@T@_tds), tm = id(@T@_tds_mean);
    const float lo = @TDS_LO@, hi = @TDS_HI@, al = @TDS_ALERT@, mx = @TDS_MAX@;
    const float jv = std::isnan(tm) ? tds : tm;
    const int tj = judge(jv, lo, hi, al, 15.0f);
    const uint32_t tcol = tj < 0 ? 0x94A3B8 : J_COL[tj];
    const char *TJ[] = {"In Target Band", "Above Target", "Above Alert"};
    txt(id(w_@T@_tds_cap), "%s", stale ? "TDS (CACHED)" : "TDS (PURITY)");
    if (std::isnan(tds)) txt(id(w_@T@_tds_val), "--"); else txt(id(w_@T@_tds_val), "%.0f", tds);
    col(id(w_@T@_tds_val), stale ? 0x64748B : C_TEXT);
    lv_obj_update_layout(id(w_@T@_tds_val));
    lv_obj_align_to(id(w_@T@_tds_unit), id(w_@T@_tds_val), LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -5);
    if (stale) { txt(id(w_@T@_tds_tgt), "STALE"); col(id(w_@T@_tds_tgt), 0xFBBF24); }
    else {
      if (compact) txt(id(w_@T@_tds_tgt), "%s", tj == 0 ? "In Target" : (tj > 0 ? TJ[tj] : ""));
      else if (std::isnan(lo)) txt(id(w_@T@_tds_tgt), "Target: < %.0f", hi);
      else txt(id(w_@T@_tds_tgt), "Band: %.0f–%.0f", lo, hi);
      col(id(w_@T@_tds_tgt), compact && tj >= 0 ? tcol : C_LABEL);
    }
    if (std::isnan(tm)) txt(id(w_@T@_tds_side), ""); else txt(id(w_@T@_tds_side), "1h avg: %.0f", tm);
    col(id(w_@T@_tds_side), stale ? 0x64748B : C_CYAN);
    range(id(w_@T@_tds_trk), id(w_@T@_tds_trk_band), id(w_@T@_tds_trk_mark), live ? jv : NAN,
          lo, hi, @TDS_MIN@, @TDS_MAXS@, tcol);
    // detail
    if (std::isnan(tds)) txt(id(w_@T@_d_tds), "--"); else txt(id(w_@T@_d_tds), "%.0f", tds);
    col(id(w_@T@_d_tds), stale ? 0x64748B : 0xF8FAFC);
    lv_obj_update_layout(id(w_@T@_d_tds));
    lv_obj_align_to(id(w_@T@_d_tds_u), id(w_@T@_d_tds), LV_ALIGN_OUT_RIGHT_BOTTOM, 8, -6);
    if (std::isnan(tm)) txt(id(w_@T@_d_tds_m), ""); else txt(id(w_@T@_d_tds_m), "1h Mean: %.0f ppm", tm);
    txt(id(w_@T@_d_tds_st), "%s", stale ? "Stale" : (tj < 0 ? "" : TJ[tj]));
    col(id(w_@T@_d_tds_st), stale ? 0xFBBF24 : tcol);
    if (std::isnan(lo)) txt(id(w_@T@_d_tds_t1), "Target: < %.0f ppm", hi);
    else txt(id(w_@T@_d_tds_t1), "Target: %.0f–%.0f ppm", lo, hi);
    txt(id(w_@T@_d_tds_t2), "Alert: %.0f", al);
    if (std::isnan(mx)) txt(id(w_@T@_d_tds_t3), "%s", ""); else txt(id(w_@T@_d_tds_t3), "Max: %.0f", mx);
    range(id(w_@T@_d_tds_trk), id(w_@T@_d_tds_trk_band), id(w_@T@_d_tds_trk_mark), live ? jv : NAN,
          lo, hi, @TDS_MIN@, @TDS_MAXS@, tcol);

    const float ph = id(@T@_ph);
    const bool ph_live = id(@T@_ph_ms) != 0 && now_ms - id(@T@_ph_ms) < 3600000;
    const float plo = @PH_LO@, phi = @PH_HI@;
    const int pj = judge(ph, plo, phi, NAN, 0.15f);
    const uint32_t pcol = pj < 0 ? 0x94A3B8 : J_COL[pj];
    const char *PJ[] = {"Optimal", "Near Band", "Out of Band"};
    if (!ph_live && !std::isnan(ph)) txt(id(w_@T@_ph_cap), "%s", "@PH_TILE@ (CACHED)");
    else txt(id(w_@T@_ph_cap), "%s", "@PH_TILE@");
    if (std::isnan(ph)) txt(id(w_@T@_ph_val), "--"); else txt(id(w_@T@_ph_val), "%.2f", ph);
    col(id(w_@T@_ph_val), ph_live ? C_TEXT : 0x64748B);
    lv_obj_update_layout(id(w_@T@_ph_val));
    lv_obj_align_to(id(w_@T@_ph_unit), id(w_@T@_ph_val), LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -5);
    if (!ph_live && !std::isnan(ph)) { txt(id(w_@T@_ph_tgt), "STALE"); col(id(w_@T@_ph_tgt), 0xFBBF24); }
    else {
      if (compact) txt(id(w_@T@_ph_tgt), "%s", pj < 0 ? "" : PJ[pj]);
      else txt(id(w_@T@_ph_tgt), "Target: %.1f–%.1f", plo, phi);
      col(id(w_@T@_ph_tgt), compact && pj >= 0 ? pcol : C_LABEL);
    }
    if (!ph_live) { txt(id(w_@T@_ph_side), "%s", std::isnan(ph) ? "" : "Wi-Fi Link Stale"); col(id(w_@T@_ph_side), 0x64748B); }
    else if (compact) { txt(id(w_@T@_ph_side), "Target %.1f–%.1f", plo, phi); col(id(w_@T@_ph_side), pj > 0 ? pcol : C_LABEL); }
    else { txt(id(w_@T@_ph_side), "%s", pj < 0 ? "" : PJ[pj]); col(id(w_@T@_ph_side), night && pj == 0 ? 0x366B56 : pcol); }
    range(id(w_@T@_ph_trk), id(w_@T@_ph_trk_band), id(w_@T@_ph_trk_mark), ph_live ? ph : NAN,
          plo, phi, @PH_MIN@, @PH_MAX@, pcol);
    if (std::isnan(ph)) txt(id(w_@T@_d_ph), "--"); else txt(id(w_@T@_d_ph), "%.2f", ph);
    col(id(w_@T@_d_ph), ph_live ? 0xF8FAFC : 0x64748B);
    lv_obj_update_layout(id(w_@T@_d_ph));
    lv_obj_align_to(id(w_@T@_d_ph_u), id(w_@T@_d_ph), LV_ALIGN_OUT_RIGHT_BOTTOM, 8, -6);
    txt(id(w_@T@_d_ph_st), "%s", ph_live ? (pj < 0 ? "" : PJ[pj]) : (std::isnan(ph) ? "No data" : "Stale"));
    col(id(w_@T@_d_ph_st), ph_live ? pcol : 0xFBBF24);
    txt(id(w_@T@_d_ph_tgt), "Target: %.2f – %.2f", plo, phi);
    txt(id(w_@T@_d_ph_t1), "Min: %.2f", @PH_MIN@);
    txt(id(w_@T@_d_ph_t2), "Target Band: %.2f – %.2f", plo, phi);
    txt(id(w_@T@_d_ph_t3), "Max: %.2f", @PH_MAX@);
    range(id(w_@T@_d_ph_trk), id(w_@T@_d_ph_trk_band), id(w_@T@_d_ph_trk_mark), ph_live ? ph : NAN,
          plo, phi, @PH_MIN@, @PH_MAX@, pcol);
    bg(id(w_@T@_tds), stale ? 0x0E141B : C_CARD3, stale ? 0x334155 : C_BORDER);
    bg(id(w_@T@_ph), (stale && !ph_live) ? 0x0E141B : C_CARD3, (stale && !ph_live) ? 0x334155 : C_BORDER);
  }

  // ---- footer + detail info card
  {
    const float lux = id(@T@_lux);
    const int co2 = id(ha_co2_@T@), bub = id(ha_bubbler_@T@);
    const float conf = id(@T@_conf);
    const bool dark = live && !std::isnan(lux) && lux < 18.0f;
    if (!live || std::isnan(lux)) txt(id(w_@T@_f_lux), "-- lux");
    else if (dark) txt(id(w_@T@_f_lux), "%s", "Lights Off");
    else txt(id(w_@T@_f_lux), "%.0f lux", lux);
    lv_label_set_text(id(w_@T@_fi_lux), dark ? "@ICON_NIGHT@" : "@ICON_SUN@");
    col(id(w_@T@_fi_lux), night ? 0x506173 : 0xFBBF24);
    col(id(w_@T@_f_lux), C_LABEL);
    txt(id(w_@T@_f_co2), "CO2 %s", co2 < 0 ? "--" : (co2 ? "On" : "Off"));
    col(id(w_@T@_f_co2), co2 == 1 ? C_CYAN : C_LABEL); col(id(w_@T@_fi_co2), co2 == 1 ? C_CYAN : 0x64748B);
    txt(id(w_@T@_f_bub), "Bubbler %s", bub < 0 ? "--" : (bub ? "On" : "Off"));
    col(id(w_@T@_f_bub), bub == 1 ? C_CYAN : C_LABEL); col(id(w_@T@_fi_bub), bub == 1 ? C_CYAN : 0x64748B);
    if (stale) { txt(id(w_@T@_f_model), "BLE Down"); col(id(w_@T@_f_model), 0xFBBF24); col(id(w_@T@_fi_model), 0xFBBF24); }
    else if (id(@T@_fault)) { txt(id(w_@T@_f_model), "Safety Tripped"); col(id(w_@T@_f_model), 0xEF4444); col(id(w_@T@_fi_model), 0xEF4444); }
    else if (std::isnan(conf)) { txt(id(w_@T@_f_model), "Model --"); col(id(w_@T@_f_model), C_LABEL); }
    else { txt(id(w_@T@_f_model), "Model %.0f%%", conf); col(id(w_@T@_f_model), conf < 70 ? 0xFBBF24 : C_LABEL); col(id(w_@T@_fi_model), conf < 70 ? 0xFBBF24 : 0x64748B); }
    show(id(w_@T@_details), !stale);
    show(id(w_@T@_reconn), stale && ever);
    bg(id(w_@T@_details), crit ? 0x3B1216 : (night ? 0x0A1118 : 0x1E293B), crit ? 0xDC2626 : (night ? 0x131C26 : 0x334155));
    fill(id(w_@T@_sep), C_BORDER);

    if (!live || std::isnan(lux)) txt(id(w_@T@_d_lux), "-- lux");
    else if (dark) txt(id(w_@T@_d_lux), "%.0f lux (Lights Off)", lux);
    else txt(id(w_@T@_d_lux), "%.0f lux", lux);
    auto dawn = id(sun_pa).sunrise(-6.0); auto dusk = id(sun_pa).sunset(-6.0);
    if (dawn.has_value() && dusk.has_value())
      txt(id(w_@T@_d_sun), "Civil Dawn (%s) – Dusk (%s)", dawn->strftime("%-I:%M").c_str(), dusk->strftime("%-I:%M").c_str());
    txt(id(w_@T@_d_co2), "%s", co2 < 0 ? "--" : (co2 ? "ON" : "OFF"));
    col(id(w_@T@_d_co2), co2 == 1 ? 0x38BDF8 : 0xF8FAFC);
    // Schedule notes from Home Assistant: "(Schedule off)", "(7:31–3:10)".
    const std::string &cn = id(ha_co2_note_@T@), &bn = id(ha_bubbler_note_@T@);
    if (cn.empty()) txt(id(w_@T@_d_co2_n), "%s", ""); else txt(id(w_@T@_d_co2_n), "(%s)", cn.c_str());
    if (bn.empty()) txt(id(w_@T@_d_bub), "Bubbler: %s", bub < 0 ? "--" : (bub ? "ON" : "OFF"));
    else txt(id(w_@T@_d_bub), "Bubbler: %s (%s)", bub < 0 ? "--" : (bub ? "ON" : "OFF"), bn.c_str());
    col(id(w_@T@_d_bub), bub == 1 ? 0x10B981 : 0x94A3B8);
    lv_label_set_text(id(w_@T@_d_bub_i), bub == 1 ? "@ICON_CHECK@" : "@ICON_MINUSC@");
    col(id(w_@T@_d_bub_i), bub == 1 ? 0x10B981 : 0x94A3B8);
    if (!live) { txt(id(w_@T@_d_safe2), "Safety Tripped: --"); col(id(w_@T@_d_safe2), 0x94A3B8); }
    else { txt(id(w_@T@_d_safe2), "Safety Tripped: %s", id(@T@_fault) ? "YES" : "NO"); col(id(w_@T@_d_safe2), id(@T@_fault) ? 0xEF4444 : 0x10B981); }
    if (live) txt(id(w_@T@_d_ctrl), "Controller BLE: Live (%s ago)", as);
    else txt(id(w_@T@_d_ctrl), "Controller BLE: Down (%s)", ever ? as : "no data yet");
  }

  // ---- detail header, setpoint, probes, actuators
  {
    if (live) txt(id(w_@T@_d_link_l), "BLE Live • %s ago", as);
    else txt(id(w_@T@_d_link_l), "BLE Down • %s", ever ? a : "no data yet");
    col(id(w_@T@_d_link_l), live ? 0x38BDF8 : 0xFBBF24); fill(id(w_@T@_d_link_dot), live ? 0x38BDF8 : 0xFBBF24);
    if (!live) txt(id(w_@T@_d_safety_l), "SAFETY: UNKNOWN (LINK DOWN)");
    else txt(id(w_@T@_d_safety_l), "%s", id(@T@_fault) ? "SAFETY TRIPPED: YES" : "SAFETY TRIPPED: NO (NORMAL)");
    const uint32_t sc = !live ? 0xFBBF24 : (id(@T@_fault) ? 0xEF4444 : 0x10B981);
    col(id(w_@T@_d_safety_l), sc); col(id(w_@T@_d_safety_i), sc);
    bg(id(w_@T@_d_safety), !live ? 0x291B07 : (id(@T@_fault) ? 0x2D0E12 : 0x0F291E),
       !live ? 0xD97706 : (id(@T@_fault) ? 0xDC2626 : 0x059669));
    const float shown = std::isnan(id(@T@_sp_pending)) ? sp : id(@T@_sp_pending);
    if (std::isnan(shown)) txt(id(w_@T@_d_sp), "--"); else txt(id(w_@T@_d_sp), "%.1f", shown);
    col(id(w_@T@_d_sp), std::isnan(id(@T@_sp_pending)) ? 0xF8FAFC : 0xFBBF24);
    if (!std::isnan(id(@T@_sp_pending))) txt(id(w_@T@_d_band), "Sending to controller…");
    else if (std::isnan(sp) || std::isnan(swing)) txt(id(w_@T@_d_band), "%s", "");
    else txt(id(w_@T@_d_band), "Control Band: %.1f° – %.1f°F", sp - swing, sp + swing);
    if (std::isnan(swing)) txt(id(w_@T@_d_swing_l), "SWING --"); else txt(id(w_@T@_d_swing_l), "SWING ±%.1f °F", swing);
    const float conf = id(@T@_conf);
    if (std::isnan(conf)) txt(id(w_@T@_d_conf), "Confidence: --");
    else txt(id(w_@T@_d_conf), "Confidence: %.0f%%", conf);
    const bool ln = id(@T@_learn);
    txt(id(w_@T@_learn_l), "%s", ln ? "LEARNING ON" : "LEARNING OFF");
    col(id(w_@T@_learn_l), ln ? 0x10B981 : 0x94A3B8);
    bg(id(w_@T@_learn), ln ? 0x0F291E : 0x1E293B, ln ? 0x059669 : 0x334155);
    if (std::isnan(temp)) txt(id(w_@T@_d_pa), "--"); else txt(id(w_@T@_d_pa), "%.1f", temp);
    col(id(w_@T@_d_pa), live ? 0xF8FAFC : 0x64748B);
    lv_obj_update_layout(id(w_@T@_d_pa));
    lv_obj_align_to(id(w_@T@_d_pa_u), id(w_@T@_d_pa), LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -5);
    //@DUAL{
    {
      const float tb = id(@T@_temp_b), g = id(@T@_grad);
      if (std::isnan(tb)) txt(id(w_@T@_d_pb), "--"); else txt(id(w_@T@_d_pb), "%.1f", tb);
      col(id(w_@T@_d_pb), live ? 0xF8FAFC : 0x64748B);
      lv_obj_update_layout(id(w_@T@_d_pb));
      lv_obj_align_to(id(w_@T@_d_pb_u), id(w_@T@_d_pb), LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -5);
      if (std::isnan(g)) txt(id(w_@T@_d_grad), "--"); else txt(id(w_@T@_d_grad), "%+.2f °F", g);
      if (!live || std::isnan(dr)) txt(id(w_@T@_d_drift), "%s", "");
      else txt(id(w_@T@_d_drift), "%s %+.2f °F/min Drift", dr < -0.005f ? "↘" : (dr > 0.005f ? "↗" : "→"), dr);
    }
    //@DUAL}
    //@SINGLE{
    if (!live || std::isnan(dr)) txt(id(w_@T@_d_drift), "Drift --");
    else txt(id(w_@T@_d_drift), "%s %+.2f °F/min (%s)", dr < -0.005f ? "↘" : (dr > 0.005f ? "↗" : "→"), dr,
             dr < -0.02f ? "Falling" : (dr > 0.02f ? "Rising" : "Stable"));
    {
      const bool aligned = live && !std::isnan(temp) && !std::isnan(sp) && !std::isnan(swing) && fabsf(temp - sp) <= swing;
      txt(id(w_@T@_d_aligned), "%s", live ? (aligned ? "Setpoint Aligned" : "Outside control band") : "");
      col(id(w_@T@_d_aligned), aligned ? 0x10B981 : 0xFBBF24);
    }
    //@SINGLE}
    const float h = id(@T@_heat), f = id(@T@_fan);
    const bool hon = id(@T@_heat_on), fon = id(@T@_fan_on);
    txt(id(w_@T@_d_heat_cap), "%s", hon ? "HEATER DEMAND: ON" : "HEATER DEMAND: OFF");
    col(id(w_@T@_d_heat_cap), hon ? 0xFB923C : 0x94A3B8);
    if (!live || std::isnan(h)) { txt(id(w_@T@_d_heat_pct), "--"); txt(id(w_@T@_d_heat_sub), "Duty Cycle: --"); }
    else { txt(id(w_@T@_d_heat_pct), "%.0f%%", h); if (hon) txt(id(w_@T@_d_heat_sub), "Duty Cycle: %.0f%%", h); else txt(id(w_@T@_d_heat_sub), "Duty Cycle: %.0f%% (Idle)", h); }
    col(id(w_@T@_d_heat_pct), hon ? 0xFB923C : 0x94A3B8);
    bg(id(w_@T@_d_heat), hon ? 0x261711 : 0x16202C, hon ? 0xEA580C : 0x223142);
    col(id(w_@T@_d_heat_i), hon ? 0xFB923C : 0x64748B);
    lv_bar_set_value(id(w_@T@_d_heat_bar), live && !std::isnan(h) ? (int) h : 0, LV_ANIM_OFF);
    txt(id(w_@T@_d_fan_cap), "%s", fon ? "COOLING FAN DEMAND: ON" : "COOLING FAN DEMAND: OFF");
    col(id(w_@T@_d_fan_cap), fon ? 0x38BDF8 : 0x94A3B8);
    if (!live || std::isnan(f)) { txt(id(w_@T@_d_fan_pct), "--"); txt(id(w_@T@_d_fan_sub), "Duty Cycle: --"); }
    else { txt(id(w_@T@_d_fan_pct), "%.0f%%", f); if (fon) txt(id(w_@T@_d_fan_sub), "Duty Cycle: %.0f%%", f); else txt(id(w_@T@_d_fan_sub), "Duty Cycle: %.0f%% (Idle)", f); }
    col(id(w_@T@_d_fan_pct), fon ? 0x38BDF8 : 0x94A3B8);
    bg(id(w_@T@_d_fan), fon ? 0x0C4A6E : 0x16202C, fon ? 0x0284C7 : 0x223142);
    col(id(w_@T@_d_fan_i), fon ? 0x38BDF8 : 0x64748B);
    lv_bar_set_value(id(w_@T@_d_fan_bar), live && !std::isnan(f) ? (int) f : 0, LV_ANIM_OFF);
  }
}
"""

CHART_TANK = r"""
// ------------------------------------------------- chart, tank @T@
{
  const int mode = id(@T@_chart_mode);
  lv_obj_t *tabs[3] = {id(w_@T@_tab0), id(w_@T@_tab1), id(w_@T@_tab2)};
  lv_obj_t *tabl[3] = {id(w_@T@_tab0_l), id(w_@T@_tab1_l), id(w_@T@_tab2_l)};
  for (int i = 0; i < 3; i++) {
    lv_obj_set_style_bg_color(tabs[i], lv_color_hex(i == mode ? 0x0284C7 : 0x1E293B), 0);
    lv_obj_set_style_border_color(tabs[i], lv_color_hex(i == mode ? 0x38BDF8 : 0x334155), 0);
    lv_obj_set_style_text_color(tabl[i], lv_color_hex(i == mode ? 0xF8FAFC : 0x94A3B8), 0);
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
  // Fixed-step axes like the mockup: 0.5 °F, 10 ppm, 0.1 pH per gridline,
  // centred on the data (on the setpoint for temperature).
  const float step = mode == 0 ? 0.5f : (mode == 1 ? 10.0f : 0.1f);
  if (any) {
    const float c = (mode == 0 && !std::isnan(sp)) ? sp : (lo + hi) / 2.0f;
    const float mid = roundf(c / step) * step;
    float half = 2.0f * step;
    while (mid - half > lo || mid + half < hi) half += 2.0f * step;
    lo = mid - half; hi = mid + half;
  }
  const char *fmt = mode == 1 ? "%.0f" : (mode == 2 ? "%.1f" : "%.1f°");
  lv_obj_t *yl[5] = {id(w_@T@_yl0), id(w_@T@_yl1), id(w_@T@_yl2), id(w_@T@_yl3), id(w_@T@_yl4)};
  for (int i = 0; i < 5; i++) {
    if (!any) { txt(yl[i], "%s", ""); continue; }
    txt(yl[i], fmt, hi - (hi - lo) * i / 4.0f);
    lv_obj_set_style_text_color(yl[i], lv_color_hex(i == 2 && mode == 0 ? 0x10B981 : 0x64748B), 0);
  }
  if (mode == 0) {
    txt(id(w_@T@_lg_a_l), "%s", @DUAL@ ? "Probe A" : "Water Temp");
    txt(id(w_@T@_lg_b_l), "%s", "Probe B");
    if (std::isnan(sp)) txt(id(w_@T@_lg_sp_l), "%s", "Setpoint"); else txt(id(w_@T@_lg_sp_l), "Setpoint (%.1f°)", sp);
  } else {
    txt(id(w_@T@_lg_a_l), "%s", mode == 1 ? "TDS (ppm)" : "pH");
  }
  show(id(w_@T@_lg_b), use_b);
  show(id(w_@T@_lg_sp), mode == 0);
  show(id(w_@T@_plot_empty), n < 2);
  static lv_point_precise_t pa_@T@[96], pb_@T@[96], ps_@T@[2];
  auto build = [&](const std::array<float, 96> &S, lv_point_precise_t *pts) {
    int k = 0;
    for (int i = 0; i < n; i++) {
      if (std::isnan(S[i])) continue;
      // Newest sample at the right edge, 15 min per step across 24 h.
      pts[k].x = (lv_value_precise_t) (@PW@ - (n - 1 - i) * (float) @PW@ / 95.0f);
      pts[k].y = (lv_value_precise_t) ((hi - S[i]) / (hi - lo) * @PH@);
      k++;
    }
    return k;
  };
  const int ka = any ? build(A, pa_@T@) : 0;
  lv_line_set_points(id(w_@T@_ln_a)->obj, pa_@T@, ka);
  const int kb = (any && use_b) ? build(B, pb_@T@) : 0;
  lv_line_set_points(id(w_@T@_ln_b)->obj, pb_@T@, kb);
  if (any && mode == 0 && !std::isnan(sp)) {
    const float y = (hi - sp) / (hi - lo) * @PH@;
    ps_@T@[0] = {0, (lv_value_precise_t) y}; ps_@T@[1] = {@PW@, (lv_value_precise_t) y};
    lv_line_set_points(id(w_@T@_ln_sp)->obj, ps_@T@, 2);
  } else {
    lv_line_set_points(id(w_@T@_ln_sp)->obj, ps_@T@, 0);
  }
}
"""


def layout_code(T):
    """C++ that moves one card's blocks to the normal or compact layout."""
    t = T["t"]
    parts = []
    for mode in ("compact", "normal"):
        L = LAYOUT[mode]
        lines = [
            f"lv_obj_set_pos(id(w_{t}_card), {T['card_x']}, {L['card'][0]}); "
            f"lv_obj_set_height(id(w_{t}_card), {L['card'][1]});",
            f"lv_obj_set_y(id(w_{t}_head), {L['head']}); lv_obj_set_y(id(w_{t}_link), {L['head'] + 4});",
            f"lv_obj_set_y(id(w_{t}_lost), {L['lost']});",
            f"lv_obj_set_y(id(w_{t}_hero), {L['hero'][0]}); lv_obj_set_height(id(w_{t}_hero), {L['hero'][1]});",
            f"lv_obj_set_y(id(w_{t}_frozen), {L['hero'][0] - 9});",
            f"for (lv_obj_t *o : {{id(w_{t}_heat), id(w_{t}_fan)}}) "
            f"{{ lv_obj_set_y(o, {L['act'][0]}); lv_obj_set_height(o, {L['act'][1]}); }}",
            f"for (lv_obj_t *o : {{id(w_{t}_tds), id(w_{t}_ph)}}) "
            f"{{ lv_obj_set_y(o, {L['met'][0]}); lv_obj_set_height(o, {L['met'][1]}); }}",
            f"lv_obj_set_y(id(w_{t}_tds_trk), {L['met'][1] - 18}); lv_obj_set_y(id(w_{t}_ph_trk), {L['met'][1] - 18});",
            f"lv_obj_set_y(id(w_{t}_sep), {L['sep']}); lv_obj_set_y(id(w_{t}_foot), {L['foot']});",
            f"lv_obj_set_y(id(w_{t}_details), {L['details']}); lv_obj_set_y(id(w_{t}_reconn), {L['reconn']});",
        ]
        parts.append(("if (compact) {" if mode == "compact" else "} else {") + "\n        "
                     + "\n        ".join(lines))
    return "\n      ".join(parts) + "\n      }"


def tank_code(tmpl, T):
    """Fill one tank into a C++ template. //@DUAL{ ... //@DUAL} blocks are
    kept only for the two-probe tank and //@SINGLE{ ... //@SINGLE} only for
    the one-probe tank: ESPHome resolves every id() in a lambda even inside
    a branch that can never run, so dead branches must not exist at all."""
    keep, drop = ("DUAL", "SINGLE") if T["dual"] else ("SINGLE", "DUAL")
    tmpl = re.sub(rf"[ \t]*//@{drop}{{.*?//@{drop}}}\n", "", tmpl, flags=re.S)
    tmpl = re.sub(rf"[ \t]*//@{keep}[{{}}]\n", "", tmpl)

    def num(v):
        return "NAN" if v == "NAN" else f"{float(v)}f"
    rep = {
        "@LAYOUT@": layout_code(T),
        "@TDS_LO@": num(T["tds_lo"]), "@TDS_HI@": num(T["tds_hi"]),
        "@TDS_ALERT@": num(T["tds_alert"]), "@TDS_MAXS@": num(T["tds_scale"][1]),
        "@TDS_MAX@": num(T["tds_max"]), "@TDS_MIN@": num(T["tds_scale"][0]),
        "@PH_LO@": num(T["ph_lo"]), "@PH_HI@": num(T["ph_hi"]),
        "@PH_MIN@": num(T["ph_scale"][0]), "@PH_MAX@": num(T["ph_scale"][1]),
        "@PH_TILE@": T["ph_tile"], "@PW@": str(PLOT_W), "@PH@": f"{float(PLOT_H)}f",
        "@ICON_SUN@": ICON["sun"], "@ICON_NIGHT@": ICON["night"],
        "@ICON_CHECK@": ICON["check"], "@ICON_MINUSC@": ICON["minus_circle"],
        "@DUAL@": "true" if T["dual"] else "false",
        "@T@": T["t"],
    }
    for k, v in rep.items():
        tmpl = tmpl.replace(k, v)
    return tmpl

# ------------------------------------------------------------------- fonts

TEXT_EXTRA = "°±·–—−•●Δ↗↘→←›…"
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


HEADER = """\
# GENERATED by tools/gen_panel_p4_ui.py -- do not edit by hand; edit the
# generator and rerun it. The 10.1" P4 wall panel's LVGL UI.
#
# Design: design/p4-panel/ (DESIGN.md, REVISION-1.md).
# Data:   packages/panel_p4_tank.yaml (t75, t16) and panel_p4_feeds.yaml.
"""


def build():
    """The generated YAML as text."""
    home = {"id": "w_page_home", "bg_color": COL["canvas"], "scrollable": False,
            "widgets": top_bar() + [tank_card(T) for T in TANKS] + strip() + [alert_banner()]}
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
                {"obj": {"id": "w_night_shield", "x": 0, "y": 0, "width": 1024, "height": 600,
                         "bg_opa": "TRANSP", "border_width": 0, "hidden": True,
                         "on_click": [{"lambda": "lv_obj_add_flag(id(w_night_shield), LV_OBJ_FLAG_HIDDEN);"}]}},
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
        "if (want) lv_obj_remove_flag(id(w_night_shield), LV_OBJ_FLAG_HIDDEN);\n"
        "else lv_obj_add_flag(id(w_night_shield), LV_OBJ_FLAG_HIDDEN);\n"
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
    if PREVIEW:
        text = text.replace("- logger.log: 'preview: would publish @ROPAYLOAD@ to",
                            "- logger.log: 'preview: would publish target to")
    return HEADER + text


def main():
    text = build()
    OUT.write_text(text)
    print(f"wrote {OUT} ({len(text.splitlines())} lines)")


if __name__ == "__main__":
    main()
