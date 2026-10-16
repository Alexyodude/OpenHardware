---
id: OH-241
title: Only the 3D models whose licence allows it ship in the static build, each with
  its notice, and the runtime's licences ship beside it
status: done
priority: P1
created: '2026-10-16'
touches:
- tools/site_licences.py
- tests/rules/test_site_licences.py
- rules/licence-hygiene.md
- PROVENANCE.md
- tools/build_site.py
- tests/webui/test_site_build.py
- tests/webui/test_site_browser.py
---

Slice 4 of docs/superpowers/plans/2026-10-16-static-site.md. The owner: 'Ship only files whose licence allows it; check each 3D model in webui/static/models and update PROVENANCE.md.' The models are gitignored and built locally, so a build that has them must decide per file. tools/site_licences.py holds one row per .glb: shipped (with the licence the shipped file is under and whose work it is) or withheld (and why). Withheld: every Seeed model (their licence is OH-234's open question for the owner), the PCBCUPID Glyph C3/C6 (licence only stated in a README, not opened), the two Olimex boards (CERN-OHL; PROVENANCE 2g leaves them to the owner). Shipped: the composed boards whose board file is opened CC BY-SA or MIT, and KiCad's parts/*.glb, CC BY-SA 4.0; the two drawing Adafruit_CAD_Parts carry its MIT notice. The build writes a filtered models/index.json always (no 404 when none exist, as on CI), models/NOTICE.md, and a NOTICE for the runtime it vendors (Pyodide MPL-2.0, CPython PSF, Emscripten's libraries) from pinned, sha256-checked licence texts. An unlisted model fails the build by name. Verify: python tools/build_site.py prints shipped and withheld per model; tests/rules/test_site_licences.py. Borrows PROVENANCE.md from OH-163 and tools/build_site.py from OH-240.

**Note 2026-10-16:** Borrows PROVENANCE.md from OH-163 (2026-10-16); returns it on close, to OH-244 if that is still waiting, else to OH-163.

**Note 2026-10-16:** Done. tools/site_licences.py holds a row per board model and decides each: 9 boards ship (5 SparkFun/Arduino board files opened CC BY-SA, 3 drawing Adafruit_CAD_Parts with its MIT text whole, PCBCUPID's Glyph Mini 2040 with its MIT text), the rest withheld with the reason printed; KiCad parts ship. The notices are NOTICE.txt, not NOTICE.md as the body says: a server types .md as text/markdown and a browser offers it as a download rather than showing it. Every pinned file is cached under its sha256 prefix, because three of them are called LICENSE. A local build with models: 35,320,220 bytes, models 18,341,921 of it; a build with none, as CI's is, writes an empty models/index.json so the page's request is answered. Verified: 59 site tests, mutations of models() and runtime_notice() each red (index not written, everything copied, MIT text dropped, a missing Emscripten text skipped, Emscripten's texts not read), and the two browser tests red with models/index.json or NOTICE.txt deleted from the build. PROVENANCE.md is free on close: OH-244 takes it if still waiting, else it goes back to OH-163.
