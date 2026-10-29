# Tank Monitor UI Design System & LVGL 9 Rebuild Specification

**Target Hardware:** Elecrow CrowPanel Advanced 10.1" (ESP32-P4)  
**Resolution:** 1024 × 600 px Landscape  
**Display Technology:** IPS 400 nits, Capacitive 5-point touch, 16-bit colour (RGB565)  
**Framework:** LVGL 9 via ESPHome  

---

## 1. Visual Direction & Design Philosophy

The Tank Monitor interface is engineered as an **appliance-grade, glanceable wall dashboard** for an active home office.

1. **Glanceable Hierarchy (1–3 Metres):**  
   From across the room, the primary water temperature for both tanks is immediately readable via 58px extra-bold tabular typography. Secondary metrics (TDS, pH, actuator duty) become clear when stepping up to within 1 metre, and detailed configuration controls engage on direct touch.
2. **RGB565 16-Bit Colour Integrity:**  
   To prevent chromatic banding on the CrowPanel's 16-bit display, large soft gradients and glassmorphism blurs are strictly prohibited. The system utilizes crisp, solid surface fills, 1px precision structural borders, and purposeful accent colours.
3. **Ergonomic Touch Targets:**  
   Every interactive button, mode selector, and setpoint adjustment target satisfies a minimum touch envelope of **56 × 56 px** (or min 56 px height on full-width buttons), ensuring confident finger operation without mis-taps.
4. **Purpose-Driven Semantics:**  
   Colour is never used for mere decoration. Every hue conveys an exact physical or telemetry state:
   - **Aquatic Cyan (`#0284C7` / `#38BDF8`):** Live telemetry, normal water flow, connected link.
   - **Heating Orange (`#EA580C` / `#FB923C`):** Heater demand active and heat output.
   - **Cooling Sky (`#0284C7` / `#38BDF8`):** Chiller/fan actuator demand active.
   - **Safe Emerald (`#059669` / `#10B981`):** Water parameters within target band, safety not tripped.
   - **Warning Amber (`#D97706` / `#FBBF24`):** Near-band thresholds, stale sensor cache, or non-critical alert.
   - **Critical Red (`#DC2626` / `#EF4444`):** Tripped safety, heater stall, hardware failure.
   - **Stale Slate (`#475569` / `#64748B`):** Disconnected hardware, unverified actuator status.
5. **Nocturnal Ergonomics (Night Mode):**  
   Because the display is mounted in a room that goes completely dark at night, night mode is entered automatically when the room goes dark (tank lights off after civil dusk), rather than at fixed clock times. The UI shifts the canvas to deep obsidian black (`#040608`) and dials typography down to a warm, low-luminance amber (`#C28238`), showing "Lights off · tap to wake" in the status pill. Amber wavelengths (>590nm) avoid blue-light melatonin suppression, maintaining healthy sleep cycles.

---

## 2. Complete Colour Tokens (RGB565 Safe)

All values are verified 16-bit hex codes that render without quantization dithering or banding.

### Day Palette (Surfaces & Structural)

| Token Name | Hex Code | RGB565 Equivalent | Usage / Application |
| :--- | :--- | :--- | :--- |
| `SURFACE_CANVAS` | `#0B1015` | `0x0882` | Full screen root background |
| `SURFACE_CARD_1` | `#131B24` | `0x10E4` | Primary tank & strip container fill |
| `SURFACE_CARD_2` | `#19232F` | `0x1926` | Hero temperature block, metric tile fill |
| `SURFACE_CARD_3` | `#16202C` | `0x1105` | Actuator box & auxiliary info fill |
| `SURFACE_BTN_IDLE` | `#1E293B` | `0x1957` | Button idle background |
| `SURFACE_BTN_ACTIVE`| `#212E3D` | `0x2167` | Button touch / active pressed fill |
| `BORDER_SUBTLE` | `#223142` | `0x2188` | Standard 1px card boundary |
| `BORDER_CONTAINER`| `#243447` | `0x21A8` | Internal hero module boundary |
| `BORDER_ACTIVE` | `#334155` | `0x320A` | Button border & selected boundary |

### Semantic Accent Tokens (Day)

