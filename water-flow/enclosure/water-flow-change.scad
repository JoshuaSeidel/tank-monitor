// water-flow-change.scad -- SEALED enclosure for the water-change flow meter
// (water-flow-change), used beside a lot of moving water.
//
// Body + deep lid joined on a perimeter gasket: 2 mm silicone O-ring cord in
// a groove in the body rim, pressed by a tongue on the lid, 4 x M3 screws
// into M3 heat-set inserts. The only openings are the 12 mm latching switch
// (switch end) and a PG7 cable gland (far end). The board sits just above
// the body rim with its USB-C toward the switch end, so with the lid off a
// USB-C cable slides in over the rim to charge -- no hole in the box for it.
// The blue LED shows through a 0.6 mm skin in the lid (no hole).
// A flat tab with an 8 mm hole at the switch end hangs the box from a hook,
// or from the Brute with the printed S-hook (part "hook").
//
// PRINT (PETG, 0.2 mm layers, 4 walls, no supports):
//   change-body : floor on the bed, opening up (as exported).
//   change-lid  : outside face on the bed, skirt up (as exported).
//   change-hook : flat (as exported). Optional.
//
//   openscad -D 'part="body"' -o stl/change-body.stl water-flow-change.scad
//   openscad -D 'part="lid"'  -o stl/change-lid.stl  water-flow-change.scad
//   openscad -D 'part="hook"' -o stl/change-hook.stl water-flow-change.scad
//   part = "assembly" (default) shows everything in place; "section" cuts it.

include <common.scad>

part    = "assembly";   // "body" | "lid" | "hook" | "assembly" | "section"
explode = 15;
$fn     = 48;

/* ---------- print / shell ---------- */
wall    = 1.8;   // 4 perimeters at 0.45 mm line width
floor_t = 1.4;   // 7 solid layers -- watertight
lid_t   = 1.2;
r_in    = 2.0;   // interior corner radius

/* ---------- gasket ---------- */
cord_d   = 2.0;  // silicone O-ring cord (or a cured bead of RTV silicone)
groove_w = 2.6;  // ~1.3 x cord
groove_d = 1.8;  // depth below the rim face
tongue_w = 1.4;
tongue_h = 0.4;  // compressed cord = groove_d - tongue_h = 1.4 mm -> 30 % squeeze
land     = 1.2;  // plastic on each side of the groove
rim_w    = groove_w + 2 * land;   // width of the sealing face
rim_h    = 2.2;  // straight part of the rim band; a 45-degree chamfer sits under it
drip     = 0.8;  // lid band overhangs the body band: drip edge

/* ---------- screws ---------- */
insert_d     = 4.0;   // M3 heat-set insert hole (M3 x 5.7, 4.6 OD). Self-tapping: 2.5
insert_depth = 6.5;
screw_clear  = 3.4;
ear_d        = 9.0;
ear_h_body   = 7.5;
ear_h_lid    = 4.0;   // plastic under the screw head -> M3 x 10 countersunk screws
csk_d        = 6.6;   // M3 countersunk head diameter (+ clearance)

/* ---------- MEASURE AND SET: AITRIP ESP32 Lite V1.0.0 ---------- */
pcb_l     = 49.5;  // published 49.2 x 25.5
pcb_w     = 25.8;
pcb_t     = 1.6;
pcb_lift  = 1.5;   // PCB underside above the body rim (USB-C plug overmould clears the rim)
jst_clear = 12;    // USB end of the PCB to the switch-end wall: battery plug + lead bend
jst_h     = 6.0;   // JST-PH socket height above the PCB
top_clear = 1.5;   // over the tallest part
usb_off_y = 0;     // USB-C centre, offset from the PCB's width centre (+ = to your left, USB-C end toward you)
usbc_h    = 3.3;
plug_w    = 12.5;  // USB-C cable overmould, for the clearance check only
led_x     = 9.0;   // blue LED (GPIO22) from the PCB's USB-end edge  -- measure
led_y     = 5.0;   //                    from the PCB's LEFT long edge (USB-C toward you) -- measure
led_win_d = 6.0;   // diameter of the thin spot
led_skin  = 0.6;   // lid thickness left over the LED (3 layers). 0 = through hole (NOT sealed)
gap       = 0.3;

