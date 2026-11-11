// Feeder funnel for the 75 gal: guides food from the MA-Feeder into the tank.
// v4 (2026-11-11): a straight 19 mm tube with the top 6 mm flared out to
// 25 mm, 19 mm tall overall. (v3 was a plain 19->25 mm cone, v2 15/13/20,
// v1 11/9.5/16.) All diameters are OUTSIDE.
//
// Print in PETG as modelled, narrow end on the bed. The flare leans about
// 27 degrees off vertical, well inside what prints without supports.
// 0.2 mm layers, 3+ walls so the 1.2 mm wall prints solid.

tube_od  = 19.0;   // outside diameter of the straight tube (tank end)
flare_od = 25.0;   // outside diameter at the top of the flare (feeder end)
height   = 19.0;   // overall height
flare_h  = 6.0;    // height of the flared section at the top
wall     = 1.2;    // 3 x 0.4 mm perimeters
$fn = 128;

tube_h = height - flare_h;
r_tube  = tube_od / 2;
r_flare = flare_od / 2;

// Half cross-section, revolved: the wall follows the outside profile at a
// constant horizontal thickness, so the bore keeps the same shape.
rotate_extrude()
    polygon([
        [r_tube - wall,  0],
        [r_tube,         0],
        [r_tube,         tube_h],
        [r_flare,        height],
        [r_flare - wall, height],
        [r_tube - wall,  tube_h],
    ]);
