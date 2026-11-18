// Long spray bar for the 75 gal (Marineland 75: 48 x 18 x 21 in outside,
// ~47 in / 1194 mm inside). Replaces the Vevor AQ-911F-UV's whole "rain
// shower pipe assembly": everything from the locked in-tank outlet pipe down.
//
// v2 (2026-11-18). PETG on the Creality K2 Plus (350 x 350 x 350 mm).
//   v2: every joint is a plain friction slip fit (no O-rings, no zip tie);
//       nozzles stick out of the bar; gauge rings 8-15 mm (the in-tank pipe
//       is much smaller than the 16/22 hose -- user, 2026-11-18).
//   v1: O-ring joints, zip-tie inlet sleeve, flush holes, 16 mm assumed.
//
// SIZES
// Vevor publishes no pipe sizes for this filter (manual, product page and
// listings checked 2026-11-18). Print `part = "gauge"` and slide the rings
// over the dry pipe: the ring that goes on with a firm push and stays put
// is the friction fit -- set inlet_bore to THAT ring's number (it is the
// bore as designed, so printer shrink is already in it). If two feel
// right, take the tighter. Print `part = "fittest"` to pick fit_clear for
// the bar joints the same way.
//
// LAYOUT
//   inlet block  -- vertical friction sleeve over the locked pipe, horizontal
//                   spigot into segment 1
//   seg 1..3     -- 24 / 19 mm tube, socket at the feed end, tapered spigot
//                   at the far end; the last segment is capped
//   nozzles      -- stubs standing out nozzle_len mm, aimed hole_aim degrees up
//   clips        -- C-clips for the bar with a keyhole tab for a suction cup
// Feed is at one end because the outlet pipe is fixed; the nozzle bores grow
// from hole_d_near to hole_d_far so the far end is not starved.
//
// PRINTING
// Segments stand upright, socket end down, exactly as exported. Nozzles and
// their bores are teardrops pointing up, so nothing needs support. Segments
// 1-2 are 340 mm tall with the spigot (K2 Plus: 350). The last segment's
// 3 mm end cap is a 19 mm bridge. Inlet block prints block down, sleeve up;
// the sideways spigot needs supports from the build plate under it.
// 0.2 mm layers, 4 walls, 40% infill (inlet block 100%). Clean PETG only.
//
// PICK A PART:
part = "assembly";   // assembly | seg1 | seg2 | seg3 | inlet | clip | gauge | fittest

// ---- fit (set from the gauge / fit test) ----------------------------------
inlet_bore      = 12.0;  // sleeve bore over the locked pipe = snug gauge ring
inlet_sleeve    = 30.0;  // how far the sleeve slides over the pipe
fit_clear       = 0.10;  // bar joints: socket bore = spigot_od + this
// ---- bar ---------------------------------------------------------------
bar_od          = 24.0;
bar_id          = 19.0;
seg_body        = 320.0; // tube length per segment, not counting the spigot
n_seg           = 3;
spigot_len      = 25.0;
spigot_od       = 21.0;
spigot_id       = 17.0;
spigot_lead     = 0.4;   // tip is this much smaller: starts easily, tightens as it seats
cap_t           = 3.0;   // end cap thickness on the last segment
// ---- nozzles -----------------------------------------------------------
hole_pitch      = 30.0;  // mm between nozzles
hole_d_near     = 2.3;   // bore nearest the feed
hole_d_far      = 2.9;   // bore farthest from the feed
nozzle_len      = 6.0;   // how far a nozzle stands out of the bar
nozzle_wall     = 1.2;   // 3 perimeters
hole_margin     = 15.0;  // keep nozzles this far from any joint
hole_aim        = 10;    // degrees above horizontal (the "slightly up" ripple)
// Stretches of bar with NO nozzles, measured in mm from the inlet block's
// side of segment 1 -- e.g. [[300, 360]] where a heater or probe sits.
skip = [];
// ---- clip --------------------------------------------------------------
clip_w          = 12.0;
clip_t          = 2.4;
keyhole_head_d  = 9.0;   // suction-cup head
keyhole_neck_w  = 4.5;   // suction-cup neck
$fn = 96;

