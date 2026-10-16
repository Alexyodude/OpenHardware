# OpenHardware - the page's /api, answered inside the browser tab.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Answer the emulator page's `/api/*` requests with no server, per OH-238.

    InPage().answer("POST", "/api/run", '{"steps": 20000}')
    -> (200, '{"steps": 24, "status": "halted", "detail": ""}')

`webui/static/inpage/worker.js` runs this under Pyodide in a Web Worker, and
`webui/static/inpage/transport.js` hands it every `fetch` the page makes to
`/api/`. **The routes are `webui/emulator_server.py`'s, called as they are**:
`handle_api` decides what each request does and the cores load through the
same `core/*/abi.py`. What this module adds is only what `Handler` does around
that call -- the verb check, the body's ceiling and parse, and turning each
refusal into its status -- so the page cannot tell which transport answered.
`tests/webui/test_inpage.py` holds that: the same requests, through this and
through the loopback server, get the same statuses and the same JSON.

## Why the mapping is restated rather than shared

`Handler._api` and `Handler.do_POST` hold it, inside an `http.server` class,
in a file OH-161 holds. It is restated here, and the differential test is what
stops the two drifting. Once `emulator_server.py` is free, `Handler._api` can
call `InPage.route` instead and the restatement goes.

## The two routes a tab cannot honour

**Compiling** runs a cross-compiler in a subprocess, and a tab has neither.
The server's own refusal would name an install command for a machine the
visitor is not on; `NO_COMPILER` says what is true instead, and `/api/boards`
answers `buildable: false` for every board, so the page greys its Build button
before anyone presses it.

**Artefact search** walks the server's disk. The server answers it as off
unless it was started with `--artefacts`; here it is off with a note naming
the server rather than the flag.

## No lock

The server takes one lock around each call because `ThreadingHTTPServer`
answers on threads. A Worker handles one message at a time, so calls already
run in the order they arrived.
"""

from __future__ import annotations

import json
import urllib.parse

from webui import api, emulator, firmware
from webui import emulator_server as server

#: What `/api/board/compile` answers in a tab.
NO_COMPILER = (
    "Compiling a sketch needs a toolchain, and this copy of OpenHardware runs "
    "in your browser with no server and no compiler. Load an image you built "
    "instead, or run the local server: python webui/emulator_server.py"
)

#: What `/api/board/artefacts` notes in a tab.
NO_SEARCH = (
    "artefact search reads the server's own disk, and this copy runs in your "
    "browser with no server. Load the image with the file picker instead, or "
    "run python webui/emulator_server.py --artefacts DIR"
)


class InPage:
    """The one i8086 session and board slot a page talks to.

    The same two things `build_server` gives its `Handler`, for the same
    reason: one page, one machine of each kind.
    """

    def __init__(self) -> None:
        self.session = emulator.Session()
        self.boards = server.BoardSlot()

    def answer(self, verb: str, target: str, body: str) -> tuple[int, str]:
        """One request, as status and JSON text, the way the server sends it.

        `target` is the path and query the page fetched; `body` the text it
        posted, empty for a GET. Mirrors `Handler.do_GET` and `do_POST`.
        """
        parsed = urllib.parse.urlparse(target)
        query = urllib.parse.parse_qs(parsed.query)
        if verb == "GET":
            return self._json(*self.route(parsed.path, query, {}, verb))
        if verb != "POST":
            # `http.server` has no do_<verb> for these and answers 501 before
            # any route is looked at; so does this.
            return self._json(501, {"error": f"unsupported method {verb!r}"})

        size = len(body.encode("utf-8"))
        if size > server.MAX_BODY_BYTES:
            return self._json(413, {"error": f"body of {size} bytes exceeds "
                                             f"{server.MAX_BODY_BYTES}"})
        try:
            payload = json.loads(body or "{}")
        except (ValueError, RecursionError) as exc:
            # The server's two, for the server's reasons: see do_POST.
            return self._json(400, {"error": f"body is not JSON: {exc}"})
        if not isinstance(payload, dict):
            return self._json(400, {"error": "body must be a JSON object"})
        return self._json(*self.route(parsed.path, query, payload, verb))

    def route(self, route: str, query: dict[str, list[str]],
              payload: dict[str, object], verb: str) -> tuple[int, dict[str, object]]:
        """A parsed request -> status and reply. Mirrors `Handler._api`."""
        allowed = server.ROUTE_METHODS.get(route)
        if allowed is not None and verb not in allowed:
            return 405, {"error": (
                f"{route} changes the machine and answers only "
                f"{'/'.join(sorted(allowed))}; a {verb} must not mutate"
            )}
        if route == "/api/board/compile":
            return 400, {"error": NO_COMPILER}
        if route == "/api/board/artefacts":
            return 200, {"enabled": False, "note": NO_SEARCH, "artefacts": []}
        try:
            reply = server.handle_api(self.session, route, query, payload,
                                      self.boards)
        except api.BoardRunError as exc:
            return (server.BOARD_ERROR_STATUS.get(exc.reason, 400),
                    {"error": str(exc), "reason": exc.reason})
        except firmware.FirmwareError as exc:
            return 400, {"error": str(exc), "reason": "unreadable-artefact"}
        except (server.ApiError, emulator.EmulatorError, ValueError) as exc:
            return 400, {"error": str(exc)}
        if route == "/api/boards":
            reply = {**reply, "boards": [{**board, "buildable": False}
                                         for board in reply["boards"]]}
        return 200, reply

    @staticmethod
    def _json(status: int, reply: dict[str, object]) -> tuple[int, str]:
        return status, json.dumps(reply)