/* ---------- MEASURE AND SET: battery (MakerHawk 102050, 1000 mAh) ---------- */
batt_l = 56.0;     // 50 mm cell + protection board / lead fold
batt_t = 10.5;     // stands on its long edge
batt_h = 20.5;
foam   = 1.5;      // foam pad on the floor, both faces and the cell end
foam_top = 2.0;    // foam strip on top, pressed by the lid rib
part_t = 1.2;      // partition between battery bay and electronics

/* ---------- MEASURE AND SET: switch + gland ---------- */
sw_hole   = 12.2;  // 12 mm latching button
sw_depth  = 26;    // body + terminals + soldered wires behind the panel
sw_nut_af = 16;    // inside hex nut across flats
sw_head_d = 15.0;  // head / O-ring outside diameter
gl_hole   = 12.7;  // PG7: 12.5 mm thread
gl_nut_af = 18;    // PG7 lock nut across flats (inside)
gl_hex_af = 15;    // PG7 body hex (outside)
boost_l = 25.5; boost_w = 18.0; boost_h = 6.0;   // see README (USB-A version is bigger)

/* ---------- hang tab / hook ---------- */
tab_len  = 18;
tab_w    = 18;
tab_t    = 3.0;
tab_hole = 8.0;
hook_gap = 12;     // opening of the S-hook's big end -- measure the Brute rim / handle
hook_t   = 4.0;    // strip width
hook_th  = 5.0;    // print thickness

/* ---------- derived ---------- */
cham     = rim_w - wall;                          // rim band chamfer run
band     = rim_h + cham;                          // rim band total height
sw_nut_r = sw_nut_af / sqrt(3) + 0.5;             // hex corner radius + clearance
gl_nut_r = gl_nut_af / sqrt(3) + 0.5;
gl_hex_r = gl_hex_af / sqrt(3) + 0.3;
bay_w    = batt_t + 2 * foam;                     // battery bay (y = 0 .. bay_w)
ey0      = bay_w + part_t;                        // electronics bay start
ebay_w   = max(pcb_w + 2 * gap + 1.2, 2 * sw_nut_r + 1, 2 * gl_nut_r + 1);
IX = max(batt_l + 2 * foam, jst_clear + pcb_l + gap + 1.2);
IY = ey0 + ebay_w;
// body height: battery stack, and room for switch/gland nuts inside and
// heads outside below the rim band chamfer
IZ = max(foam + batt_h + foam_top,
         sw_nut_af / 2 + 0.5 + sw_head_d / 2 + band + 0.5,
         gl_nut_af / 2 + 0.5 + gl_hex_af / 2 + 0.3 + band + 0.5);   // nuts turned flat-down
HL = pcb_lift + pcb_t + max(jst_h, usbc_h) + top_clear;   // lid inner height above the rim
sw_z  = max(sw_nut_af / 2 + 0.5, IZ - band - sw_head_d / 2 - 0.5);
gl_z  = max(gl_nut_af / 2 + 0.5, IZ - band - gl_hex_af / 2 - 0.8);
ey_c  = ey0 + ebay_w / 2;
pcb_x1 = IX - 1.2 - gap;  pcb_x0 = pcb_x1 - pcb_l;          // antenna end at the gland wall
pcb_y1 = IY - 1.2 - gap;  pcb_y0 = pcb_y1 - pcb_w;          // beside the outer wall, inside a 1.2 mm stop
pcb_z0 = IZ + pcb_lift;
usb_y  = (pcb_y0 + pcb_y1) / 2 + usb_off_y;
OX = IX + 2 * wall;  OY = IY + 2 * wall;
ears = [ for (c = [[0, 0, -1, -1], [IX, 0, 1, -1], [0, IY, -1, 1], [IX, IY, 1, 1]])
         [[c[0] + c[2] * rim_w, c[1] + c[3] * rim_w],
          [c[0] + c[2] * (wall - 1.6), c[1] + c[3] * (wall - 1.6)]] ];

