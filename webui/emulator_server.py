# OpenHardware - a loopback HTTP front end for the i8086 emulator.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Serve the emulator UI and a small JSON API, per ticket OH-7.

    python webui/emulator_server.py --port 8088

## This is deliberately thin

Every handler here does one thing: translate a request into a call on
`webui.emulator.Session` and its answer into JSON. All the behaviour, and all
the tests, live there. A bug that can only be found through HTTP is a bug in
the translation, and there is not much translation to get wrong.

## The same safety posture as the bridge

`webui/bridge.py` states the reasoning at length and it applies unchanged:

* **loopback only.** A server on a public interface hands anyone who can reach
  it the ability to load and run code in this process.
* **Origin is checked.** A page you visit can POST to `localhost` without the
  same-origin policy stopping it. A request carrying an Origin that is not
  this server's own is refused, so a stray tab cannot drive the emulator.
* **an explicit route table**, not a dispatcher that turns a URL into a method
  name. The set of things this server can be asked to do is the list below and
  nothing else.
* **only four file extensions are served**, each with a stated content type,
  so a file dropped into `static/` is not served because it happened to land
  there.

Loading a program is *meant* to run arbitrary 8086 code -- that is the entire
product -- so the boundary that matters is who can ask, not what they ask for.
The 8086 has no way out of its one megabyte: it cannot open a file, reach a
socket, or address a byte this process did not give it.
"""

from __future__ import annotations

import argparse
import http.server
import json
import pathlib
import sys
import threading
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from webui import emulator  # noqa: E402

DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8088
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})

STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"

#: Only these are served, each with an explicit type. Same table and same
#: reasoning as bridge.py.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}

#: The largest program the API will accept, in bytes. The address space is a
#: megabyte; anything larger is a mistake or an attempt to exhaust memory.
MAX_PROGRAM_BYTES = 1 << 20


class ApiError(Exception):
    """A request that is wrong, as opposed to a server that is broken."""


def resolve_static(target: str) -> tuple[bytes, str] | None:
    """Map a request path to file bytes and a content type, or None for 404.

    Path traversal is blocked by resolving the candidate and requiring it to
    stay under `static/`. `..` in a URL is the first thing anyone tries.
    """
    path = urllib.parse.urlparse(target).path
    if path in ("", "/"):
        path = "/emulator.html"

    candidate = (STATIC_DIR / path.lstrip("/")).resolve()
    try:
        candidate.relative_to(STATIC_DIR.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    content_type = CONTENT_TYPES.get(candidate.suffix)
    if content_type is None:
        return None
    return candidate.read_bytes(), content_type


def _int(payload: dict[str, object], name: str, default: int) -> int:
    value = payload.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(f"{name} must be an integer, got {value!r}")
    return value


def handle_api(session: emulator.Session, route: str, query: dict[str, list[str]],
               payload: dict[str, object]) -> dict[str, object]:
    """The whole API. Adding a route means adding it here, on purpose."""
    if route == "/api/samples":
        return {"samples": [
            {"name": s.name, "hex": s.hex, "watch": s.watch,
             "listing": list(s.listing)}
            for s in emulator.SAMPLES
        ]}

    if route == "/api/state":
        at = int(query.get("at", ["512"])[0], 0)
        length = int(query.get("len", ["256"])[0], 0)
        return session.state(memory_at=at, memory_length=length)

    if route == "/api/step":
        result = session.step()
        return {"steps": result.steps, "status": result.status,
                "detail": result.detail}

    if route == "/api/run":
        result = session.run(_int(payload, "steps", 10_000))
        return {"steps": result.steps, "status": result.status,
                "detail": result.detail}

    if route == "/api/reset":
        session.reset()
        return {"status": session.status}

    if route == "/api/load":
        text = payload.get("hex", "")
        if not isinstance(text, str):
            raise ApiError("hex must be a string of hex digits")
        try:
            program = bytes.fromhex("".join(text.split()))
        except ValueError as exc:
            raise ApiError(f"not hex: {exc}") from exc
        if len(program) > MAX_PROGRAM_BYTES:
            raise ApiError(
                f"{len(program)} bytes is larger than the whole address space"
            )
        session.load(program, origin=_int(payload, "origin", session.origin))
        return {"status": session.status, "loaded": len(program),
                "origin": session.origin}

    raise ApiError(f"no such route: {route}")


class Handler(http.server.BaseHTTPRequestHandler):
    """One session, shared by every request, guarded by one lock."""

    session: emulator.Session
    lock: threading.Lock
    allowed_origins: frozenset[str]

    protocol_version = "HTTP/1.1"
    server_version = "OpenHardware-i8086"

    def log_message(self, fmt: str, *args: object) -> None:
        """Quiet by default. The default handler writes a line per request to
        stderr, which buries anything the emulator itself has to say."""

    # --- the two verbs ------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802  (http.server's naming)
        if not self._origin_is_allowed():
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._api(parsed.path, urllib.parse.parse_qs(parsed.query), {})
            return
        found = resolve_static(self.path)
        if found is None:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        body, content_type = found
        self._send(200, body, content_type)

    def do_POST(self) -> None:  # noqa: N802
        if not self._origin_is_allowed():
            return
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            self._json(400, {"error": f"body is not JSON: {exc}"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"error": "body must be a JSON object"})
            return
        self._api(parsed.path, urllib.parse.parse_qs(parsed.query), payload)

    # --- helpers ------------------------------------------------------------

    def _api(self, route: str, query: dict[str, list[str]],
             payload: dict[str, object]) -> None:
        try:
            with self.lock:
                self._json(200, handle_api(self.session, route, query, payload))
        except (ApiError, emulator.EmulatorError, ValueError) as exc:
            # A bad request, named. Not a 500: nothing here is broken.
            self._json(400, {"error": str(exc)})

    def _origin_is_allowed(self) -> bool:
        """Refuse any Origin that is not this server's own.

        A missing Origin is allowed: curl and the test suite do not send one,
        and it is browsers this is protecting against.
        """
        origin = self.headers.get("Origin")
        if origin is None or origin in self.allowed_origins:
            return True
        self._send(403, b"origin not allowed", "text/plain; charset=utf-8")
        return False

    def _json(self, status: int, body: dict[str, object]) -> None:
        self._send(status, json.dumps(body).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The page is served from this origin and talks only to it.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def build_server(bind: str, port: int,
                 session: emulator.Session | None = None
                 ) -> http.server.ThreadingHTTPServer:
    """A configured server, not yet serving. Refuses a non-loopback bind."""
    if bind not in LOOPBACK:
        raise ValueError(
            f"refusing to bind {bind}: this server loads and runs code on "
            f"request, so it is loopback-only by design. See the module "
            f"docstring."
        )

    live = session if session is not None else emulator.Session()

    class Bound(Handler):
        pass

    Bound.session = live
    Bound.lock = threading.Lock()
    server = http.server.ThreadingHTTPServer((bind, port), Bound)

    # **After binding, not before.** Port 0 means "any free port", and the
    # allowed-origin set was being built from the 0 rather than from whatever
    # was actually assigned -- so a server started that way refused its own
    # page. Only the test suite passes 0, which is exactly why the test suite
    # is what found it.
    assigned = server.server_address[1]
    Bound.allowed_origins = frozenset(
        f"http://{host}:{assigned}" for host in ("127.0.0.1", "localhost")
    )
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bind", default=DEFAULT_BIND)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    try:
        server = build_server(args.bind, args.port)
    except ValueError as exc:
        print(f"emulator-server: {exc}", file=sys.stderr)
        return 2

    host, port = server.server_address[:2]
    print(f"i8086 emulator on http://{host}:{port}/  (ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