eps = 0.01;
seg_pitch = seg_body;            // bar length each segment adds
bar_len   = n_seg * seg_pitch;   // holes run over this

// Hole diameter tapers with distance from the feed.
function hole_d(x) = hole_d_near + (hole_d_far - hole_d_near) * x / bar_len;
function skipped(x) = len([for (s = skip) if (x >= s[0] && x <= s[1]) 1]) > 0;

// A horizontal hole along +y, for a part printed upright (+z up): a teardrop
// with its point up so the roof is self-supporting.
module teardrop_y(d, l) {
    rotate([90, 0, 0]) linear_extrude(height = l, center = true)
        union() {
            circle(d = d, $fn = 32);
            rotate(45) square(d / 2);
        }
}

// Bore version starting at y = 0 (for cutting through a nozzle).
module teardrop_y_from0(d, l) {
    translate([0, l / 2, 0]) teardrop_y(d, l);
}

// Same profile, as a solid stub from y = 0 to y = l.
module teardrop_stub(d, l) {
    rotate([-90, 0, 0]) linear_extrude(height = l)
        rotate(180) union() {     // after rotate([-90,..]) 2D +y maps to -z: flip so the point is up
            circle(d = d, $fn = 32);
            rotate(45) square(d / 2);
        }
}

module tube(od, id, h) {
    difference() {
        cylinder(d = od, h = h);
        translate([0, 0, -eps]) cylinder(d = id, h = h + 2 * eps);
    }
}

// One bar segment, standing on its socket end (z = 0 is the feed side).
// i = 0..n_seg-1. Bar position along the tank = i * seg_pitch + z.
function nozzle_z() = [for (z = [hole_margin + spigot_len : hole_pitch : seg_body - hole_margin]) z];
module nozzle_at(z) {
    translate([0, 0, z]) rotate([0, 0, hole_aim]) children();
}
module segment(i) {
    last = (i == n_seg - 1);
    difference() {
        union() {
            tube(bar_od, bar_id, seg_body);
            if (!last)   // tapered spigot into the next segment's socket
                translate([0, 0, seg_body - eps]) difference() {
                    cylinder(d1 = spigot_od, d2 = spigot_od - spigot_lead, h = spigot_len + eps);
                    translate([0, 0, -eps]) cylinder(d = spigot_id, h = spigot_len + 3 * eps);
                }
            // nozzle stubs
            for (z = nozzle_z()) {
                x = i * seg_pitch + z;
                if (!skipped(x))
                    nozzle_at(z) translate([0, bar_id / 2, 0])
                        teardrop_stub(hole_d(x) + 2 * nozzle_wall, (bar_od - bar_id) / 2 + nozzle_len);
            }
        }
        // socket at the feed end, with a 0.5 mm lead-in chamfer
        translate([0, 0, -eps]) cylinder(d = spigot_od + fit_clear, h = spigot_len + 0.5);
        translate([0, 0, -eps]) cylinder(d1 = spigot_od + fit_clear + 1, d2 = spigot_od + fit_clear, h = 0.5);
        // nozzle bores, right through the wall
        for (z = nozzle_z()) {
            x = i * seg_pitch + z;
            if (!skipped(x))
                nozzle_at(z) translate([0, bar_id / 4, 0])
                    teardrop_y_from0(hole_d(x), bar_od / 2 + nozzle_len + 1);
        }
        // keep the bore clear of nozzle material
        translate([0, 0, spigot_len]) cylinder(d = bar_id, h = seg_body);
    }
    if (last)   // closed far end
        translate([0, 0, seg_body - cap_t]) cylinder(d = bar_od, h = cap_t);
}

