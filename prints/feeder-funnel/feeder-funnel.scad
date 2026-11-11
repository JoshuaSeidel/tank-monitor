// Feeder funnel for the 75 gal: guides food from the MA-Feeder into the tank.
// Outside dimensions as measured: 11 mm across the top, 9.5 mm across the
// bottom, 16 mm tall. Print in PETG as modelled, narrow end on the bed: the
// taper is under 3 degrees, so it needs no supports. 0.2 mm layers,
// 3+ walls so the 1.2 mm wall prints solid.

top_od    = 11.0;   // outside diameter at the feeder end
bottom_od = 9.5;    // outside diameter at the tank end
height    = 16.0;
wall      = 1.2;    // 3 x 0.4 mm perimeters
$fn = 96;

difference() {
    cylinder(h = height, d1 = bottom_od, d2 = top_od);
    // Bore follows the outside taper, open at both ends.
    translate([0, 0, -0.01])
        cylinder(h = height + 0.02, d1 = bottom_od - 2 * wall, d2 = top_od - 2 * wall);
}
