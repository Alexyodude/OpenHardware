# OpenHardware — the bridge's HTTP surface.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""The page has to survive a browser, not just `urllib`.

`webui/bridge.py` serves the front-end from the same port as the websocket, via
`websockets`' `process_request`. That path answers **one HTTP request per
connection and then closes the socket**.

HTTP/1.1 defaults to keep-alive, so unless the response says otherwise a
browser reuses that socket for `style.css`, `app.js` and the rest -- and every
one of those requests dies on a connection the server has already closed. The
page renders blank.

`urllib` never saw it, because it opens a fresh connection per request. This
suite exists because that difference cost an afternoon: every check said the
server was fine while the browser showed nothing.
"""

from __future__ import annotations

import pathlib
import re

BRIDGE = (
    pathlib.Path(__file__).resolve().parents[2] / "webui" / "bridge.py"
).read_text(encoding="utf-8")


def test_every_http_response_announces_that_it_closes():
    """Both the served-file path and the 404 path must say `Connection: close`.

    Without it a browser keeps the socket and its next request vanishes.
    """
    responses = re.findall(r"return Response\((.*?)\n        \)", BRIDGE, re.S)
    assert responses, "no Response construction found; this test's parse is wrong"
    for body in responses:
        assert '"Connection": "close"' in body, (
            f"an HTTP response does not announce closing:\n{body[:300]}"
        )


def test_the_404_path_closes_too():
    assert BRIDGE.count('"Connection": "close"') >= 2


def test_responses_carry_an_explicit_content_length():
    """A browser needs to know where the body ends on a closing connection."""
    assert '"Content-Length": str(len(body))' in BRIDGE


def test_static_files_are_not_cached():
    """A stale app.js is a debugging session nobody wants."""
    assert '"Cache-Control": "no-store"' in BRIDGE
