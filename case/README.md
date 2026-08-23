# Enclosure

Purpose-built for the **LAFVIN ESP32-C6 1.47" LCD** board, because nothing
off the shelf fits it.

The Waveshare-outline cases and the generic MakerWorld ESP32-C6 enclosure
both fail: they assume a board with the LCD centred and USB on a long edge.
This board is a stick — USB-C, BOOT and RESET are all crammed onto one short
end, with the glass filling the far two-thirds.

## Print this first

`tank-monitor-fittest.stl` — a 10 mm slice through the USB end. About three
minutes. It tells you whether the pocket and the USB slot are right before
you spend an hour on the real thing.

LAFVIN publishes no mechanical drawing, so the dimensions here were scaled
off photographs and are good to roughly **±1 mm**. If the coupon is tight or
sloppy, adjust `pcb_l` / `pcb_w` / `back_h` at the top of the `.scad` and
re-render.

## Then

| File | Notes |
|---|---|
| `tank-monitor-tray.stl` | print open-side up, no supports |
| `tank-monitor-lid.stl` | print face down, no supports |

**PETG, not PLA.** This sits above a warm, humid tank and PLA creeps.

0.2 mm layers, 3 perimeters, 20% infill. No supports needed on either part —
that's what the geometry was arranged for.

## Design choices that absorb the ±1 mm

- **USB-C is a full-width slot**, not a shaped port cutout. There is no
  alignment to get wrong.
- **The LCD window is cut 1 mm inside the glass** on every side, so the
  bezel laps over the edge and hides any positional error.
- **No BOOT/RESET holes.** Their positions are the least certain thing on
  the board, and once OTA works you never press them. If you need them,
  the lid pulls off.
- **0.4 mm clearance per side** around the PCB.

## Cable exit

The GPIO headers run down **both long edges** of this board, so wires leave
from both sides — not off the end. There's a 26 × 5 mm slot on each long
side, positioned over the header rows. Every stock case assumes USB and
nothing else, which is the other reason none of them work here.

## Changing dimensions

Everything is parametric. Edit the `BOARD` block at the top of
`tank-monitor-case.scad`, then:

```sh
openscad -o tank-monitor-tray.stl -D 'part="tray"' tank-monitor-case.scad
openscad -o tank-monitor-lid.stl  -D 'part="lid"'  tank-monitor-case.scad
```

`part` accepts `tray`, `lid`, `fittest`, or `all` (everything laid out on
one plate).
