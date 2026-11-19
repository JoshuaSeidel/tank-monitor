// Long spray bar for the 75 gal (Marineland 75: 48 x 18 x 21 in outside,
// ~47 in / 1194 mm inside). Replaces the Vevor AQ-911F-UV's spray bar (the
// two-piece ~14 in bar with ~20 nozzles that plugs into the fitting on the
// locked outlet pipe); that fitting stays.
//
// v3 (2026-11-18). PETG on the Creality K2 Plus (350 x 350 x 350 mm).
//   v3: CENTRE FEED. A drop tee plugs into the old fitting (12.4 mm plug),
//       S-bends down by `drop`, and tees into a left and a right arm, each
//       capped -- so the bar runs both ways from the inlet, under the fitting.
//   v2: friction slip fits, nozzles standing out, gauge 8-15 mm.
//   v1: O-ring joints, zip-tie sleeve, end feed, 16 mm assumed.
//
// SIZES
// Vevor publishes no pipe sizes (manual, product page, listings checked
// 2026-11-18). Old bar, calipers (user): plug 12.4 x 13.3 mm, tube 15.9 mm,
// nozzles 11 mm apart. The old Vevor suction-cup clips fit this 16 mm bar. Bar joints use
// fit_clear from `part = "fittest"` (PLA round: 0.0-0.2 all loose).
//
// LAYOUT (in the tank, x along the back glass, z up)
//   droptee  -- plug pointing at the fitting (-x), elbow, riser down `drop`,
//               tee whose run has a tapered spigot on each side
//   tubes 16 / 12 mm; every joint is the old bar's 12.4 mm plug (9 mm bore)
//   L1.. / R1..  -- arm segments: socket at the tee end, spigot onward, the
//               last one capped. Nozzles stand out nozzle_len, aimed
//               hole_aim up; bores grow away from the tee.
// Arms as set below: left 20 in = L1 + L2, right 6 in = R1 (one capped piece).
//
// PRINTING
// Segments stand upright, socket end down, exactly as exported; nozzles and
// bores are teardrops pointing up, so no supports. The drop tee prints as
// exported (tee run on the bed) with tree supports under the plug arm.
// 0.2 mm layers, 4 walls, 40% infill (drop tee 100%). Clean PETG only.
//
// PICK A PART:
part = "assembly";   // assembly | droptee | L1 | L2 | L3 | R1 | R2 | R3 | clip | gauge | fittest

// ---- fit (set from the gauge / fit test) ----------------------------------
inlet_plug_od   = 12.4;  // old bar's plug end, calipers (user, 2026-11-18)
inlet_plug_id   = 9.0;
inlet_plug_len  = 13.3;  // old bar's plug length, calipers (user, 2026-11-18)
inlet_stub      = 8.0;   // straight 16 mm run between the elbow and the plug
fit_clear       = -0.50; // bar joints: socket bore = spigot_od + this. Fit test said -0.6, but -0.7 on the real
                         // bar had to be sanded a lot (the spigot tops a tall tower and prints fat): -0.5
// ---- drop tee ----------------------------------------------------------
drop            = 25.0;  // plug centreline to bar centreline, mm (how much lower). User 2026-11-18: 60 -> 15 -> 25
riser_od        = 16.0;
riser_id        = 11.0;
arm_left        = 508.0; // tee centre to the left cap: 20 in (user, 2026-11-18)
arm_right       = 152.4; // tee centre to the right cap: 6 in (user, 2026-11-18)
// Which way the plug points, facing the tank: +1 = right, -1 = left. The old
// bar ran toward the long (left) side, so its fitting opens left and the
// plug points RIGHT into it. Flip if the old bar ran right.
plug_dir        = 1;
seg_max         = 320.0; // longest segment body (K2 Plus 350 incl. spigot)
// ---- bar ---------------------------------------------------------------
bar_od          = 16.0;  // user: tubes no thicker than 16-17 mm
bar_id          = 12.0;
spigot_len      = 14.0;  // joint depth. 25 -> 14 (2026-11-19): shorter lever, less to break, smaller nozzle gap
spigot_od       = 12.4;  // same as the old bar's plug: one fit for every joint
spigot_id       = 8.0;   // 9 -> 8: 2.2 mm wall instead of 1.7 (L1's spigot snapped)
spigot_lead     = 0.4;   // tip is this much smaller: starts easily, tightens as it seats
root_fillet     = 2.5;   // cone at the spigot root (16 -> spigot_od): no sharp corner for the layers to
                         // snap at; the socket mouth is coned to match so the joint closes flush
