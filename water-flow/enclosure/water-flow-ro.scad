// water-flow-ro.scad -- enclosure for the RO flow meter (water-flow-ro).
//
// Dry location, USB-C wall power, no battery. Box + flat lid, 2 x M3
// self-tapping screws (or M3 heat-set inserts), USB-C cut-out on the board's
// port, sensor-lead hole with zip-tie strain relief, LED hole in the lid,
// two flat mounting tabs (screw or zip tie).
//
// PRINT (PETG, 0.2 mm layers, 4 walls, no supports):
//   ro-body : as exported -- floor on the bed, opening up.
//   ro-lid  : as exported -- outside face on the bed, lip and fingers up.
//
// Render one part:  openscad -D 'part="body"' -o stl/ro-body.stl water-flow-ro.scad
//                   openscad -D 'part="lid"'  -o stl/ro-lid.stl  water-flow-ro.scad
//   part = "assembly" shows both in place (lid lifted by `explode`).

include <common.scad>

part    = "assembly";   // "body" | "lid" | "assembly"
explode = 12;
$fn     = 48;

/* ---------- print / shell ---------- */
wall    = 1.7;   // 4 perimeters at 0.42 mm line width
floor_t = 1.2;   // 6 layers at 0.2 mm
lid_t   = 1.2;
r_in    = 1.5;   // interior corner radius
clr     = 0.25;  // fit clearance lid lip <-> wall

/* ---------- MEASURE AND SET: AITRIP ESP32 Lite V1.0.0 ---------- */
pcb_l     = 49.5;  // published 49.2 x 25.5
pcb_w     = 25.8;
pcb_t     = 1.6;   // measure (some clones are 1.2)
pcb_under = 3.5;   // free space under the PCB: solder tails / wires on the back
top_clear = 7.5;   // above the PCB top: tallest part (JST-PH socket ~6) + wire bends
usb_off_y = 0;     // USB-C centre, offset from the PCB's width centre (+ = to your left, USB-C end toward you)
usbc_h    = 3.3;   // USB-C receptacle height above the PCB
plug_w    = 12.5;  // USB-C plug overmould (cable end) width  -- measure your cable
plug_h    = 7.0;   //                                height
plug_clr  = 0.6;
led_x     = 9.0;   // blue LED (GPIO22) from the PCB's USB-end edge  -- measure
led_y     = 5.0;   //                    from the PCB's RIGHT long edge (USB-C toward you) -- measure
led_d     = 3.0;   // through-hole in the lid; a 3 mm clear-filament stub makes a light pipe
gap       = 0.3;   // PCB-to-wall clearance
ledge_d   = 2.0;   // how far the end ledges run under the PCB
ledge_w   = 10;    // ledge width, centred on the PCB (keeps clear of the header rows)

/* ---------- MEASURE AND SET: boost module + divider ---------- */
boost_l = 25.5;    // no-USB version 25.2 x 17.6 x 5.9. USB-A version is 32.5 x 17.6 x 8.3:
boost_w = 18.0;    //   set 33 / 18 / 8.5, or desolder the USB-A socket
boost_h = 6.0;
div_l   = 20;      // perfboard with the 10k/20k divider (or leave it inline in heat shrink)
div_w   = 15;
div_h   = 8;

/* ---------- MEASURE AND SET: sensor lead ---------- */
cable_d = 5.0;     // uxcell lead: sheath (or bundle of 3 wires) diameter

/* ---------- mounting ---------- */
screw_pilot = 2.5; // M3 self-tapping into PETG. For M3 heat-set inserts use 4.0
screw_clear = 3.4;
ear_d       = 7.5;
ear_h       = 6.0;
tab_len     = 11;  // mounting tabs on both long sides
tab_w       = 14;
tab_t       = 2.0;
tab_slot_w  = 4.0; // fits a 3.6 mm zip tie or an M3/#6 screw
tab_slot_l  = 6.5;

/* ---------- derived ---------- */
anchor_l = 6;                                       // zip-tie anchor footprint (x)
anchor_h = 4.2;                                     // its height; the lead lies on top of it
cable_z  = anchor_h + cable_d / 2 + 0.3;            // lead hole centre above the inner floor
bay_w = max(boost_w, div_w) + 1;
IX = max(pcb_l + 2 * gap, boost_l + div_l + anchor_l + 4);
IY = pcb_w + 2 * gap + bay_w;
IZ = max(pcb_under + pcb_t + top_clear, boost_h + 4, div_h + 3, cable_z + cable_d / 2 + 2.5);
OX = IX + 2 * wall; OY = IY + 2 * wall;
pcb_x0 = gap; pcb_y0 = gap;                         // USB end at x = 0
pcb_z0 = pcb_under;
usb_y  = pcb_y0 + pcb_w / 2 + usb_off_y;
usb_z  = pcb_z0 + pcb_t + usbc_h / 2;
bay_y0 = pcb_y0 + pcb_w + gap;
bay_yc = bay_y0 + bay_w / 2;
// screw ears on two diagonal corners, outside the walls
ears = [[[-wall - 1.0, -wall - 1.0], [-wall + 1.3, -wall + 1.3]],
        [[IX + wall + 1.0, IY + wall + 1.0], [IX + wall - 1.3, IY + wall - 1.3]]];

