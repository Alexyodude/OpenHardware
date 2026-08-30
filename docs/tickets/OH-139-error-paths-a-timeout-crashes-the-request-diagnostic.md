---
id: OH-139
title: 'Error paths: a timeout crashes the request, diagnostics leak paths, query
  errors name no field'
status: done
priority: P2
created: '2026-08-30'
touches:
- webui/compile.py
- webui/emulator_server.py
- webui/static/emulator.js
- tests/webui/test_compile.py
- tests/webui/test_emulator.py
- tests/webui/test_editor.py
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

---

**CLOSED 2026-08-30.** The four named tests exist and each fix rides an
existing rail rather than growing a new one.

  * **The timeout half arrived via OH-136**, and better than the ticket
    asked: `subprocess.TimeoutExpired` is a returncode-124 RESULT with the
    budget and the command named -- a 200 with `ok: false` and diagnostics,
    not the 500 this ticket would have settled for. What remained here was
    the missing TOOL: `FileNotFoundError` is now a 127 result naming the
    tool ("the compiler was found, so the toolchain package is
    incomplete"), where before it killed the request with no response.
  * **Paths are scrubbed to labels.** `_diagnostics` replaced only the
    sketch path; a link error led with the temp OBJECT path. The build
    directory becomes `<build>` and the PlatformIO packages root
    `<toolchain>`, both slash spellings, compiler's words intact.
  * **Query errors name the parameter.** `_query_int` mirrors the body
    path's `_int`/`_optional_int`: `at=zz` answers "at must be an integer,
    decimal or 0x hex, got 'zz'" instead of int()'s own message.
  * **The client reads the status before parsing.** A text/plain 404 or an
    unknown route surfaced as a SyntaxError from `response.json()`; `api()`
    now branches on `response.ok` first and parses the error body inside a
    try, so the status survives a non-JSON reply.

NOT built, and said so: folding the SAMD21's eight nosys.specs warnings is
renderer presentation, absent from the DONE WHEN, and left for a ticket of
its own if it earns one.

Five mutations, all killed: the tool handler deleted, 127 read as success,
the scrub loop deleted, the state route back to bare int(), and the client
re-inverted.
