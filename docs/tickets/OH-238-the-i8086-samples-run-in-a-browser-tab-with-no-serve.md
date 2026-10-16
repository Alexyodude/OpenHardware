---
id: OH-238
title: 'The i8086 samples run in a browser tab with no server: the cores as wasm side
  modules under Pyodide, /api answered by a Worker'
status: done
priority: P1
created: '2026-10-16'
touches:
- webui/inpage.py
- webui/static/inpage/transport.js
- webui/static/inpage/worker.js
- tools/build_site.py
- tools/build_core.py
- tests/webui/test_inpage.py
- tests/webui/test_site_build.py
- tests/webui/test_site_pyodide.py
- docs/superpowers/plans/2026-10-16-static-site.md
avoid:
- webui/emulator_server.py
- webui/api.py
- webui/static/emulator.js
- webui/static/board3d.js
- webui/static/board3d-panel.js
---

The owner, 2026-10-16: 'openhardware is also not accesable in webatm?', 'openhardware could run client side right?'. Today the emulator page runs only from webui/emulator_server.py on 127.0.0.1:8088. Slice 1 of docs/superpowers/plans/2026-10-16-static-site.md: the thin end-to-end path. tools/build_site.py compiles each core/<core> to a wasm side module with emscripten 5.0.3 (Pyodide 314.0.7's), vendors the pinned Pyodide runtime, zips the Python the page runs with the cores under build/lib/, and writes build/site/index.html from emulator.html with webui/static/inpage/transport.js loaded first. transport.js answers fetch('/api/...') from a module Worker (inpage/worker.js) that boots Pyodide and calls webui.inpage.InPage.answer, which calls the UNCHANGED emulator_server.handle_api; core/*/abi.py load the .so through ctypes unchanged. Done when: python tools/build_site.py builds; python -m http.server -d build/site serves a page whose sample programs run and match the server's registers; test_inpage holds InPage to the loopback server request for request; test_site_pyodide boots the built bundle alone under node and runs all six samples. Not this slice: boards (OH-239), subpath and network log (OH-240), licences (OH-241), Pages (OH-242), version (OH-243). emulator_server.py, api.py, emulator.js, board3d*.js are other tickets' and are not edited.

**Note 2026-10-16:** Done 2026-10-16. python tools/build_site.py builds build/site (16,805,785 bytes: page 2.69 MB, Pyodide 314.0.7 runtime 13.53 MB, openhardware.zip 0.58 MB with the four cores as wasm side modules, 89 KB of it). In Chromium from python -m http.server -d build/site: the samples list in 1.9 s and Sum 1 to 10 halts after 24 steps with AX=0037, every request to the serving origin. test_inpage holds InPage to the loopback server request for request (8 tests); test_site_pyodide boots the built bundle alone under node and matches the native build on all six samples, the RP2040 hello.bin and the Uno blink (3); test_site_build covers page(), core_sources, BUNDLE, the zip's dates, the lock and the runtime's names (14); each seen red under a mutation. Full suite 3288 passed, 57 skipped; every checker OK. Left to OH-239: the page said nothing about where it ran, and Build and run stayed enabled at first load because emulator.js greys it only after /api/board/pins answers. Handler._api could call InPage.route once OH-161 frees emulator_server.py, and the restated mapping would go.