| Token Name | Hex Code | Usage / Application |
| :--- | :--- | :--- |
| `ACCENT_CYAN_VIBRANT` | `#38BDF8` | Primary active accent, live text, units |
| `ACCENT_CYAN_DEEP` | `#0284C7` | Primary action button, live link dot |
| `ACCENT_CYAN_BG` | `#0C4A6E` | Flowing status pill background |
| `ACCENT_HEATER_ORANGE`| `#FB923C` | Heater duty bar, active heat text |
| `ACCENT_HEATER_BORDER`| `#EA580C` | Heater active card 1px border |
| `ACCENT_HEATER_BG` | `#261711` | Heater active card fill |
| `ACCENT_GREEN_SAFE` | `#10B981` | Safe metrics, target marker, OK badge |
| `ACCENT_GREEN_BG` | `#0F291E` | Safe pill fill |
| `ACCENT_GREEN_BORDER`| `#059669` | Safe pill 1px border |
| `ACCENT_AMBER_WARN` | `#FBBF24` | Warning status, near-band threshold |
| `ACCENT_AMBER_BG` | `#291B07` | Warning banner fill |
| `ACCENT_AMBER_BORDER`| `#D97706` | Warning banner border |
| `ACCENT_CRIT_RED` | `#EF4444` | Critical alarm text, stall alert, fault |
| `ACCENT_CRIT_BG` | `#2D0E12` | Critical alert container fill |
| `ACCENT_CRIT_BORDER`| `#DC2626` | Critical alert 2px border |
| `STALE_GREY_TEXT` | `#64748B` | Stale cached metric text |
| `STALE_GREY_BORDER` | `#475569` | Stale card solid 1px border |
| `STALE_GREY_BG` | `#0E141B` | Stale card surface fill |

### Night Palette (Low-Luminance Amber / Deep Slate)

| Token Name | Hex Code | Usage / Application |
| :--- | :--- | :--- |
| `NIGHT_CANVAS` | `#040608` | Pitch dark background (zero glare) |
| `NIGHT_CARD_1` | `#080D13` | Deep card container fill |
| `NIGHT_CARD_2` | `#0A1118` | Temperature hero module fill |
| `NIGHT_BORDER` | `#131C26` | Ultra-subtle 1px card boundary |
| `NIGHT_HEADLINE` | `#C28238` | Dimmed warm amber temperature headline |
| `NIGHT_HEADLINE_UNIT`| `#7D5627` | Dimmed amber unit (°F) |
| `NIGHT_TEXT_PRIMARY` | `#8C9CAE` | Secondary metric labels |
| `NIGHT_TEXT_MUTED` | `#506173` | Auxiliary info & timestamps |
| `NIGHT_ACCENT_HEAT` | `#B47834` | Dimmed heater duty accent |
| `NIGHT_ACCENT_SAFE` | `#366B56` | Dimmed safe status pill |

---

## 3. Typography Specification

- **Primary Font Family:** `Plus Jakarta Sans` (Google Fonts), sans-serif.
- **Rendering Setting:** Tabular numerals enabled (`font-variant-numeric: tabular-nums;`) to prevent layout wobble during dynamic updates.

### Scale & Weight Definitions

| Scale Token | Font Size | Weight | Line Height | Usage in LVGL 9 |
| :--- | :--- | :--- | :--- | :--- |
| `TYPE_HERO_XL` | 58 px | 800 (ExtraBold) | 58 px (1.0) | Headline temperature (Home & Details) |
| `TYPE_HERO_LG` | 52 px | 800 (ExtraBold) | 52 px (1.0) | Critical alert headline temp |
| `TYPE_SETPOINT` | 42 px | 800 (ExtraBold) | 42 px (1.0) | Large setpoint touch readout |
| `TYPE_STAT_LG` | 32 px | 800 (ExtraBold) | 36 px (1.1) | TDS / pH in Detail view, RO gal |
| `TYPE_STAT_MD` | 26 px | 800 (ExtraBold) | 30 px (1.15) | TDS / pH in Home view, RO strip |
| `TYPE_TITLE_LG` | 18 px | 800 (ExtraBold) | 22 px (1.2) | Tank card titles, Screen header titles |
| `TYPE_TITLE_MD` | 15 px | 800 (ExtraBold) | 18 px (1.2) | Top bar brand, Water change modes |
| `TYPE_BODY_BOLD` | 13 px | 700 (Bold) | 16 px (1.2) | Button labels, Setpoint control limits |
| `TYPE_BODY_REG` | 12 px | 600 (SemiBold) | 16 px (1.3) | Live status, Target badges, Drift rate |
| `TYPE_MICRO` | 10–11 px | 700 (Bold) | 14 px (1.3) | Sensor tags, Actuator labels, Range ticks |

---

## 4. Layout Grid, Spacing & Geometry

The screen adheres strictly to an absolute **1024 × 600 px** footprint.