echo(str("CHANGE interior ", IX, " x ", IY, " x ", IZ, " (+", HL, " in lid)"));
echo(str("CHANGE outer (rim band, no ears/tab): ", IX + 2 * rim_w + 2 * drip, " x ", IY + 2 * rim_w + 2 * drip,
         " x ", floor_t + IZ + HL + lid_t));
echo(str("switch z ", sw_z, "  gland z ", gl_z));

module body() {
    difference() {
        union() {
            // walls + floor
            translate([0, 0, -floor_t]) linear_extrude(floor_t + IZ) outline([IX, IY], r_in, wall);
            // rim band: sealing face, 45-degree chamfer under it
            translate([0, 0, IZ - rim_h]) linear_extrude(rim_h) outline([IX, IY], r_in, rim_w);
            hull() {
                translate([0, 0, IZ - band]) linear_extrude(eps) outline([IX, IY], r_in, wall);
                translate([0, 0, IZ - rim_h - eps]) linear_extrude(eps) outline([IX, IY], r_in, rim_w);
            }
            for (e = ears) ear(e[0], e[1], IZ - ear_h_body, ear_d, ear_h_body);
            // hanging tab at the switch end, flush with the bottom
            translate([-wall + 0.5, IY / 2, -floor_t]) rotate([0, 0, 180])
                difference() {
                    slot_tab(tab_len + 0.5, tab_w, tab_t, 0.01, 0.01);
                    translate([tab_len + 0.5 - tab_w / 2, 0, -1]) cylinder(d = tab_hole, h = tab_t + 2);
                }
        }
        // cavity (the hull above also fills it -- cut it back out)
        linear_extrude(IZ + 1) rrect([IX, IY], r_in);
        // gasket groove
        translate([0, 0, IZ - groove_d]) outline_ring([IX, IY], r_in, rim_w / 2 - groove_w / 2, rim_w / 2 + groove_w / 2, groove_d + 1);
        // switch hole (switch end, x = 0)
        hole_x([-wall / 2, ey_c, sw_z], sw_hole, wall + 2);
        // gland hole (far end, x = IX)
        hole_x([IX + wall / 2, ey_c, gl_z], gl_hole, wall + 2);
        // insert holes
        for (e = ears) translate([e[0][0], e[0][1], IZ - insert_depth]) cylinder(d = insert_d, h = insert_depth + 1);
    }
    // partition, battery bay | electronics, full height (it carries the PCB
    // beam), with a wire notch at the switch end
    difference() {
        translate([0, bay_w, 0]) cube([IX, part_t, IZ]);
        translate([-1, bay_w - 1, IZ - 8]) cube([9, part_t + 2, 9]);
    }
    // USB-end PCB support: a beam bridging partition -> outer wall under the
    // PCB's end strip. In front of the PCB it stays low (IZ + 0.5) so the
    // USB-C plug overmould passes over it; corner stops locate the PCB.
    translate([pcb_x0 - 1.2, bay_w, IZ - 2.5]) cube([3.2, IY - bay_w, 3.0]);
    translate([pcb_x0, bay_w, IZ]) cube([2.0, IY - bay_w, pcb_lift]);
    for (y = [pcb_y0, pcb_y1 - 1.5])
        translate([pcb_x0 - 1.2, y, IZ]) cube([1.2 + eps, 1.5, pcb_lift + pcb_t]);
    translate([pcb_x0, pcb_y0 - 1.2, IZ]) cube([2.0, 1.2, pcb_lift + pcb_t]);
    translate([pcb_x0, pcb_y1, IZ]) cube([2.0, IY - pcb_y1, pcb_lift + pcb_t]);   // 1.2 + gap wide
    // antenna-end support: corbel on the gland wall with an end stop
    translate([IX - 1.2 - gap - 2.0, (pcb_y0 + pcb_y1) / 2 - 6, 0]) {
        hull() {
            translate([0, 0, pcb_z0 - 1.5]) cube([3.5 + gap, 12, 1.5]);
            translate([3.5 + gap - eps, 0, pcb_z0 - 1.5 - 3.5 - gap]) cube([eps, 12, 1]);
        }
        translate([2.0 + gap, 0, pcb_z0 - eps]) cube([1.2, 12, pcb_t]);
    }
}

