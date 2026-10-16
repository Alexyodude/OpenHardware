---
id: OH-240
title: The static build runs from a subfolder, as GitHub Pages serves it, and no request
  leaves the site
status: open
priority: P1
created: '2026-10-16'
avoid:
- webui/static/emulator.js
- webui/static/emulator.html
- webui/static/board3d.js
- webui/static/board3d-panel.js
---

Slice 3 of docs/superpowers/plans/2026-10-16-static-site.md. GitHub Pages serves the site at alexyodude.com/OpenHardware/, a subfolder, and emulator.html loads /emulator.css, /emulator.js, /board3d-panel.js, /clock.js and its import map's /vendor/... from the root; board3d-panel.js and board3d.js fetch /models/... and import /board3d.js. page() rewrites the page's own references to relative ones (asserted, like OH-239's), adds import-map entries for the absolute module specifiers the scripts import, and transport.js sends any other same-origin absolute fetch to the site's folder. Verify: tests/webui/test_site_browser.py serves build/ so the site sits at /site/, runs a sample and a board there, and asserts every request stays under the site. Takes tools/build_site.py, webui/static/inpage/transport.js, tests/webui/test_site_build.py and tests/webui/test_site_browser.py in turn from OH-239.