```
+-------------------------------------------------------------------------+
| Top System Bar (Height: 46 px, Padding: 0 4px)                          |
+------------------------------------+------------------------------------+
| Left Tank Card: 75 Gallon          | Right Tank Card: Nano              |
| Width: 492 px, Height: 416 px      | Width: 492 px, Height: 416 px      |
| Gap: 12 px                         | Gap: 12 px                         |
+------------------------------------+------------------------------------+
| Compact Flow Strip (Height: 108 px)                                     |
| [RO Filter: 344px]   [Water Change Meter: 388px]   [Home Assistant: 252px] |
+-------------------------------------------------------------------------+
```

### Corner Radii Scale
- `RADIUS_CONTAINER_LG`: **14 px** (Outer tank cards, primary workspace panels)
- `RADIUS_CARD_MD`: **12 px** (Chart card, Bottom strip cards)
- `RADIUS_MODULE_SM`: **10 px** (Temperature hero container, Setpoint box)
- `RADIUS_CONTROL_XS`: **8 px** (Buttons, Mode toggles, Actuator boxes)
- `RADIUS_PILL`: **20 px** (Status badges, connection indicators)

### Minimum Touch Dimensions
- Standard touch buttons: **Min 56 × 56 px** (Setpoint `[-]` and `[+]`).
- Bar-style action buttons: **Min 56 px height** (Adaptive Learning toggle, Mode switches, Water Change actions).
- Detail navigation links: **38 px height** with generous 14 px lateral padding.

---

## 5. LVGL 9 Component Specifications

### 5.1 Tank Card (`lv_obj`)
- **LVGL Base:** `lv_obj_create(parent)`
- **Dimensions:** Width `492 px`, Height `416 px`
- **Styles:**
  - `bg_color`: `lv_color_hex(0x131B24)`
  - `border_color`: `lv_color_hex(0x223142)`, `border_width`: `1 px`
  - `radius`: `14 px`
  - `pad_all`: `14 px`
  - `layout`: `LV_LAYOUT_FLEX`, column direction with `LV_FLEX_ALIGN_SPACE_BETWEEN`

### 5.2 Glanceable Temperature Hero (`lv_obj` + `lv_label`)
- **LVGL Base:** `lv_obj_create(tank_card)`
- **Styles:**
  - `bg_color`: `lv_color_hex(0x19232F)`
  - `border_color`: `lv_color_hex(0x243447)`, `border_width`: `1 px`
  - `radius`: `10 px`
  - `pad_all`: `12 px`
- **Temperature Label:**
  - `text_font`: Custom Montserrat / Plus Jakarta Sans 58px font asset
  - `text_color`: `lv_color_hex(0xF8FAFC)`
- **Probes Readout:** Dual labels showing `A: 74.9°`, `B: 75.1°` with gradient badge `Δ -0.2°F` (`lv_color_hex(0x38BDF8)`).

### 5.3 Setpoint Control (`lv_obj` + `lv_btn`)
- **LVGL Base:** Container with 3 child widgets:
  1. **Decrement Button:** `lv_btn_create()`, size `56 × 56 px`, `radius: 8px`, `bg_color: 0x212E3D`, icon `mdi-minus`.
  2. **Readout Container:** Center aligned, 42px font `75.0`, sub-label `Swing: ±0.5 °F (74.5° - 75.5°)`.
  3. **Increment Button:** `lv_btn_create()`, size `56 × 56 px`, `radius: 8px`, `bg_color: 0x212E3D`, icon `mdi-plus`.
- **Target Value:** `75.0 °F` (adjusts in 0.1 °F steps via ESPHome number component).

### 5.4 Thermal Actuator Bars (`lv_bar`)
- **LVGL Base:** `lv_bar_create(parent)`
- **Dimensions:** Width `48 px` (Home) / `80 px` (Detail), Height `8 px`
- **Styles:**
  - `bg_color`: `lv_color_hex(0x0F172A)`
  - `indicator_bg_color`: `lv_color_hex(0xFB923C)` (Heater) / `lv_color_hex(0x38BDF8)` (Fan)
  - `radius`: `4 px`

### 5.5 Target Range Bar (`lv_bar` with custom marker)
- **LVGL Base:** Stacked container or `lv_bar` with segmented drawing:
  - Base track: Width 100%, Height `6 px`, `bg_color: 0x0F172A`.
  - Target zone: Positioned absolutely from target min to max, `bg_color: 0x064E3B`, 1px borders `0x059669`.
  - Current value marker: Width `4 px`, Height `6 px`, `bg_color: 0x10B981`.

