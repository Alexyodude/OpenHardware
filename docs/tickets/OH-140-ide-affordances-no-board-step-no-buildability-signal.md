---
id: OH-140
title: 'IDE affordances: no board step, no buildability signal, the sketch dies on
  reload'
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 API/IDE survey; affordance bundle.

  * BoardSession.step() exists and no route exposes it: a board cannot be
    single-stepped from the page while the 8086 can.
  * Nothing says which boards have a compile recipe; the picker offers Build
    on all 26 and 9 runnable boards 400 only after the attempt. Surface
    buildability in the catalogue JSON and grey the button.
  * The editor resets to DEFAULT_SKETCH on every reload; localStorage holds
    only the theme. Any crash or reload eats the sketch, unwarned. No build
    shortcut either.
  * words= peripheral-register watch: route, validation and a long docstring
    argument exist; the UI never sends it.

DONE WHEN each affordance exists or its absence is stated on the page rather
than discovered by failure.