echo(str("RO outer box (no tabs/ears): ", OX, " x ", OY, " x ", floor_t + IZ + lid_t, " mm"));

module body() {
    difference() {
        union() {
            // shell
            translate([0, 0, -floor_t]) linear_extrude(floor_t + IZ) outline([IX, IY], r_in, wall);
            // screw ears
            for (e = ears) ear(e[0], e[1], IZ - ear_h, ear_d, ear_h);
            // mounting tabs, flush with the bottom
            for (s = [0, 1])
                translate([IX / 2, s ? IY + wall - 0.5 : -wall + 0.5, -floor_t])
                    rotate([0, 0, s ? 90 : -90]) slot_tab(tab_len + 0.5, tab_w, tab_t, tab_slot_w, tab_slot_l);
        }
        // cavity
        linear_extrude(IZ + 1) rrect([IX, IY], r_in);
        // USB-C plug opening in the x = 0 wall
        rrhole_x([-wall / 2, usb_y, usb_z], [plug_w + plug_clr, plug_h + plug_clr], 2.0, wall + 2);
        // sensor lead hole in the far wall, in the side bay
        hole_x([IX + wall / 2, bay_yc, cable_z], cable_d + 0.5, wall + 2);
        // screw pilots
        for (e = ears) translate([e[0][0], e[0][1], IZ - ear_h - 1]) cylinder(d = screw_pilot, h = ear_h + 2);
    }
    // PCB end ledges (centre only, clear of the header rows)
    translate([0, pcb_y0 + pcb_w / 2 - ledge_w / 2, 0]) cube([pcb_x0 + ledge_d, ledge_w, pcb_under]);
    translate([IX - gap - ledge_d, pcb_y0 + pcb_w / 2 - ledge_w / 2, 0]) cube([gap + ledge_d, ledge_w, pcb_under]);
    // Y-locating posts on the bay side of the PCB, one at each end
    for (x = [0, IX - 3])
        translate([x, bay_y0, 0]) cube([3, 1.2, pcb_z0 + pcb_t + 1.0]);
    // zip-tie anchor just inside the lead hole: a bridge the tie threads under
    translate([IX - anchor_l - 1, bay_yc - 5, 0]) difference() {
        cube([anchor_l, 10, anchor_h]);
        translate([(anchor_l - 4.2) / 2, -1, -eps]) cube([4.2, 12, 2.2]);
    }
}

module lid_assembled() {
    zt = IZ;                       // lid underside = top of the walls
    difference() {
        union() {
            translate([0, 0, zt]) linear_extrude(lid_t) union() {
                outline([IX, IY], r_in, wall);
                for (e = ears) translate(e[0]) circle(d = ear_d);
            }
            // locating lip just inside the walls
            translate([0, 0, zt - 2.0]) outline_ring([IX, IY], r_in, -clr - 1.2, -clr, 2.0 + eps);
            // hold-down fingers: on the antenna end of the PCB and on the USB-C shell
            translate([IX - gap - 3.5, pcb_y0 + pcb_w / 2 - 2, pcb_z0 + pcb_t + 0.2]) cube([3, 4, zt - (pcb_z0 + pcb_t + 0.2) + eps]);
            translate([pcb_x0 + 1.5, usb_y - 2, usb_z + usbc_h / 2 + 0.2]) cube([3, 4, zt - (usb_z + usbc_h / 2 + 0.2) + eps]);
        }
        for (e = ears) translate([e[0][0], e[0][1], zt - 1]) cylinder(d = screw_clear, h = lid_t + 2);
        // LED hole
        translate([pcb_x0 + led_x, pcb_y0 + led_y, zt - 3]) cylinder(d = led_d, h = lid_t + 6);
    }
}

// print orientation: flipped so the outside face is on the bed
module lid_print() translate([0, 0, IZ + lid_t]) rotate([180, 0, 0]) lid_assembled();

// Stand-ins for the parts inside: part = "fit" previews them, "clash" must be empty.
module contents() {
    color("green") translate([pcb_x0, pcb_y0, pcb_z0]) cube([pcb_l, pcb_w, pcb_t]);
    color("silver") translate([pcb_x0 - 0.5, usb_y - 4.5, pcb_z0 + pcb_t]) cube([7.5, 9, usbc_h]);
    color("gray") translate([-30, usb_y - plug_w / 2, usb_z - plug_h / 2]) cube([30 + pcb_x0 - 0.6, plug_w, plug_h]);
    color("red") translate([0.5, bay_y0 + 1.3, 0]) cube([boost_l, boost_w, boost_h]);
    color("orange") translate([boost_l + 1.5, bay_y0 + 1.3, 0]) cube([div_l, div_w, div_h]);
    color("black") translate([IX - anchor_l - 2, bay_yc, cable_z]) rotate([0, 90, 0]) cylinder(d = cable_d, h = 20);
}

if (part == "body") body();
else if (part == "fit") { body(); %lid_assembled(); contents(); }
else if (part == "clash") intersection() { union() { body(); lid_assembled(); } contents(); }
else if (part == "lid") lid_print();
else { body(); translate([0, 0, explode]) lid_assembled(); }
