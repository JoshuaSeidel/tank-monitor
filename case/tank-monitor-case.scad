// Tank Monitor enclosure -- LAFVIN ESP32-C6 1.47" LCD board
//
// LAFVIN publishes no mechanical drawing and the Waveshare-outline cases
// do not fit this board, so these dimensions come from photographs and
// are good to roughly +/-1mm. The design is built to tolerate that:
//
//   * USB-C is a full-width slot, not a shaped port -- nothing to misalign
//   * the LCD window is cut inside the glass edge, so the bezel hides error
//   * BOOT/RESET get no holes at all (see note below)
//
// Before printing the whole thing, set part="fittest" and print that. It
// is a 10mm slice of the pocket and the USB end -- about 3 minutes -- and
// tells you whether pcb_l/pcb_w/depth are right.

part = "all";   // "all" | "tray" | "lid" | "fittest"

/* [BOARD -- replace with caliper readings if you get them] */
pcb_l = 51.0;     // long dimension, USB end to far end
pcb_w = 23.0;     // short dimension
pcb_t = 1.6;      // bare PCB thickness

back_h  = 4.0;    // tallest component on the BACK
front_h = 2.5;    // glass + ribbon height above the PCB front

// The glass runs from the far end back toward the USB end and is very
// nearly the full board width.
lcd_l      = 33.0;   // glass length along pcb_l
lcd_w      = 21.0;   // glass width along pcb_w
lcd_gap    = 1.0;    // glass inset from the FAR end
lcd_off_w  = 1.0;    // glass inset from one long edge

/* [FIT] */
clearance = 0.4;    // per side around the PCB
wall      = 2.0;
floor_t   = 1.6;
bezel_t   = 1.6;
overlap   = 1.0;    // how far the bezel laps over the glass

/* [CABLE EXIT] */
// The GPIO headers run down BOTH long edges of this board, so wires leave
// from both sides -- not off the end. Slots on each long side, positioned
// over the header rows.
cable_w = 26.0;   // slot length, along pcb_l
cable_h = 5.0;

eps = 0.01;
$fn = 40;

// ---- derived ----------------------------------------------------------
in_l   = pcb_l + 2 * clearance;
in_w   = pcb_w + 2 * clearance;
out_l  = in_l + 2 * wall;
out_w  = in_w + 2 * wall;
tray_h = floor_t + back_h + pcb_t;
skirt  = front_h + 0.4;

module rrect(l, w, h, r = 2.5) {
  hull() for (x = [r, l - r], y = [r, w - r]) translate([x, y, 0]) cylinder(r = r, h = h);
}

// USB end is at x = 0. Full-width slot: no alignment to get wrong.
module usb_slot() {
  translate([-eps, wall + 2, floor_t + back_h + pcb_t - 3.6])
    cube([wall + 2 * eps, in_w - 4, 3.8]);
}

module cable_slot() {
  // Both long edges, centred on the header rows.
  for (y = [-eps, out_w - wall + eps])
    translate([(out_l - cable_w) / 2 + 4, y, tray_h - cable_h])
      cube([cable_w, wall + 2 * eps, cable_h + eps]);
}

module tray() {
  difference() {
    rrect(out_l, out_w, tray_h);
    translate([wall, wall, floor_t]) cube([in_l, in_w, tray_h]);
    usb_slot();
    cable_slot();
    // Vents -- this hangs above a warm, humid tank
    for (i = [-1, 1], j = [0 : 4])
      translate([out_l / 2 - 16 + j * 8,
                 out_w / 2 + i * (out_w / 2 - wall / 2), floor_t / 2])
        cube([5, 2.4, floor_t * 3], center = true);
  }
  // Posts that stop the board sliding, all below board level
  for (x = [wall + 1.4, out_l - wall - 1.4], y = [wall + 1.4, out_w - wall - 1.4])
    translate([x, y, floor_t]) cylinder(r = 1.1, h = back_h);
}

module lid() {
  // Window sits INSIDE the glass by `overlap` on every side, so a 1mm
  // error in the glass position is still covered by bezel.
  win_l = lcd_l - 2 * overlap;
  win_w = lcd_w - 2 * overlap;
  win_x = wall + clearance + (pcb_l - lcd_gap - lcd_l) + overlap;
  win_y = wall + clearance + lcd_off_w + overlap;

  difference() {
    union() {
      rrect(out_l, out_w, bezel_t);
      difference() {
        translate([0, 0, bezel_t]) rrect(out_l, out_w, skirt);
        translate([wall - 0.2, wall - 0.2, bezel_t - eps])
          cube([in_l + 0.4, in_w + 0.4, skirt + 2 * eps]);
      }
    }
    translate([win_x, win_y, -eps]) cube([win_l, win_w, bezel_t + 2 * eps]);
    // The USB slot continues through the skirt
    translate([-eps, wall + 2, bezel_t - eps]) cube([wall + 2 * eps, in_w - 4, skirt]);
    for (y = [-eps, out_w - wall + eps])
      translate([(out_l - cable_w) / 2 + 4, y, bezel_t - eps])
        cube([cable_w, wall + 2 * eps, skirt]);
  }
}

// A 10mm slice through the USB end. Print this first.
module fittest() {
  intersection() {
    tray();
    cube([12, out_w, tray_h]);
  }
}

if (part == "tray") tray();
else if (part == "lid") lid();
else if (part == "fittest") fittest();
else {
  tray();
  translate([0, out_w + 4, 0]) lid();
  translate([0, 2 * out_w + 8, 0]) fittest();
}
