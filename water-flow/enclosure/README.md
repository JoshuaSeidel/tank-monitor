# Printed enclosures for the flow meters

Two PETG boxes, one per unit, designed to use as little filament as the job
allows: thin walls (1.7-1.8 mm = 4 perimeters), no solid blocks, no
supports, everything printed flat in the orientation the STL is exported in.

| Unit | Box | Outside size | Parts |
|---|---|---|---|
| `water-flow-ro` | splash-resistant, 2 screws | 59 × 49 × 15 mm (68 × 71 with screw ears and mounting tabs) | `ro-body`, `ro-lid` |
| `water-flow-change` | **sealed**: O-ring cord gasket, 4 screws, switch + PG7 gland the only openings | 75 × 54 × 37 mm over the rim band (82 × 61 with screw ears, 92 long with the hanging tab) | `change-body`, `change-lid`, `change-hook` (optional) |

| File | What it is |
|---|---|
| `water-flow-ro.scad` | RO box, parametric |
| `water-flow-change.scad` | change box, parametric |
| `common.scad` | shared helpers |
| `stl/*.stl` | the exported parts, already in print orientation |

## Filament and print time

OrcaSlicer 2.3 estimates. PETG, 0.4 mm nozzle, 0.2 mm layers, 4 walls, 5
top / 5 bottom layers, 15 % gyroid, no supports, no brim. Infill hardly
matters here: the walls are all perimeter, and the floors and lids are
solid top/bottom layers. Times are at moderate PETG speeds (80 mm/s outer
wall), so a fast printer will be quicker.

| Part | PETG | Time |
|---|---|---|
| `ro-body` | 11.2 g | 1 h 21 m |
| `ro-lid` | 5.1 g | 37 m |
| **RO total** | **16.3 g** | **~2 h** |
| `change-body` | 24.8 g | 3 h 04 m |
| `change-lid` | 17.5 g | 2 h 10 m |
| `change-hook` (optional) | 1.8 g | 12 m |
| **Change total** | **44.1 g** | **~5 h 25 m** |
| **Both units** | **~60 g** | **~7 h 30 m** |

## Print settings

* **PETG**, 0.4 mm nozzle, **0.2 mm** layers.
* **4 perimeters** (walls). The walls are 1.7 / 1.8 mm on purpose, so they
  come out as solid perimeters with no infill gap in them. Do not drop to 2.
* **5 top / 5 bottom** layers. The change box floor is 1.4 mm (7 layers) and
  its lid 1.2 mm (6 layers), solid all through, so they are watertight.
* Infill 15 % gyroid. Only the screw columns and ears get any.
* **No supports.** Every overhang is 45° or less, as a chamfer or cone.
  Two features are bridges: the USB-C opening in the RO box (13 mm) and the
  PCB beam in the change box (27 mm across the electronics bay). Both are
  fine in PETG with bridge fan at 100 %.
* No brim needed. Use glue stick or a textured PEI sheet so PETG releases
  cleanly from smooth PEI.
* Orientation: as exported. Bodies print floor-down. Lids print outside
  face down, with the lip, fingers, rib and tongue pointing up. The hook
  prints flat.