module lid_assembled() {
    z0 = IZ;                       // rim face
    zt = IZ + HL;                  // underside of the top plate
    difference() {
        union() {
            // skirt + top plate
            translate([0, 0, z0]) linear_extrude(HL + lid_t) outline([IX, IY], r_in, wall);
            // rim band (with drip overhang), chamfer above it
            translate([0, 0, z0]) linear_extrude(rim_h) outline([IX, IY], r_in, rim_w + drip);
            hull() {
                translate([0, 0, z0 + rim_h]) linear_extrude(eps) outline([IX, IY], r_in, rim_w + drip);
                translate([0, 0, z0 + rim_h + cham + drip]) linear_extrude(eps) outline([IX, IY], r_in, wall);
            }
            // screw columns, full height, webbed to the skirt corner
            for (e = ears) hull() {
                translate([e[0][0], e[0][1], z0]) cylinder(d = ear_d, h = HL + lid_t);
                translate([e[1][0], e[1][1], z0]) cylinder(d = 1, h = HL + lid_t);
            }
            // gasket tongue
            translate([0, 0, z0 - tongue_h]) outline_ring([IX, IY], r_in, rim_w / 2 - tongue_w / 2, rim_w / 2 + tongue_w / 2, tongue_h + eps);
            // battery hold-down rib: presses the top foam strip
            translate([8, foam + batt_t / 2 - 1, foam + batt_h + foam_top - 0.8]) cube([IX - 16, 2, zt - (foam + batt_h + foam_top - 0.8) + eps]);
            // PCB hold-down fingers: antenna end, and on the USB-C shell
            translate([pcb_x1 - 4, (pcb_y0 + pcb_y1) / 2 - 2, pcb_z0 + pcb_t + 0.2]) cube([3, 4, zt - (pcb_z0 + pcb_t + 0.2) + eps]);
            translate([pcb_x0 + 1.5, usb_y - 2, pcb_z0 + pcb_t + usbc_h + 0.2]) cube([3, 4, zt - (pcb_z0 + pcb_t + usbc_h + 0.2) + eps]);
        }
        // cavity inside the skirt
        translate([0, 0, z0 - 1]) linear_extrude(HL + 1) rrect([IX, IY], r_in);
        // M3 countersunk screws: clearance hole, 45-degree seat, counterbore to the top
        for (e = ears) translate([e[0][0], e[0][1], 0]) {
            translate([0, 0, z0 - 1]) cylinder(d = screw_clear, h = HL + lid_t + 2);
            translate([0, 0, z0 + ear_h_lid]) cylinder(d1 = screw_clear, d2 = csk_d, h = (csk_d - screw_clear) / 2 + eps);
            translate([0, 0, z0 + ear_h_lid + (csk_d - screw_clear) / 2]) cylinder(d = csk_d, h = HL + lid_t);
        }
        // LED thin spot (pocket from the inside)
        translate([pcb_x0 + led_x, pcb_y1 - led_y, zt - eps])
            cylinder(d = led_win_d, h = lid_t - led_skin + eps);
    }
    // re-add the parts the cavity cut removed (rib and fingers live inside it)
    intersection() {
        union() {
            translate([8, foam + batt_t / 2 - 1, foam + batt_h + foam_top - 0.8]) cube([IX - 16, 2, zt - (foam + batt_h + foam_top - 0.8) + eps]);
            translate([pcb_x1 - 4, (pcb_y0 + pcb_y1) / 2 - 2, pcb_z0 + pcb_t + 0.2]) cube([3, 4, zt - (pcb_z0 + pcb_t + 0.2) + eps]);
            translate([pcb_x0 + 1.5, usb_y - 2, pcb_z0 + pcb_t + usbc_h + 0.2]) cube([3, 4, zt - (pcb_z0 + pcb_t + usbc_h + 0.2) + eps]);
        }
        translate([0, 0, -50]) linear_extrude(200) rrect([IX, IY], r_in);
    }
}