### 5.6 24-Hour History Chart (`lv_line` series)
- **LVGL Base:** ESPHome's LVGL has no chart widget, so the plot is an `lv_obj` (`bg_color: 0x0B1015`, 1 px `0x223142` border, radius 8) holding `lv_line` series whose points are recomputed from the panel's own 24 h history (96 samples, one per 15 min).
- **Dimensions:** Plot `532 × 170 px` inside a `608 × 266 px` card; Y-axis labels left of the plot, X labels (`-24 h … Now`) below it.
- **Grid:** 5 horizontal 1 px lines, `0x223142`. Tabs above the plot switch the series: Temperature / TDS / pH.
- **Series (solid lines only, no area fill):**
  1. Setpoint: thin solid horizontal line, width 1 px, `0x059669`.
  2. Probe A (or the single probe): solid, width 3 px, `0x38BDF8`.
  3. Probe B (75 Gallon only): solid, width 2 px, `0x0284C7`.
- **Empty state:** until two samples exist the plot reads "Collecting history (one point every 15 min)".

### 5.7 Water Change Arc Gauge (`lv_arc`)
- **LVGL Base:** `lv_arc_create(parent)`
- **Dimensions:** Width `220 px`, Height `120 px`
- **Angles:** 180° semi-circle (from 180° to 0°).
- **Track Thickness:** `16 px`
- **Track Colour:** `lv_color_hex(0x1E293B)`
- **Indicator Colour:** `lv_color_hex(0xFB923C)` (Draining) / `lv_color_hex(0x0284C7)` (Refilling)
- **Center Label:** Displays `29.4%` (18.2 gal / 62 gal).

### 5.8 Alert Banner & Critical Tank State
- **Container:** `820 × 48 px` at the top of the home screen, over the brand and status pill (the clock stays visible). Critical: `bg_color: 0x2D0E12`, border `0xDC2626`. Warning: `bg_color: 0x291B07`, border `0xD97706`.
- **Icon:** `mdi-alert-octagon`, red (critical) or amber (warning).
- **Text:** Title (15 px) and message (12 px) exactly as Home Assistant's alert sent them, e.g. "75 Gallon: heater not responding" / "Heater on at 100 % but water is falling 0.15 °F/min. Check the heater and its power."
- **Action:** one button, `OPEN 75 GALLON` / `OPEN NANO`, that goes to that tank's detail screen. No silence or diagnose actions.
- **Critical tank card:** border `2 px 0xEF4444`, hero fill `0x2D0E12` with `0xDC2626` border, temperature in red; the heater tile reads `HEATER (NOT HEATING)` in red when demand is 100 % and the water is falling.

### 5.9 Offline / Stale State
- **Card:** solid 1 px border `0x475569` (no dashed borders), fill `0x0E141B`.
- **Header:** the tag pill is replaced by an amber `STALE 4m` pill; the link line reads "Link lost · values from 14:35:10" in `0xFBBF24`.
- **Temperature:** `0x64748B` with strikethrough (`LV_TEXT_DECOR_STRIKETHROUGH`).
- **Actuators:** `-- (unknown)` in amber; TDS/pH targets read `CACHED`.
- **No button:** the Bluetooth link reconnects by itself.

### 5.10 Night Mode
- **Trigger:** the sun is below civil twilight (-6°) **and** the 75's tank light reads off, and the screen has not been touched for 60 s. Any touch wakes it; that first touch is absorbed so it never presses a button.
- **Look:** backlight 10 %, canvas `0x040608`, cards `0x080D13`, temperatures `0xC28238` with `0x7D5627` units, text `0x8C9CAE`. The status pill reads "Lights off · tap to wake" style copy only in the mockup; on the device the pill keeps its live status in dim colours.

## 6. Summary of Key Design Decisions

1. **Dual Column Split (492 px + 492 px):**  
   Treating both aquariums as equal primary peers on the dashboard creates symmetrical visual balance while giving each tank enough width to render a giant 58px temperature readout alongside full dual-probe and actuator data.
2. **Dedicated Bottom Water-Flow Strip (108 px):**  
   Water changes and RO filtration are critical ongoing maintenance tasks that don't belong hidden behind a menu. The bottom strip keeps the RO batch fill volume and hose meter ready to start at any moment.
3. **RGB565 Anti-Banding Architecture:**  
   By enforcing crisp 1px borders and high-contrast solid card fills instead of large gradients, the CrowPanel IPS display delivers razor-sharp clarity without colour quantization steps.
4. **Physically Unmistakable Stale Data:**  
   In aquatic monitoring, acting on stale data can be fatal to livestock. The stale state uses strike-through styling, a grey card frame, an amber STALE pill and the time the values are from, so old sensor readings can never be confused with live telemetry.
5. **Circadian Night Theme:**  
   The night mode shifts the color spectrum entirely away from blue/white light toward warm amber at 10% backlight, ensuring the monitor provides passive peace of mind in the home office without disturbing sleep.