cap_t           = 3.0;   // end cap thickness on the last segment
// ---- nozzles -----------------------------------------------------------
hole_pitch      = 11.0;  // mm between nozzles: the old bar's spacing, calipers (user)
hole_d_near     = 1.6;   // bore nearest the feed. Small because there are many: each arm's
                         // total nozzle area stays under the 12 mm bore's 113 mm2, so the far
                         // nozzles are not starved. Drill out with a 1.6 mm bit if any print shut.
hole_d_far      = 1.9;   // bore farthest from the feed (L2 is fed through the 8 mm spigot bore)
nozzle_len      = 6.0;   // how far a nozzle stands out of the bar
nozzle_wall     = 1.2;   // 3 perimeters
hole_margin     = 2.4;   // keep nozzles this far from a joint. Nozzles sit on ONE pitch from the tee
                         // across all segments, so a joint costs one or two, not a 55 mm gap
hole_aim        = 10;    // degrees above horizontal (the "slightly up" ripple)
// Stretches with NO nozzles, in mm from the tee centre, per arm -- e.g.
// skip_left = [[300, 360]] where a heater or probe sits.
skip_left  = [];
skip_right = [];
// ---- clip --------------------------------------------------------------
clip_w          = 12.0;
clip_t          = 2.4;
keyhole_head_d  = 9.0;   // suction-cup head
keyhole_neck_w  = 4.5;   // suction-cup neck
$fn = 96;

eps = 0.01;
// Tee body wide enough to carry nozzles at 0 and +/- one pitch (stub + margin).
tee_body = max(riser_od / 2 + 4, hole_pitch + hole_margin + 0.6);
tee_half = tee_body + root_fillet + spigot_len;      // tee centre to a spigot tip
// Each arm is split into equal segments no longer than seg_max.
function n_segs(arm) = ceil((arm - tee_body) / seg_max);
// Joints (x from the tee centre, where a segment's socket face sits). A
// joint's dead zone (hole_margin + fillet + socket + hole_margin = 21.3 mm,
// under two pitches) is centred on one nozzle position, so each joint costs
// exactly that one nozzle and the spacing either side stays 11 mm.
function joint(arm, k) =
    k == 0 ? tee_body :
    k >= n_segs(arm) ? arm :
    hole_pitch * round((tee_body + k * (arm - tee_body) / n_segs(arm) + (spigot_len + root_fillet) / 2) / hole_pitch)
        - (spigot_len + root_fillet) / 2;
function seg_len(arm, i = 0) = joint(arm, i + 1) - joint(arm, i);
// Bore grows with distance from the tee (x in mm from the tee centre),
// scaled to the LONGER arm so both arms use the same size at the same
// distance and the short arm does not get the far-end bores.
arm_max = max(arm_left, arm_right);
function hole_d(x, arm) = hole_d_near + (hole_d_far - hole_d_near) * x / arm_max;
function skipped(x, sk) = len([for (s = sk) if (x >= s[0] && x <= s[1]) 1]) > 0;

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

