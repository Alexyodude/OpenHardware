---
id: OH-244
title: 'Build and run works in the static build: the sketch compiles in the browser
  tab, avr-gcc as WebAssembly, Uno first, the same bytes as the server'
status: open
priority: P1
created: '2026-10-16'
touches:
- tools/build_compiler.py
- tools/wasm_toolchain/**
- webui/static/compiler/**
- webui/static/inpage/compile.js
- tests/webui/test_compile_wasm.py
- tests/webui/test_compiler_page.py
- docs/superpowers/plans/2026-10-16-web-compile.md
- docs/research/web-compile/**
- tests/webui/compile_wasm_runner.mjs
- PROVENANCE.md
- tools/build_site.py
- tests/webui/test_site_build.py
- tests/webui/test_site_browser.py
- .github/workflows/pages.yml
avoid:
- webui/compile.py
- webui/emulator_server.py
- webui/api.py
- webui/inpage.py
- webui/static/emulator.js
- webui/static/emulator.html
- webui/static/inpage/transport.js
- webui/static/inpage/worker.js
---

The owner, 2026-10-16: 'CAN YOU MAKE IT SO WEB COMPILE IS POSSIBLE AND RUNNING?', then chose 'In the browser', with no server. Builds on the static build (OH-238..OH-243, T-62): the page's Build and run must work there without PlatformIO. avr-gcc 7.3.0 and binutils 2.26 -- the exact sources of Arduino's 7.3.0-atmel3.6.1-arduino7, whose executables are byte-identical to PlatformIO's toolchain-atmelavr 3.70300.220127 that webui/compile.py runs -- are compiled to WebAssembly by tools/wasm_toolchain/ (Docker, pinned emsdk), fetched only when Build is pressed and cached; the Arduino core objects are precompiled by the same wasm compiler at build time. webui/static/inpage/compile.js wraps fetch after transport.js: /api/board/compile runs the wasm compiler in its own Worker and, on success only, POSTs the image to the unchanged /api/board/load, so a failed build leaves the board unchanged and diagnostics keep their sketch.cpp:LINE. Same bytes as the server: tests/webui/test_compile_wasm.py builds the samples both ways and compares. Then SAMD21 the same way; RP2040 has no server recipe to match; ESP32 measured and, if it does not fit, those boards say to build locally. GCC is GPL and the Arduino cores LGPL: source offer and notices ship beside the binaries and PROVENANCE.md records it (borrowed when free). tools/build_site.py is OH-238's chain's until OH-243 is done; until then the page is tested through a post-step over build/site. webui/compile.py, the server's compile path, is not changed. No push, tag or publish.

## Progress, 2026-10-16

The Uno is done: in the post-step's `build/site-with-compiler/` served as plain files, Blink
builds in the tab (6.3 s the first time in headed Chrome, 21.1 MB fetched;
0.1 s after), PB5 changes every 8,000,000 instructions at delay(500) and
every 4,000,000 at delay(250), a syntax error is reported at
`sketch.cpp:2:23` with its line quoted and the board left as it was, and no
request leaves the site. Five samples are the server's bytes. The toolchain
rebuilds from nothing in Docker, byte for byte. Measurements:
`docs/research/web-compile/README.md`.

Since OH-243 handed it over (3ea2e1f), `tools/build_site.py` builds the
compiler into `build/site/compiler/` itself, and the post-step and
`build/site-with-compiler/` are gone. A board the copy has no compiler for
has Build off and says to use the local server.

Left, in order:

- The SAMD21, the same way: arm-none-eabi GCC 12.3.1 to WebAssembly. The
  server's is xPack's build of it, not Arm's binaries, whose Cortex-M0+
  libraries differ in bytes; so xPack's is the one to match.
- The ESP32s turned out to need no framework worth the name -- the
  repository's own 128 KB core, bare metal -- so they fit, and need only a
  riscv32-esp GCC 8.4.0 built the same way. They say to build locally until
  then.
- The RP2040 has no server recipe, so there is nothing to match.
- PROVENANCE.md goes back to OH-163's touches once this ticket's last licence
  record is in, the SAMD21's.
