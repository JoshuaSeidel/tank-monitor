// Long spray bar for the 75 gal (Marineland 75: 48 x 18 x 21 in outside,
// ~47 in / 1194 mm inside). Replaces the Vevor AQ-911F-UV's whole "rain
// shower pipe assembly": everything from the locked in-tank outlet pipe down.
//
// v1 (2026-11-18). PETG on the Creality K2 Plus (350 x 350 x 350 mm).
//
// WHY THESE SIZES
// Vevor publishes no pipe sizes for this filter (manual, product page and
// listings checked 2026-11-18). The canister hose is 16/22 mm and slides
// over the in-tank pipe, so that pipe is taken as ~16 mm outside. The inlet
// is a slotted sleeve closed with a zip tie, so it grips anything from about
// 15 to 18 mm; print `part = "gauge"` first and slide the rings over the dry
// top of the pipe to confirm, then set inlet_pipe_od. The inlet joint is
// underwater INSIDE the tank: it must hold on, it need not be watertight.
//
// LAYOUT
//   inlet block  -- vertical sleeve over the locked pipe, horizontal spigot
//   seg 1..3     -- 24 / 19 mm tube, socket at the feed end, spigot (O-ring
//                   17 x 2 mm) at the far end; the last segment is capped
//   clips        -- C-clips for the 24 mm bar with a keyhole tab for a
//                   standard aquarium suction cup
// Total ~1 m (39 in) of holes. Feed is at one end (feed_at_center = false)
// because the outlet pipe is fixed where it is; the holes grow from
// hole_d_near to hole_d_far so the far end is not starved.
//
// PRINTING
// Segments stand upright, socket end down, exactly as exported (round tube,
// clean O-ring groove, holes printed as teardrops pointing up so they need no
// supports). Segments 1-2 are 340 mm tall with the spigot (K2 Plus: 350).
// The last segment's 3 mm end cap is a 19 mm bridge -- no support needed.
// Inlet block prints block down, sleeve up; the sideways spigot needs
// supports from the build plate under it (tree supports, easy off).
// 0.2 mm layers, 4 walls, 40% infill (inlet block 100%). Clean PETG only.
//
// PICK A PART:
part = "assembly";   // assembly | seg1 | seg2 | seg3 | inlet | clip | gauge

// ---- tank / fit ---------------------------------------------------------
inlet_pipe_od   = 16.0;  // locked outlet pipe outside diameter (see gauge)
inlet_clear     = 0.4;   // sleeve bore = pipe + this (zip tie closes it)
// ---- bar ---------------------------------------------------------------
bar_od          = 24.0;
bar_id          = 19.0;
seg_body        = 320.0; // tube length per segment, not counting the spigot
n_seg           = 3;
spigot_len      = 20.0;
spigot_od       = 20.0;
spigot_id       = 15.0;
socket_clear    = 0.3;   // socket bore = spigot_od + this
oring_root_d    = 17.0;  // groove floor; O-ring 17 mm ID x 2 mm section
oring_w         = 2.6;   // groove width
oring_from_tip  = 7.0;   // groove centre, measured from the spigot tip
cap_t           = 3.0;   // end cap thickness on the last segment
// ---- holes -------------------------------------------------------------
hole_pitch      = 30.0;  // mm between holes
hole_d_near     = 2.3;   // nearest the feed
hole_d_far      = 2.9;   // farthest from the feed
hole_margin     = 15.0;  // keep holes this far from any joint
hole_aim        = 10;    // degrees above horizontal (the "slightly up" ripple)
// Stretches of bar with NO holes, measured in mm from the inlet block's
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

module tube(od, id, h) {
    difference() {
        cylinder(d = od, h = h);
        translate([0, 0, -eps]) cylinder(d = id, h = h + 2 * eps);
    }
}

// One bar segment, standing on its socket end (z = 0 is the feed side).
// i = 0..n_seg-1. Bar position along the tank = i * seg_pitch + z.
module segment(i) {
    last = (i == n_seg - 1);
    difference() {
        union() {
            tube(bar_od, bar_id, seg_body);
            if (!last)   // spigot into the next segment's socket
                translate([0, 0, seg_body - eps])
                    tube(spigot_od, spigot_id, spigot_len + eps);
        }
        // socket at the feed end
        translate([0, 0, -eps]) cylinder(d = spigot_od + socket_clear, h = spigot_len + 1);
        // O-ring groove on the spigot
        if (!last)
            translate([0, 0, seg_body + spigot_len - oring_from_tip - oring_w / 2])
                tube(spigot_od + 1, oring_root_d, oring_w);
        // holes along +y (= into the tank), tilted hole_aim degrees toward -x
        // (= up once the bar lies in the tank, see assembly())
        for (z = [hole_margin + spigot_len : hole_pitch : seg_body - hole_margin]) {
            x = i * seg_pitch + z;
            if (!skipped(x))
                translate([0, 0, z]) rotate([0, 0, hole_aim])
                    translate([0, bar_od / 4, 0]) teardrop_y(hole_d(x), bar_od / 2 + 1);
        }
    }
    if (last)   // closed far end
        translate([0, 0, seg_body - cap_t]) cylinder(d = bar_od, h = cap_t);
}

// Inlet block: vertical slotted sleeve over the locked pipe, horizontal
// spigot into segment 1. Printed sleeve up, block on the bed.
blk = bar_od + 6;
sleeve_len = 30;
module inlet() {
    sb = inlet_pipe_od + inlet_clear;
    difference() {
        union() {
            translate([-blk / 2, -blk / 2, 0]) cube([blk, blk, blk]);
            // sleeve up
            translate([0, 0, blk - eps]) cylinder(d = sb + 5, h = sleeve_len);
            // spigot sideways (+x), with an O-ring groove like the segments
            translate([blk / 2 - eps, 0, blk / 2]) rotate([0, 90, 0])
                tube(spigot_od, spigot_id, spigot_len + eps);
        }
        // pipe bore down into the block, stopping at the cross bore
        translate([0, 0, blk / 2]) cylinder(d = sb, h = blk + sleeve_len);
        // cross bore to the spigot (teardrop, self-supporting)
        translate([blk / 4, 0, blk / 2]) rotate([0, 0, 90]) teardrop_y(spigot_id, blk / 2 + 1);
        // vertical slots so the zip tie can close the sleeve
        for (a = [0, 180]) rotate(a)
            translate([sb / 2 - 1, -1, blk + 4]) cube([5, 2, sleeve_len]);
        // zip-tie groove
        translate([0, 0, blk + sleeve_len - 8]) tube(sb + 6, sb + 2.6, 4);
        // O-ring groove on the spigot
        translate([blk / 2 + spigot_len - oring_from_tip - oring_w / 2, 0, blk / 2])
            rotate([0, 90, 0]) tube(spigot_od + 1, oring_root_d, oring_w);
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

// Test rings: slide over the dry top of the locked pipe; the one that slides
// on with no play is the size. Labelled by bore in mm.
gauge_sizes = [15.0, 15.5, 16.0, 16.5, 17.0, 17.5, 18.0, 19.0, 20.0, 22.0];
module gauge() {
    for (k = [0 : len(gauge_sizes) - 1]) {
        d = gauge_sizes[k];
        translate([(k % 5) * 34, floor(k / 5) * 40, 0]) {
            tube(d + 6, d, 5);
            translate([0, -(d / 2 + 7), 0]) linear_extrude(1.2)
                text(str(d), size = 4.5, halign = "center", valign = "center");
        }
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
