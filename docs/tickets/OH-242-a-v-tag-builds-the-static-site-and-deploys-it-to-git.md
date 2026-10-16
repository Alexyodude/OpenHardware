---
id: OH-242
title: A v* tag builds the static site and deploys it to GitHub Pages
status: open
priority: P1
created: '2026-10-16'
touches:
- .github/workflows/pages.yml
---

Slice 5 of docs/superpowers/plans/2026-10-16-static-site.md. A v* tag (or a manual run) builds build/site on ubuntu-24.04 with the Emscripten tools/build_site.py names, runs the site's tests with skips counted as failures, and deploys the folder with actions/deploy-pages. Served at alexyodude.com/OpenHardware/ under the owner's user site's custom domain: no DNS change. The operator, not this ticket, enables Pages (source GitHub Actions), adds a v* tag rule to the github-pages environment, pushes and tags. Verify: the workflow's steps run locally in order; the tag check refuses a tag that is not v + pyproject's version.
