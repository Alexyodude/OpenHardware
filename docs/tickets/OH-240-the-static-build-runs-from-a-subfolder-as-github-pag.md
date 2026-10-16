---
id: OH-240
title: The static build runs from a subfolder, as GitHub Pages serves it, and no request
  leaves the site
status: done
priority: P1
created: '2026-10-16'
touches:
- tools/build_site.py
- webui/static/inpage/transport.js
- tests/webui/test_site_build.py
- tests/webui/test_site_browser.py
avoid:
- webui/static/emulator.js
- webui/static/emulator.html
- webui/static/board3d.js
- webui/static/board3d-panel.js
---

Slice 3 of docs/superpowers/plans/2026-10-16-static-site.md. GitHub Pages serves the site at alexyodude.com/OpenHardware/, a subfolder, and emulator.html loads /emulator.css, /emulator.js, /board3d-panel.js, /clock.js and its import map's /vendor/... from the root; board3d-panel.js and board3d.js fetch /models/... and import /board3d.js. page() rewrites the page's own references to relative ones (asserted, like OH-239's), adds import-map entries for the absolute module specifiers the scripts import, and transport.js sends any other same-origin absolute fetch to the site's folder. Verify: tests/webui/test_site_browser.py serves build/ so the site sits at /site/, runs a sample and a board there, and asserts every request stays under the site. Takes tools/build_site.py, webui/static/inpage/transport.js, tests/webui/test_site_build.py and tests/webui/test_site_browser.py in turn from OH-239.

**Note 2026-10-16:** Done 2026-10-16. page() makes the page's own references relative (emulator.css, emulator.js, board3d-panel.js, the inline import of clock.js, and the import map's vendor targets), and adds an import-map entry for /board3d.js, which board3d-panel.js imports from the root. transport.js sends a same-origin fetch outside the site's folder to that folder, which moves board3d.js's /models/... fetches; at a root nothing moves. test_site_browser now serves build/ so the site sits at /site/, and every request stays under it. Seen red: transport's move off (models/index.json at the root), the /board3d.js map entry gone (board3d.js at the root), and statically emulator.js absolute again and the map entry renamed. 29 site tests pass. models/index.json still answers 404 until OH-241 writes it. Passes build_site.py, test_site_build.py and test_site_browser.py on to OH-241.