// One arm segment, standing on its socket end (z = 0 is the tee side).
// arm = arm length, sk = its skip list, i = 0..n-1. Its socket end sits
// x0 = joint(arm, i) from the tee centre.
module nozzle_at(z) {
    translate([0, 0, z]) rotate([0, 0, hole_aim]) children();
}
module segment(arm, sk, i) {
    n = n_segs(arm); L = seg_len(arm, i);
    last = (i == n - 1);
    x0 = joint(arm, i);
    // Nozzles on one pitch counted from the tee centre, so spacing carries
    // across joints; only those inside the socket or within hole_margin of a
    // joint are left out.
    zlo = spigot_len + root_fillet + hole_margin;
    zhi = L - hole_margin - (last ? cap_t : 0);
    zs = [for (k = [ceil((x0 + zlo) / hole_pitch) : floor((x0 + zhi) / hole_pitch)]) k * hole_pitch - x0];
    difference() {
        union() {
            tube(bar_od, bar_id, L);
            if (!last)   // filleted root, then the tapered spigot into the next socket
                translate([0, 0, L - eps]) difference() {
                    union() {
                        cylinder(d1 = bar_od, d2 = spigot_od, h = root_fillet + eps);
                        translate([0, 0, root_fillet])
                            cylinder(d1 = spigot_od, d2 = spigot_od - spigot_lead, h = spigot_len);
                    }
                    translate([0, 0, -eps]) cylinder(d = spigot_id, h = root_fillet + spigot_len + 3 * eps);
                }
            for (z = zs) if (!skipped(x0 + z, sk))
                nozzle_at(z) translate([0, bar_id / 2, 0])
                    teardrop_stub(hole_d(x0 + z, arm) + 2 * nozzle_wall, (bar_od - bar_id) / 2 + nozzle_len);
        }
        // socket: coned mouth that takes the previous spigot's root fillet
        // (also clears the first-layer squish that made the mouth tight),
        // then the friction bore
        translate([0, 0, -eps]) cylinder(d1 = bar_od - 1.2, d2 = spigot_od + fit_clear, h = root_fillet + eps);
        translate([0, 0, root_fillet - eps]) cylinder(d = spigot_od + fit_clear, h = spigot_len + 2 * eps);
        for (z = zs) if (!skipped(x0 + z, sk))
            nozzle_at(z) translate([0, bar_id / 4, 0])
                teardrop_y_from0(hole_d(x0 + z, arm), bar_od / 2 + nozzle_len + 1);
        // main bore, socket to the top of THIS segment only (it used to run on
        // through the spigot and leave it a 0.2 mm skin the slicer dropped);
        // starts 2 mm above the socket so a narrower lip stops the next
        // segment's spigot at full depth instead of letting it slide in
        translate([0, 0, root_fillet + spigot_len + 2]) cylinder(d = bar_id, h = L - root_fillet - spigot_len - 2 + eps);
        translate([0, 0, root_fillet + spigot_len - eps]) cylinder(d = spigot_id + 1, h = 2 + 3 * eps);
    }
    if (last)   // closed far end
        translate([0, 0, L - cap_t]) cylinder(d = bar_od, h = cap_t);
}

function tee_nozzles() = [for (x = [-hole_pitch, 0, hole_pitch])
    if (!skipped(abs(x), x < 0 ? skip_left : skip_right)) x];

