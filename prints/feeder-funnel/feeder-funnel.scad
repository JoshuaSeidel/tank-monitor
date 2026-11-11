// Feeder funnel for the 75 gal: guides food from the MA-Feeder into the tank.
// Outside dimensions: 25 mm across the flared top, 19 mm across the
// bottom, 19 mm tall (v3, 2026-11-11; v2 15/13/20, v1 11/9.5/16). Print in PETG as modelled, narrow end on the bed: the
// wall flares about 9 degrees off vertical, so it needs no supports. 0.2 mm layers,
// 3+ walls so the 1.2 mm wall prints solid.

top_od    = 25.0;   // outside diameter at the feeder end
bottom_od = 19.0;   // outside diameter at the tank end
height    = 19.0;
wall      = 1.2;    // 3 x 0.4 mm perimeters
$fn = 96;

difference() {
    cylinder(h = height, d1 = bottom_od, d2 = top_od);
    // Bore follows the outside taper, open at both ends.
    translate([0, 0, -0.01])
        cylinder(h = height + 0.02, d1 = bottom_od - 2 * wall, d2 = top_od - 2 * wall);
}
