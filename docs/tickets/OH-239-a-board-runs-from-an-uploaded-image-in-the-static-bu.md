---
id: OH-239
title: A board runs from an uploaded image in the static build, and the page says
  compiling needs the server
status: open
priority: P1
created: '2026-10-16'
touches:
- webui/static/inpage/inpage.css
- tests/webui/test_site_browser.py
- tools/build_site.py
- tests/webui/test_site_build.py
- webui/static/inpage/worker.js
avoid:
- webui/static/emulator.js
- webui/static/emulator.html
- webui/emulator_server.py
- webui/api.py
---

Slice 2 of docs/superpowers/plans/2026-10-16-static-site.md. The static build already answers the board routes (test_site_pyodide runs the RP2040 and the Uno under node); this slice is what the PAGE shows. tools/build_site.py's page() puts a notice above the toolbar saying the copy runs in the browser with no server and cannot compile a sketch (with #inpage-status, where transport.js reports the runtime starting), disables #sketch-build in the HTML itself and says why beside it -- emulator.js greys it only after /api/board/pins answers, which it refuses at first load, so a script-free page offered a Build button whose every press is refused. emulator.html and emulator.js are not edited: the build adapts a copy, each adaptation's anchor asserted exactly once. Verify: tests/webui/test_site_browser.py drives build/site in Chromium -- a sample halts with AX=0037, an uploaded tests/cortexm0/uart/hello.bin on XIAO-RP2040-DIP prints hello, world, an uploaded tests/avr/blink/blink.bin on the Arduino Uno shows PB5 both high and low, the Build button is disabled, and no request leaves the site. Takes tools/build_site.py, tests/webui/test_site_build.py and webui/static/inpage/worker.js from OH-238 once it is done.