// Drop tee, in tank orientation: tee run along x at z = 0, riser up to
// z = drop, elbow, plug pointing -x into the old fitting. Exported as is:
// tee run on the bed, tree supports under the plug arm.
module spigot_x(dir) {   // filleted root + tapered spigot from the tee body along +/-x
    rotate([0, dir * 90, 0]) translate([0, 0, tee_body - eps]) difference() {
        union() {
            cylinder(d1 = bar_od, d2 = spigot_od, h = root_fillet + eps);
            translate([0, 0, root_fillet])
                cylinder(d1 = spigot_od, d2 = spigot_od - spigot_lead, h = spigot_len);
        }
        translate([0, 0, -eps]) cylinder(d = spigot_id, h = root_fillet + spigot_len + 3 * eps);
    }
}
module droptee() {
    body = tee_body;                       // tee body half length
    rb = bar_od / 2;
    translate([0, 0, rb]) difference() {
        union() {
            rotate([0, 90, 0]) cylinder(d = bar_od, h = 2 * body, center = true);
            spigot_x(1); spigot_x(-1);
            // nozzles on the tee itself: centre and one pitch each side, so
            // the middle of the bar sprays (2026-11-19: "big gap in the middle")
            for (x = tee_nozzles()) translate([x, 0, 0]) rotate([hole_aim, 0, 0])
                translate([0, bar_id / 2, 0])
                    teardrop_stub(hole_d(abs(x), 0) + 2 * nozzle_wall, (bar_od - bar_id) / 2 + nozzle_len);
            cylinder(d = riser_od, h = drop);                         // riser
            translate([0, 0, drop]) sphere(d = riser_od);             // elbow
            translate([0, 0, drop]) rotate([0, plug_dir * 90, 0])
                cylinder(d = riser_od, h = inlet_stub);               // stub toward the fitting
            translate([plug_dir * (inlet_stub - eps), 0, drop]) rotate([0, plug_dir * 90, 0])
                cylinder(d = inlet_plug_od, h = inlet_plug_len);      // plug
        }
        rotate([0, 90, 0]) cylinder(d = bar_id, h = 2 * body - 4, center = true);   // stops 2 mm short each side so the spigot roots stay full wall
        rotate([0, 90, 0]) cylinder(d = spigot_id, h = 2 * tee_half + 2, center = true);  // open through to the spigots
        for (x = tee_nozzles()) translate([x, 0, 0]) rotate([hole_aim, 0, 0])
            translate([0, bar_id / 4, 0]) teardrop_y_from0(hole_d(abs(x), 0), bar_od / 2 + nozzle_len + 1);
        cylinder(d = riser_id, h = drop);
        translate([0, 0, drop]) sphere(d = riser_id);
        translate([0, 0, drop]) rotate([0, plug_dir * 90, 0]) cylinder(d = inlet_plug_id, h = inlet_stub + inlet_plug_len + 1);
        // lead-in chamfer on the plug tip
        translate([plug_dir * (inlet_stub + inlet_plug_len + eps), 0, drop]) rotate([0, -plug_dir * 90, 0])
            difference() {
                cylinder(d = inlet_plug_od + 2, h = 1);
                cylinder(d1 = inlet_plug_od - 1, d2 = inlet_plug_od, h = 1);
            }
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

// Labelled tab joined to a ring of outer diameter od: a flat tab off one
// side with the number raised on it, so the label stays with the ring.
module label_tab(od, label) {
    tl = 17; tw = 9; tt = 1.6;     // tab: 17 mm out from the ring, 9 mm wide
    translate([od / 2 - 1, -tw / 2, 0]) {
        cube([tl + 1, tw, tt]);
        translate([1 + tl / 2, tw / 2, tt - eps]) linear_extrude(0.8)
            text(label, size = 4.2, halign = "center", valign = "center");
    }
}
// "9" -> "9.0", "12.5" stays: every label has one decimal so 6/9 and 1/7
// cannot be mistaken and the labels line up.
function mm(d) = d == floor(d) ? str(d, ".0") : str(d);

// Test rings: slide over the dry locked pipe; the one that goes on with a
// firm push and stays put sets inlet_plug_od. Each ring carries its bore (mm)
// on a tab.
gauge_sizes = [8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0, 13.5, 14.0, 14.5, 15.0];
module gauge() {
    for (k = [0 : len(gauge_sizes) - 1]) {
        d = gauge_sizes[k];
        translate([(k % 5) * 44, floor(k / 5) * 26, 0]) {
            tube(d + 5, d, 5);
            label_tab(d + 5, mm(d));
        }
    }
}

// Joint fit test: one tapered spigot and short sockets at the fit_clear
// values below, each socket carrying its number on a tab. The socket that
// pushes on firmly and holds when you shake it is the fit_clear to use.
// Print standing, like the segments.
// Round 1 (0.0 / 0.1 / 0.2) were ALL loose on the K2 Plus in PETG
// (2026-11-18): it prints holes oversize, so round 2 goes negative.
fit_tests = [-0.1, -0.2, -0.3, -0.4, -0.5, -0.6];
module fittest() {
    difference() {
        cylinder(d1 = spigot_od, d2 = spigot_od - spigot_lead, h = spigot_len);
        translate([0, 0, -eps]) cylinder(d = spigot_id, h = spigot_len + 2 * eps);
    }
    for (k = [0 : len(fit_tests) - 1])
        translate([(k % 2) * (bar_od + 26), (floor(k / 2) + 1) * (bar_od + 6), 0]) {
            difference() {
                cylinder(d = bar_od, h = spigot_len + 2);
                translate([0, 0, -eps]) cylinder(d = spigot_od + fit_tests[k], h = spigot_len + 3);
            }
            label_tab(bar_od, mm(fit_tests[k]));
        }
}

module arm(len, sk, dir) {   // dir +1 = right (+x), -1 = left
    n = n_segs(len);
    for (i = [0 : n - 1])
        translate([dir * joint(len, i), 0, bar_od / 2])
            rotate([0, dir * 90, 0]) color(i % 2 ? "lightgreen" : "khaki") segment(len, sk, i);
}
module assembly() {
    color("lightblue") droptee();
    arm(arm_right, skip_right, 1);
    arm(arm_left, skip_left, -1);
}

if (part == "assembly") assembly();
else if (part == "droptee") droptee();
else if (part == "L1") segment(arm_left, skip_left, 0);
else if (part == "L2") segment(arm_left, skip_left, 1);
else if (part == "L3") segment(arm_left, skip_left, 2);
else if (part == "R1") segment(arm_right, skip_right, 0);
else if (part == "R2") segment(arm_right, skip_right, 1);
else if (part == "R3") segment(arm_right, skip_right, 2);
else if (part == "clip") clip();
else if (part == "gauge") gauge();
else if (part == "fittest") fittest();