* For the change box, use **natural / translucent PETG** if you want the
  blue LED to show through the lid (see [LED](#led)). Any colour works
  otherwise.

## Hardware

**RO unit**

| Qty | Part |
|---|---|
| 2 | M3 × 8 self-tapping screws for plastics (pan head). They go into 2.5 mm pilot holes. For M3 heat-set inserts instead, set `screw_pilot = 4.0` and use M3 × 8 machine screws |
| 1 | small zip tie, ≤ 4 mm wide: strain relief for the sensor lead |
| 2 | zip ties (3.6 mm) or M3 / #6 screws: mounting through the two tabs |
| - | double-sided foam tape, to stick the boost module and divider down |

**Change unit**

| Qty | Part |
|---|---|
| 4 | **M3 heat-set inserts**, short (M3 × 5.7, ~4.6 mm OD). The holes are 4.0 mm, 6.5 mm deep |
| 4 | **M3 × 10 countersunk** screws (ISO 10642 / DIN 7991), stainless |
| ~230 mm | **2 mm solid silicone O-ring cord** (gasket). Or neutral-cure RTV silicone, see step 7 |
| 1 | **PG7 nylon cable gland** (12.5 mm thread, 3-6.5 mm cable) |
| 1 | 12 mm IP67 latching push-button (from the [parts list](../README.md#change-unit----water-flow-change-sealed)) |
| - | **foam pad**: 1.5 mm EVA or neoprene sheet (floor 59 × 13 mm, two sides 56 × 20 mm, one end 13 × 20 mm) and a **2 mm strip** 47 × 10 mm for the top of the cell |
| - | double-sided foam tape for the boost module and divider |
| ~3 cm | 4-5 mm adhesive-lined heat shrink, if the sensor lead is loose wires (see step 4) |
| 1 | optional: hook or S-hook. The printed `change-hook` fits the tab's 8 mm hole |

## Assembly: RO unit

Looking into the box with the **USB-C wall toward you**: the board goes
against the **right** wall, and the boost module and divider go in the bay
on the left. The sensor lead leaves through the far wall, on the bay side.

1. **Boost module and divider.** Put the boost module flat on the floor in
   the bay, near the USB-C end, and the divider beside it. Stick both down
   with foam tape. Meter the boost output first (5.0 V, see the main
   README).
2. **Sensor lead.** Pass the lead through the 5.5 mm hole in the far wall.
   Cut the plug off and re-terminate if it won't fit through. Lay the lead
   over the small bridge just inside the hole, and pull a zip tie through
   the tunnel under the bridge and round the lead. Tighten it: a tug on the
   cable now pulls on the bridge, not on the solder joints.
3. **Board.** Hold it top side up. Tilt the USB-C end down into the wall
   opening, then lower the antenna end onto its ledge. Two narrow ledges
   carry the PCB at the middle of each short end, clear of the header rows.
   The wall and two small posts locate it sideways.
4. **Lid.** One finger presses the antenna end and the other the top of the
   USB-C shell, so the board can't lift when a cable is pulled. The LED
   hole sits over the blue LED. A 3 mm stub of clear filament pushed in
   from inside makes a light pipe. Fit the 2 screws.
5. **Mount.** Run zip ties through the two side tabs around the RO frame or
   a tube, or screw the tabs to a panel. Keep the USB-C end clear for the
   cable.

## Assembly: change unit (sealed)

Looking into the box with the **switch end toward you**: the cell stands on
its long edge in the padded bay along the **right** wall. The electronics
bay is on the left, with the switch at the near end and the gland at the
far end. The board sits just **above the rim**, over the electronics bay,
with its USB-C toward you.

1. **Clean the holes.** Round horizontal holes can sag a little at the top
   when printed. Deburr the switch and gland holes. Both seal on the flat
   outside face, not in the bore.
2. **Inserts.** Press the 4 M3 inserts into the body's corner ears with a
   soldering iron (~220 °C for PETG). Keep them square and flush.
3. **Switch.** From outside, with its O-ring **outside** under the head.
   Fit the nut inside, a **flat facing the floor** (the height is set for
   that), and tighten firmly. Its body and terminals point along the
   electronics bay. A latching button gets no turning force in use, so it
   needs no anti-rotation flat.
4. **Gland.** Put the PG7 through the far-end hole from outside. Fit the
   lock nut inside, again flat to the floor. The gland seals only on a
   round cable. If the YF-S201 lead is three loose wires, shrink a 3 cm
   piece of adhesive-lined heat shrink over them where they pass through
   the gland, or splice in a short round 3-core cable. Leave the dome nut
   loose until the wiring is done, then tighten it hard.
5. **Cell.** Line the bay with the 1.5 mm foam: floor, both faces, and the
   far end. Stand the cell in it on its long edge, with the protection-board
   end at the switch end. The lead goes up through the notch at the
   switch-end top of the partition, to the board's JST socket. No sharp
   edge touches the cell. The lid rib presses the 2 mm foam strip on top of
   the cell, so it can't move with the lid on.
6. **Boost and divider.** Stand the boost module on its long edge against
   the partition (electronics side), between the switch nut and the gland
   nut. Put the divider on the floor beside it. Use foam tape, and keep the
   wiring clear of the space above the rim.
7. **Board.** Drop the antenna end onto the corbel on the gland wall,
   behind its little stop. Then lower the USB-C end onto the beam across
   the bay, between the two corner stops. Plug in the battery, **after the
   polarity check in the main README**.
8. **Gasket.** Press the 2 mm cord into the groove all round, without
   stretching it. Cut it so the ends butt on a long straight side, and join
   them with a drop of CA glue. A smear of silicone grease helps it seal and
   last. Alternative: a formed-in-place gasket. Run a bead of neutral-cure
   RTV silicone in the groove, put the lid on over cling film, snug the
   screws lightly, and let it cure 24 h. Then remove the film. The gasket
   stays in the body.
9. **Lid.** Put the 2 mm foam strip on top of the cell. Fit the lid (its
   tongue goes into the groove) and tighten the 4 countersunk screws
   crosswise, a little at a time, until the lid's band meets the body rim
   all the way round. Then stop. The tongue limits the squeeze to ~30 %,
   so more torque does nothing but strip the inserts.
10. **Leak test, once,** before trusting it near the tank. Close the box
    with a dry tissue inside and the battery out. Plug the gland with its
    cable, or a 5 mm rod. Hold it under water for a minute, then open it
    and check the tissue.

**Charging.** Undo the 4 screws and lift the lid. The USB-C cable plugs in
horizontally **over the rim** at the switch end: the board sits 1.5 mm
above the rim, so the plug's moulding clears it. Switch **ON** to charge
(the switch is between the cell and the charger, see the main README). Wipe
the box dry before you open it.

**Hanging.** The flat tab at the switch end has an 8 mm hole. Hang it from
a hook, or from the Brute with `change-hook`: its big U goes over the rim
or handle and its small U through the tab. Hung like that, the switch is at
the top and the cable gland points down, so give the sensor cable a drip
loop below the gland. The lid band overhangs the body band by 0.8 mm as a
drip edge, so water running down the lid falls clear of the seam.

### LED

The change box keeps no hole for the blue LED. The lid is thinned to a
**0.6 mm skin** (3 layers, still solid and sealed) in a 6 mm spot over the
LED. Printed in natural or translucent PETG, the LED blinking until online
is clearly visible through it. In an opaque dark colour it won't show, and
nothing else changes: online/offline status is in Home Assistant either
way. Setting `led_skin = 0` makes it a through hole, which **breaks the
seal**, so don't do that on this unit. The spot only works if `led_x` /
`led_y` are measured (below).

## Measure and set

Most of these are not in any datasheet for these exact parts. The defaults
are generous: measure your part, set the value at the top of the `.scad`,
and re-export. To export a part:

```
openscad -D 'part="body"' -o stl/change-body.stl water-flow-change.scad
```

Use `part = "fit"` to preview the boxes with stand-ins for the parts inside.
`part = "clash"` renders their overlap with the box: only face contact (a
PCB resting on its ledge) and the USB-C plug crossing the closed lid should
show up.

"Left" and "right" below are with the **board top side up and its USB-C end
toward you**.

| Parameter | File | Default | What to measure |
|---|---|---|---|
| `pcb_l`, `pcb_w` | both | 49.5, 25.8 | board outline. Published: 49.2 × 25.5 |
| `pcb_t` | both | 1.6 | PCB thickness (some clones are 1.2) |
| `usb_off_y` | both | 0 | USB-C centre relative to the board's width centre, + = left |
| `usbc_h` | both | 3.3 | USB-C receptacle height above the PCB |
| `plug_w`, `plug_h` | RO | 12.5, 7.0 | your USB-C cable's moulded plug body, width × height |
| `led_x`, `led_y` | both | 9, 5 | blue LED (GPIO22): distance from the USB-C end edge, and from the **right** edge (RO) / **left** edge (change). **Not verified -- measure** |
| `pcb_under` | RO | 3.5 | space under the PCB for solder tails / wires on the back |
| `top_clear` | RO | 7.5 | tallest part on top of the board + wire bends |
| `jst_h` | change | 6.0 | JST-PH battery socket height above the PCB |
| `jst_clear` | change | 12 | room between the board's USB-C end and the switch wall for the battery plug and its lead bend |
| `boost_l`, `boost_w`, `boost_h` | both | 25.5, 18, 6 | boost module. The no-USB version is ~25.2 × 17.6 × 5.9. The **USB-A version is ~32.5 × 17.6 × 8.3**: desolder the USB-A socket (it isn't used), or set 33 / 18 / 8.5 (the RO box grows ~7 mm) |
| `div_l`, `div_w`, `div_h` | RO | 20, 15, 8 | divider perfboard (or wire it inline in heat shrink and ignore this) |
| `cable_d` | RO | 5.0 | sensor lead diameter (sheath, or the bundle of 3 wires) |
| `batt_l`, `batt_t`, `batt_h` | change | 56, 10.5, 20.5 | cell including protection board and lead fold |
| `sw_depth` | change | 26 | switch: body + terminals + soldered wires behind the panel |
| `sw_nut_af`, `sw_head_d` | change | 16, 15 | switch nut across flats; head / O-ring outside diameter |
| `gl_nut_af`, `gl_hex_af` | change | 18, 15 | PG7 lock nut and body hex across flats |
| `insert_d` | change | 4.0 | heat-set insert hole: follow the insert maker's figure |
| `cord_d`, `groove_d`, `tongue_h` | change | 2.0, 1.8, 0.4 | gasket. For a 1.5 mm cord: `groove_w` 2.0, `groove_d` 1.3, `tongue_h` 0.25 |
| `hook_gap` | change | 12 | opening of the hook's big U: Brute rim lip or handle thickness + ~2 mm |

## What is not verified

* The LOLIN32 Lite clone has **no mounting holes**. The board is held at its
  two short ends: ledges under the end strips (centre 10-12 mm only, clear
  of the header rows), with the lid pressing it down at the antenna end and
  on the USB-C shell. This assumes ~2 mm of bare PCB at each end, under the
  centre. Check your board.
* The **LED position** on this clone is unknown. It defaults to a guess.
* The JST socket is assumed to be side-entry at the USB-C end, as on the
  LOLIN32 Lite. That is why the change unit leaves `jst_clear` in front of
  the board.
* Boost module, switch and gland dimensions are typical values, not
  measured parts.
* Filament and time figures are OrcaSlicer estimates, not printed parts.
  Kiln's printability check flags the exact-45° chamfers and the 27 mm
  bridge as "needs supports". Both print without supports in PETG.
