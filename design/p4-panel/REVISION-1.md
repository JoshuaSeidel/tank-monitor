# Revision 1: approved direction, fix list

The owner loves the current design. Keep the visual direction, palette, typography,
layout and component styles exactly as they are. Make only the changes below, in
every screen where they apply, then update `DESIGN.md` and `index.html` to match.

## Facts to correct
1. Product name: **Tank Monitor** (not "AQUA·P4"). Keep the logo tile.
2. The Nano is a **Fluval Spec 16**: 16 gal tank, ~14 gal of water. Setpoint 74.5 °F.
   Sample Nano temperature 74.4 °F. Replace every "~12 gallon" label.
3. **Both tanks have CO2 and a bubbler.** Show CO2 on/off and bubbler on/off on
   both tank cards and both detail screens (75: CO2 off until November; Nano: CO2 on
   during the day).
4. The panel gets Home Assistant data over **MQTT**, so status pills say
   "MQTT Connected" / "MQTT Down", not "HA Connected". The Home Assistant strip may
   keep its title.
5. Nano pH comes from the Nano's own controller over Wi-Fi (MQTT), not from Home
   Assistant. Label it "pH (Wi-Fi)".
6. Livestock "days since last loss" is one number for the whole house, not per tank.
   Show it only in the Home Assistant strip, never inside a tank card or detail screen.
7. "Last water change" is the date the water-change meter last started a new change.
   Show it on the water-change screen and in the water-change strip only.

## Remove things that have no real action or data behind them
8. Remove the buttons "Diagnose", "Fix Issue", "Silence 15M", "Complete & Log Change"
   and "Retry BLE Reconnect". The Bluetooth link reconnects on its own.
   - Alert banner: one button, "Open 75 Gallon", which goes to that tank's detail.
   - Critical tank card: the normal "Details" button.
   - Offline card: no button; keep the "Bluetooth link lost / showing values from
     14:35:10 / offline 4m 12s" header.
9. Water-change screen: there is **no change target**. Remove "Target: 20 gal",
   "1.8 gal remaining until 20.0 gal target" and any target marker on the arc.
   The arc shows percent of the 62 gal of water changed (18.2 gal = 29.4 %).
   Actions available: **New Water Change** (zeroes this change's counters) and the
   **Draining / Refilling** mode switch. The RO card keeps "Set Target" and
   "Reset Fill".
10. Remove invented hardware text: "triac controller", "GFCI", "Controller Hardware
    v2.1 • ESP32", "Interlock Engaged". Alert body text becomes:
    "Heater on at 100 % but water is falling 0.15 °F/min. Check the heater and its
    power." "Safety tripped" is a real field and stays.
11. Night mode is entered when the room goes dark (tank lights off after civil dusk),
    not at fixed clock times. Replace "22:00 – 06:30" with "Lights off · tap to wake".

## LVGL drawing limits
12. No dashed borders anywhere. Stale cards use a solid 1 px `STALE_GREY_BORDER`,
    the dimmed fill, the struck-through temperature, and an amber "STALE 4m" pill.
13. Charts: solid lines only, no filled area under lines. Probe B is a second solid
    line in a different colour. Setpoint is a thin solid horizontal line.

## Unchanged
Everything else: sizes, spacing, colours, fonts, layout, the 1024 x 600 frame, the
seven screen files and their names.
