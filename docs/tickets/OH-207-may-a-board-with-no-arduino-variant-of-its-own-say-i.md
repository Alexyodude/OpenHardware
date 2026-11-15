---
id: OH-207
title: May a board with no Arduino variant of its own say it runs, on an image built
  for its chip's generic variant with the pin named from the board's own netlist?
status: open
priority: P2
created: '2026-10-08'
---

A decision for the user, not work for a session: filed so it is on the board rather than buried in docs/superpowers/plans/2026-10-08-intake.md section 7. It claims no files on purpose -- rules/board-claims.md is edited by live board tickets, and claiming it here would block them.

The question. OH-174's layer 3 reads pins "from a vendor's board-support package", and a manifest row's own run claim (rules/board-claims.md sections 7 and 11) needs an image built against the board's own Arduino variant. That is right for the eleven vendor rows and it is a wall for the long tail: almost none of heypcb.ai's 11,030 GitHub KiCad boards (docs/research/heypcb/README.md) are a vendor's board with a variant. They are someone's keyboard or synth or robot controller built around a chip that already runs here.

For such a board the netlist already says which chip pin each header pad reaches (OH-178 traces it that way for the rows), and the chip's own generic variant can build the image. May a board say it runs on that evidence -- an image built for the chip's generic variant, its pin named from the board's own netlist, watched toggling the pad the netlist says -- or does it stay at three layers until someone writes a variant for it?

It should be decided before OH-205's slice S5, whose histogram counts boards that S1-S3 can describe and this rule cannot yet promote. It does not block S1 (OH-206).
