---
id: OH-242
title: A v* tag builds the static site and deploys it to GitHub Pages
status: done
priority: P1
created: '2026-10-16'
touches:
- .github/workflows/pages.yml
---

Slice 5 of docs/superpowers/plans/2026-10-16-static-site.md. A v* tag (or a manual run) builds build/site on ubuntu-24.04 with the Emscripten tools/build_site.py names, runs the site's tests with skips counted as failures, and deploys the folder with actions/deploy-pages. Served at alexyodude.com/OpenHardware/ under the owner's user site's custom domain: no DNS change. The operator, not this ticket, enables Pages (source GitHub Actions), adds a v* tag rule to the github-pages environment, pushes and tags. Verify: the workflow's steps run locally in order; the tag check refuses a tag that is not v + pyproject's version.

**Note 2026-10-16:** Done. Verified locally, in a fresh venv holding only the two packages the workflow installs (pytest 9.0.2, Playwright 1.64.0): the Emscripten-version line prints 5.0.3 (emsdk has the tag 5.0.3), build_core and build_site succeed, and the site tests give 45 passed, 0 skipped. The tag step passes v0.1.0 and refuses v0.2.0 and a bare 0.1.0. The test step names shell: bash, because a step with no shell runs bash -e, which takes tee's status for the pipe's (shown: bash -e went on past 'false | tee'; -eo pipefail exited 1). Actions are on their Node 24 majors (checkout, setup-python and setup-node v7; upload-pages-artifact and deploy-pages v5, each the latest release): rules.yml's last run warned that checkout@v4 and setup-python@v5 are forced off Node 20. Not verified: anything on a GitHub runner, which only a tag or a manual run after the operator's two steps can show. A hosted build has no 3D models at all, since they are built per machine; shipping KiCad's bench parts from CI is a follow-up ticket.
