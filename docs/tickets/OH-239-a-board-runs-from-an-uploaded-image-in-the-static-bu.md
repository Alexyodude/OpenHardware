---
id: OH-239
title: A board runs from an uploaded image in the static build, and the page says
  compiling needs the server
status: done
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

**Note 2026-10-16:** Done 2026-10-16. page() now applies ADAPTATIONS, each anchor asserted exactly once: a notice above the toolbar (where it runs, what it cannot do, the server command, and #inpage-status, which transport.js fills: Ready: nothing you load leaves this tab), inpage/inpage.css after emulator.css, #sketch-build disabled in the HTML with its reason beside it, and the transport before emulator.js. tests/webui/test_site_browser.py drives build/site in Chromium from a bare file server: Sum 1 to 10 halts with AX=0037; an uploaded hello.bin on XIAO-RP2040-DIP prints hello, world (1.2M instructions at about 148k/s); an uploaded blink.bin on the Arduino Uno shows PB5 high and low through the page's own fetch; Build is disabled; every request stays on the site (22). Each seen red: Build enabled, /api not routed, the clock module missing, an outside image added. The blink test first ended its wait on any two states and once saw input then high; it now waits for high and low. Screenshots in .omc/artifacts/static-site/. Left: on a picker change emulator.js's reflectBuildability retitles the disabled button 'no compile recipe ... See webui/compile.py's RECIPES', untrue in a tab though the visible line beside it is right; OH-244 reworks the button for the browser compiler. Passes build_site.py, test_site_build.py and test_site_browser.py on to OH-240 in turn.
