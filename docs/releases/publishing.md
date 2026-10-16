# Publishing a release

For the operator. Nothing in this repository pushes, tags, enables Pages or
publishes a release on its own: each step below is run by hand, after the
secret scan and the owner's yes. A tag starts `.github/workflows/pages.yml`,
which builds the static site, checks it, and deploys it to
https://alexyodude.com/OpenHardware/.

Release notes for each version are `docs/releases/<version>.md`; that file is
the release's body on GitHub, so it is written for whoever opens the page.

## 0.1.0, the first

Steps 2 and 3 are once, for the repository; every later release is steps 1, 4,
5 and 6 with its own version.

```bash
# 1. The branch, with the release's commits.
git push origin master

# 2. Pages, built by the workflow rather than from a branch.
gh api -X POST repos/Alexyodude/OpenHardware/pages -f build_type=workflow
gh api repos/Alexyodude/OpenHardware/pages --jq '.build_type + " " + .html_url'
#    -> workflow https://alexyodude.com/OpenHardware/

# 3. Let a v* tag deploy. The deploy job runs in the github-pages
#    environment, which allows only what it is told to. PUT makes the
#    environment if it is not there yet, and sets it to named rules.
gh api -X PUT repos/Alexyodude/OpenHardware/environments/github-pages --input - <<'EOF'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
EOF
gh api -X POST repos/Alexyodude/OpenHardware/environments/github-pages/deployment-branch-policies \
  -f name=master -f type=branch
gh api -X POST repos/Alexyodude/OpenHardware/environments/github-pages/deployment-branch-policies \
  -f name='v*' -f type=tag
gh api repos/Alexyodude/OpenHardware/environments/github-pages/deployment-branch-policies \
  --jq '.branch_policies[] | .type + " " + .name'
#    -> branch master
#       tag v*
#    A 422 saying master already exists means step 2 had added it: fine.

# 4. The tag, which starts the workflow. The workflow refuses a tag that is
#    not "v" and pyproject.toml's version.
git tag -a v0.1.0 -m "OpenHardware 0.1.0"
git push origin v0.1.0
gh run list -R Alexyodude/OpenHardware -w Pages -L 3
#    The run for v0.1.0 is listed within a few seconds; watch it by its ID:
gh run watch -R Alexyodude/OpenHardware <run ID>

# 5. The page. Its notice must end with the tag's commit and nothing after:
git rev-parse --short=12 'v0.1.0^{commit}'
#    -> open https://alexyodude.com/OpenHardware/ and read
#       "This is OpenHardware 0.1.0, built from <those 12 digits>."

# 6. The release, once the page is right.
gh release create v0.1.0 -R Alexyodude/OpenHardware --verify-tag \
  --title "OpenHardware 0.1.0" --notes-file docs/releases/0.1.0.md
```

No DNS changes: `alexyodude.com` is the custom domain of the user site
`Alexyodude.github.io`, and a project site is served under it at
`/OpenHardware/`.

## If the run fails

The page is not replaced: the deploy job runs only after the build job
passes. Read the failed step (`gh run view <run ID> --log-failed`), fix it on
master, and either run the workflow by hand from master -- `gh workflow run
Pages -R Alexyodude/OpenHardware --ref master`, which publishes a page whose
notice names that commit -- or move the tag to the fixed commit, which is the
owner's call, since a tag others may have fetched then changes under them.

## For the owner, not a step

`Alexyodude.github.io` does not enforce HTTPS (`https_enforced` is false on
its Pages settings, read 2026-10-16), so this page, which runs code, is also
served over plain HTTP. Turning that on is a setting of the user site's
repository, not a DNS change.
