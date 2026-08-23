# Enclosure

Purpose-built for the **LAFVIN ESP32-C6 1.47" LCD** board, because nothing
off the shelf fits it.

The Waveshare-outline cases and the generic MakerWorld ESP32-C6 enclosure
both fail: they assume a board with the LCD centred and USB on a long edge.
This board is a stick — USB-C, BOOT and RESET are all crammed onto one short
end, with the glass filling the far two-thirds.

## Print this first: the fit gauge

`fit-gauge.stl` — six pockets, **21.0 to 23.5 mm in 0.5 mm steps**, each
stamped with its size. About five minutes, no supports.

Slide the board into each. The one that grips lightly without needing force
is your real board width. Put that number in `pcb_w` at the top of
`tank-monitor-case.scad` and re-render — the case is then correct by
measurement instead of by estimate.

This exists because the first coupon came out too loose. The board
dimensions here were scaled off photographs, and no amount of re-measuring
the same photographs fixes that. The gauge answers it directly.

## Then the coupon

`tank-monitor-fittest.stl` — a 10 mm slice through the **USB end**. Print it
after setting `pcb_w` from the gauge. It checks the two things the gauge
can't: that a USB-C plug reaches the port through the slot, and that the
walls clear BOOT and RESET.

Slide it onto the USB end, not the far end — the port cutout is in its end
wall.

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
