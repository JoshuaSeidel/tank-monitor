// Fit gauge -- find the real board width and thickness by trying them.
//
// Six pockets, 21.0 to 23.5mm in 0.5mm steps, each stamped with its size.
// Slide the board into each. The one that grips lightly without force is
// your number; put it in tank-monitor-case.scad as pcb_w and the design
// is correct by measurement rather than by estimate.
//
// Prints in about five minutes. No supports.

widths = [21.0, 21.5, 22.0, 22.5, 23.0, 23.5];

slot_l   = 10;    // how far the board slides in
depth    = 8;     // pocket depth -- deeper than any plausible board stack
wall     = 1.6;
base     = 1.2;
gap      = 3;     // between pockets
label_h  = 0.6;

$fn = 24;

module pocket(w, label) {
  outer_w = w + 2 * wall;
  difference() {
    cube([slot_l + wall, outer_w, base + depth]);
    // the pocket itself, open at +X so the board slides in
    translate([-0.01, wall, base])
      cube([slot_l + 0.02, w, depth + 0.01]);
    // size stamped into the base, readable from below
    translate([slot_l / 2 + wall / 2, outer_w / 2, -0.01])
      linear_extrude(label_h + 0.01)
        text(label, size = 3.2, halign = "center", valign = "center");
  }
}

// Lay the pockets out and tie them together with a spine, so it prints and
// handles as one comb rather than six pieces to lose on the bench.
function y_at(i) = (i == 0) ? 0 : y_at(i - 1) + widths[i - 1] + 2 * wall + gap;

span = y_at(len(widths) - 1) + widths[len(widths) - 1] + 2 * wall;

for (i = [0 : len(widths) - 1])
  translate([0, y_at(i), 0]) pocket(widths[i], str(widths[i]));

// spine along the closed end
translate([-wall, 0, 0]) cube([wall, span, base + depth]);
