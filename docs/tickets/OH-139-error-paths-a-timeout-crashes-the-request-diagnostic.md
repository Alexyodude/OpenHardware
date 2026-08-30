---
id: OH-139
title: 'Error paths: a timeout crashes the request, diagnostics leak paths, query
  errors name no field'
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 API/IDE survey; error-path bundle.

  * subprocess.TimeoutExpired and a missing objcopy are caught by NOTHING in
    the handler's list, so the request dies with no response and the build
    button silently reverts. (.claude/CLAUDE.md rule 9.)
  * Link diagnostics replace only the sketch path: absolute toolchain and
    temp paths leak, and on SAMD21 eight nosys.specs warnings precede the one
    line that matters, none folded by the renderer.
  * Query-param errors return bare int() messages naming no field --
    "invalid literal for int() with base 0: zz" -- while the body path
    already does this right and the docstring promises reasons throughout.
  * The client parses the JSON body BEFORE checking response.ok, so any
    non-JSON error (static 404 text/plain, unknown route) surfaces as a
    SyntaxError and the real status is lost.

DONE WHEN each has a named test: a timeout answers 500 with a reason, paths
are scrubbed, query errors name the field, and the client reports status
before parsing.
