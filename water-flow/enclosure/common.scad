// common.scad -- shared helpers for the water-flow enclosures.
// Units: mm. OpenSCAD 2021.01 or newer.

eps = 0.01;

// 2D rounded rectangle, origin at its lower-left corner.
module rrect(size, r) {
    rr = max(min(r, min(size[0], size[1]) / 2 - 0.01), 0.01);
    translate([rr, rr]) offset(r = rr) square([size[0] - 2 * rr, size[1] - 2 * rr]);
}

// 2D rounded rectangle centred on the origin.
module rrect_c(size, r) translate([-size[0] / 2, -size[1] / 2]) rrect(size, r);

// The interior outline grown outward by d (d = 0 is the interior itself).
// size = [x, y] of the interior, r = interior corner radius.
module outline(size, r, d) offset(r = d) rrect(size, r);

// Ring between two offsets of the interior outline, extruded to height h.
module outline_ring(size, r, d_in, d_out, h)
    linear_extrude(h) difference() { outline(size, r, d_out); outline(size, r, d_in); }

// A screw ear: a vertical cylinder of diameter d and height h whose BOTTOM
// is at z0, carried by a 45-degree cone that runs down to a small foot at
// point p (inside the wall), so it prints without supports.
// flip = true puts the cone ABOVE the ear instead (for parts printed
// upside down, e.g. a lid printed top-down).
module ear(c, p, z0, d, h, flip = false) {
    run  = norm([c[0] - p[0], c[1] - p[1]]) + d / 2;
    hull() {
        translate([c[0], c[1], z0]) cylinder(d = d, h = h);
        if (!flip)
            translate([p[0], p[1], z0 - run]) cylinder(d = 0.6, h = 0.2);
        else
            translate([p[0], p[1], z0 + h + run - 0.2]) cylinder(d = 0.6, h = 0.2);
    }
}

// Horizontal round hole along X, centred at c, length l.
module hole_x(c, d, l) translate(c) rotate([0, 90, 0]) cylinder(d = d, h = l, center = true);

// Horizontal rounded-rectangle hole along X; size = [width (Y), height (Z)].
module rrhole_x(c, size, r, l)
    translate(c) rotate([0, 90, 0]) linear_extrude(l, center = true) rrect_c([size[1], size[0]], r);

// Flat mounting / hanging tab in the XY plane, rounded far end, with a slot.
// Origin at the middle of its root edge; it extends along +X by len.
module slot_tab(len, w, t, slot_w, slot_l) {
    difference() {
        hull() {
            translate([-eps, -w / 2, 0]) cube([eps, w, t]);
            translate([len - w / 2, 0, 0]) cylinder(d = w, h = t);
        }
        hull() for (s = [-1, 1])
            translate([len - w / 2 + s * (slot_l - slot_w) / 2, 0, -1])
                cylinder(d = slot_w, h = t + 2);
    }
}