module lid_print() translate([0, 0, IZ + HL + lid_t]) rotate([180, 0, 0]) lid_assembled();

// S-hook: the big U goes over the Brute's rim or handle, the small U through
// the tab hole. Flat 2D profile, printed lying down.
module hook() {
    t = hook_t; r1 = hook_gap / 2; r2 = 3.5; L = 22;
    c2 = r2 - r1;                                   // small U centre (x), shares the spine
    module half_ring(r, up) difference() {
        circle(r = r + t); circle(r = r);
        translate([-50, up ? -100 : 0]) square([100, 100]);
    }
    linear_extrude(hook_th) {
        half_ring(r1, true);                               // big U, opening down
        translate([r1, -5]) square([t, 5 + eps]);          // its lip
        translate([-r1 - t, -L]) square([t, L + eps]);     // spine
        translate([c2, -L]) half_ring(r2, false);          // small U, opening up
        translate([c2 + r2, -L]) square([t, 6]);           // its lip
    }
}

// Stand-ins for the parts inside, for the fit check (part = "fit" previews
// them in colour; part = "clash" must render EMPTY).
module contents() {
    color("green") translate([pcb_x0, pcb_y0, pcb_z0]) cube([pcb_l, pcb_w, pcb_t]);              // PCB
    color("silver") translate([pcb_x0 - 0.5, usb_y - 4.5, pcb_z0 + pcb_t]) cube([7.5, 9, usbc_h]); // USB-C
    color("gray") translate([-40, usb_y - plug_w / 2, pcb_z0 + pcb_t + usbc_h / 2 - 3.5])
        cube([40 + pcb_x0 - 0.6, plug_w, 7]);                                                      // plug overmould
    color("blue") translate([foam, foam, foam]) cube([batt_l, batt_t, batt_h]);                   // cell
    color("black") translate([-eps, ey_c, sw_z]) rotate([0, 90, 0]) {                               // switch
        cylinder(d = 12, h = sw_depth - wall);
        cylinder(d = sw_nut_af, h = 3, $fn = 6);
    }
    color("black") translate([-wall - 3, ey_c, sw_z]) rotate([0, 90, 0]) cylinder(d = sw_head_d, h = 3);
    color("white") translate([IX + eps, ey_c, gl_z]) rotate([0, -90, 0]) {                          // gland
        cylinder(d = 12.5, h = 8); cylinder(d = gl_nut_af, h = 5, $fn = 6);
    }
    color("white") translate([IX + wall, ey_c, gl_z]) rotate([0, 90, 0]) cylinder(d = gl_hex_af, h = 6, $fn = 6);
    color("red") translate([sw_nut_af / 4 + 4, ey0 + 0.3, 0.5]) cube([boost_l, boost_h, boost_w]); // boost, on edge
}

if (part == "body") body();
else if (part == "fit") { body(); translate([0, 0, 0]) %lid_assembled(); contents(); }
else if (part == "clash") intersection() { union() { body(); lid_assembled(); } contents(); }
else if (part == "lid") lid_print();
else if (part == "hook") hook();
else if (part == "section") difference() {
    union() { body(); lid_assembled(); }
    translate([-50, -200 + ey_c, -50]) cube([200, 200, 200]);
}
else { body(); translate([0, 0, explode]) lid_assembled(); }
