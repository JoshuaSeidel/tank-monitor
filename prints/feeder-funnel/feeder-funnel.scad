// Feeder funnel for the 75 gal: guides food from the MA-Feeder into the tank.
// v6 (2026-11-11): a straight 19 mm tube with the top 10 mm flared out to
// 35 mm, 19 mm tall overall. (v5 flared over 6 mm, v4 to 25 mm, v3 plain 19->25 cone, v2 15/13/20,
// v1 11/9.5/16.) All diameters are OUTSIDE.
//
// Print in PETG UPSIDE DOWN: flip it so the 35 mm rim sits on the bed. The
// flare leans about 39 degrees off vertical - near the limit for printing outward
// without supports, but printed rim-down every layer is smaller than the
// one below it, so it needs no supports and the rim gets a flat, clean edge.
// 0.2 mm layers, 3+ walls so the 1.2 mm wall prints solid.

tube_od  = 19.0;   // outside diameter of the straight tube (tank end)
flare_od = 35.0;   // outside diameter at the top of the flare (feeder end)
height   = 19.0;   // overall height
flare_h  = 10.0;   // height of the flared section at the top
wall     = 1.2;    // 3 x 0.4 mm perimeters
$fn = 128;

tube_h = height - flare_h;
r_tube  = tube_od / 2;
r_flare = flare_od / 2;

// Half cross-section, revolved. On the steep flare a 1.2 mm HORIZONTAL wall
// would only be ~0.7 mm thick across the slope, so the flare's horizontal
// offset is widened to keep it 1.2 mm thick measured square to the wall.
flare_angle = atan((r_flare - r_tube) / flare_h);   // off vertical
wall_flare  = wall / cos(flare_angle);
rotate_extrude()
    polygon([
        [r_tube - wall,  0],
        [r_tube,         0],
        [r_tube,         tube_h],
        [r_flare,        height],
        [r_flare - wall_flare, height],
        [r_tube - wall,  tube_h],
    ]);
