---
id: OH-243
title: 'OpenHardware 0.1.0: a version, stamped into the static page, and its release
  notes'
status: done
priority: P1
created: '2026-10-16'
touches:
- pyproject.toml
- docs/releases/0.1.0.md
- README.md
- tools/build_site.py
- tests/webui/test_site_build.py
- tests/webui/test_site_browser.py
- tools/site_licences.py
- tests/rules/test_site_licences.py
- .github/workflows/pages.yml
- docs/releases/publishing.md
---

Slice 6 of docs/superpowers/plans/2026-10-16-static-site.md. The owner: 'make some release along with it'. pyproject.toml gains [project] name openhardware, version 0.1.0; the build stamps that version and the commit it was built from into the page's notice; docs/releases/0.1.0.md says what this first release is, what the static build cannot do, its size, and the operator's push, tag and Pages commands; README gains a short section pointing at the hosted page and the release. Nothing is pushed or tagged here. Verify: the built page's notice says 0.1.0 and the commit; test_site_build holds the stamp to pyproject.toml. Takes tools/build_site.py and tests/webui/test_site_build.py in turn from OH-241.

**Note 2026-10-16:** Done in 318d8e3 and ad4e62a. pyproject.toml [project] version 0.1.0; build_site stamps the notice 'This is OpenHardware 0.1.0, built from <12 hex>', adding 'with local changes' when a tracked file differs or a file the build ships is untracked; docs/releases/0.1.0.md is the public notes and docs/releases/publishing.md the operator's steps (kept apart because the notes become the release body); README points at the page. Reviewed by an opus code-reviewer and a security-reviewer (no critical/high/medium; four low); every should-fix and three low ones fixed in 318d8e3, the CSP filed as OH-246, the hosted build's missing parts as OH-245; a verifier passed every fix. Verified: a clean worktree of 318d8e3 built with only the workflow's pip packages stamps 'built from 318d8e3b4763', carries no user path in any core (-ffile-prefix-map), totals 16,979,662 bytes with no models, and its site tests give 56 passed, 0 skipped; served from a subfolder, the i8086 sample halts with AX 0037, the RP2040 prints hello world, the Uno's PB5 goes high, Build is disabled, and 22 requests all stay on the site. The Uno blink test's 60 s bound failed once in the full suite under another session's build load; PB5 reads low first at the clock's sixth tick, replayed natively, and the bound is now 180 s. Mutations of version(), commit(), stamp(), the MIT checks and the notices each turned their test red. Nothing pushed, tagged or published.