// Inlet block: vertical friction sleeve over the locked pipe, horizontal
// tapered spigot into segment 1. Printed sleeve up, block on the bed.
blk = bar_od + 6;
module inlet() {
    sb = inlet_bore;
    difference() {
        union() {
            translate([-blk / 2, -blk / 2, 0]) cube([blk, blk, blk]);
            translate([0, 0, blk - eps]) cylinder(d = sb + 5, h = inlet_sleeve);
            translate([blk / 2 - eps, 0, blk / 2]) rotate([0, 90, 0]) difference() {
                cylinder(d1 = spigot_od, d2 = spigot_od - spigot_lead, h = spigot_len + eps);
                translate([0, 0, -eps]) cylinder(d = spigot_id, h = spigot_len + 3 * eps);
            }
        }
        // pipe bore down into the block, stopping at the cross bore
        translate([0, 0, blk / 2]) cylinder(d = sb, h = blk + inlet_sleeve);
        // lead-in chamfer at the sleeve mouth
        translate([0, 0, blk + inlet_sleeve - 1]) cylinder(d1 = sb, d2 = sb + 2, h = 1 + eps);
        // cross bore to the spigot (teardrop, self-supporting)
        translate([blk / 4, 0, blk / 2]) rotate([0, 0, 90]) teardrop_y(spigot_id, blk / 2 + 1);
    }
}

// C-clip for the bar with a keyhole tab. Prints flat.
module clip() {
    r = bar_od / 2;
    difference() {
        union() {
            cylinder(r = r + clip_t, h = clip_w);
            translate([-(keyhole_head_d + 8) / 2, r, 0])
                cube([keyhole_head_d + 8, keyhole_head_d + 10, clip_t + 1]);
        }
        translate([0, 0, -eps]) cylinder(r = r, h = clip_w + 2 * eps);
        // opening: 75% of the diameter, so it snaps on
        translate([-r * 0.75, -r - clip_t - 1, -eps]) cube([r * 1.5, r, clip_w + 2 * eps]);
        // keyhole
        translate([0, r + 4 + keyhole_head_d / 2, -eps]) {
            cylinder(d = keyhole_head_d, h = 10);
            translate([-keyhole_neck_w / 2, 0, 0]) cube([keyhole_neck_w, keyhole_head_d, 10]);
        }
    }
}

// Test rings: slide over the dry locked pipe; the one that goes on with a
// firm push and stays put is inlet_bore. Labelled by bore in mm.
gauge_sizes = [8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0, 13.5, 14.0, 14.5, 15.0];
module gauge() {
    for (k = [0 : len(gauge_sizes) - 1]) {
        d = gauge_sizes[k];
        translate([(k % 5) * 30, floor(k / 5) * 34, 0]) {
            tube(d + 5, d, 5);
            translate([0, -(d / 2 + 6), 0]) linear_extrude(1.2)
                text(str(d), size = 4, halign = "center", valign = "center");
        }
    }
}

// Joint fit test: one tapered spigot and three short sockets at fit_clear
// 0.0 / 0.1 / 0.2. The socket that pushes on firmly and holds when you
// shake it is the fit_clear to use. Print standing, like the segments.
fit_tests = [0.0, 0.1, 0.2];
module fittest() {
    difference() {
        cylinder(d1 = spigot_od, d2 = spigot_od - spigot_lead, h = spigot_len);
        translate([0, 0, -eps]) cylinder(d = spigot_id, h = spigot_len + 2 * eps);
    }
    for (k = [0 : len(fit_tests) - 1])
        translate([(k + 1) * (bar_od + 8), 0, 0]) {
            difference() {
                cylinder(d = bar_od, h = spigot_len + 2);
                translate([0, 0, -eps]) cylinder(d = spigot_od + fit_tests[k], h = spigot_len + 3);
            }
            translate([0, -(bar_od / 2 + 5), 0]) linear_extrude(1.2)
                text(str(fit_tests[k]), size = 4, halign = "center", valign = "center");
        }
}

module assembly() {
    color("lightblue") inlet();
    for (i = [0 : n_seg - 1])
        translate([blk / 2 + i * seg_pitch, 0, blk / 2]) rotate([0, 90, 0])
            color(i % 2 ? "lightgreen" : "khaki") segment(i);
}

if (part == "assembly") assembly();
else if (part == "seg1") segment(0);
else if (part == "seg2") segment(1);
else if (part == "seg3") segment(2);
else if (part == "inlet") inlet();
else if (part == "clip") clip();
else if (part == "gauge") gauge();
else if (part == "fittest") fittest();
