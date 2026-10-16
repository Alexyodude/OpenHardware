---
id: OH-243
title: 'OpenHardware 0.1.0: a version, stamped into the static page, and its release
  notes'
status: open
priority: P1
created: '2026-10-16'
touches:
- pyproject.toml
- docs/releases/0.1.0.md
- README.md
---

Slice 6 of docs/superpowers/plans/2026-10-16-static-site.md. The owner: 'make some release along with it'. pyproject.toml gains [project] name openhardware, version 0.1.0; the build stamps that version and the commit it was built from into the page's notice; docs/releases/0.1.0.md says what this first release is, what the static build cannot do, its size, and the operator's push, tag and Pages commands; README gains a short section pointing at the hosted page and the release. Nothing is pushed or tagged here. Verify: the built page's notice says 0.1.0 and the commit; test_site_build holds the stamp to pyproject.toml. Takes tools/build_site.py and tests/webui/test_site_build.py in turn from OH-241.
