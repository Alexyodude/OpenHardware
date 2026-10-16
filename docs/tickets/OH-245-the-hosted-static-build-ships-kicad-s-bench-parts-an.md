---
id: OH-245
title: The hosted static build ships KiCad's bench parts, and its empty bench stops
  telling a visitor to run a tool
status: open
priority: P2
created: '2026-10-16'
---

Found while closing OH-242. The 3D models are gitignored and built per machine, so the build GitHub Pages serves has none: every board draws as its footprint, and the bench's part tree says 'No part models here. Run tools/import_3d_model.py --parts to fetch them.' (webui/static/board3d-panel.js renderTree), which a visitor to a hosted page cannot do. KiCad's parts may ship (CC BY-SA 4.0, tools/site_licences.py), so the workflow could build them: cadquery-ocp 8.0.1.1.0 publishes a cp314 manylinux wheel, and tools/import_3d_model.py --parts fetches from KiCad's GitLab. Not done in OH-242 because nothing here could run it: no local Python has OCP, and whether the bench's parts work in the static build at all (circuit.js through the in-page /api) has not been checked. Verify: a CI-equivalent build (fresh venv, the workflow's packages plus cadquery-ocp) ships models/parts/*.glb, test_site_browser places a part on the bench, and with no parts the static page's hint does not name a tool. The hint's wording is board3d-panel.js's or a build_site adaptation, claimed when taken.

**Note 2026-10-16:** Claims nothing until taken: .github/workflows/pages.yml is OH-243's while it fixes what the release review found; this ticket claims it, and whatever carries the bench hint, when it starts.
