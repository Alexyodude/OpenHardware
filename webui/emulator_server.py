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

## The board routes

`/api/board/load`, `/api/board/run` and `/api/board/state` are the transport
half of OH-32: a board name and an uploaded artefact in, a running core out.
The same posture applies and applies harder -- this is the one route that
takes a file from the caller -- so it is behind the same loopback bind, the
same Origin check, and additionally a ceiling on the artefact and on the whole
request body.

The emulated core is no more dangerous than the 8086 above: a Cortex-M0+ here
addresses only the regions its board description mapped, and has no file, no
socket and no syscall. What the ceilings bound is this process's memory, not
the guest's reach.

`webui/api.py` holds every one of these operations and every refusal, for the
same reason `webui/emulator.py` holds the 8086's: **the tests drive the
session, not the transport.** The nine ways a load can be refused are tested
there. What is tested *here* is that each of them arrives as itself, with its
own status code, rather than as one flat 400.

### What a page sends, and what comes back

`webui/static/` is another ticket's, so this is written down rather than
wired. The board list is already at `GET /api/boards`; a page offers what
that returns and posts a name back.

    POST /api/board/load
      {"board": "XIAO-RP2040-DIP",
       "image": "<base64 of the artefact>",
       "base": "0x10000100",      // raw .bin only; ELF/UF2/HEX carry their own
       "vector_table": "0x..."}   // optional, only if neither convention fits
      -> 200 {board, chip, core, format, family, bytes, segments,
              entry, notes,
              vector_table, stack_pointer}   // Arm boards only; see below

    POST /api/board/run     {"steps": 5000}
      -> 200 {steps, status: "running"|"stopped", detail}

    GET  /api/board/state?at=0x10000100&len=64&words=0xd0000010,0xd0000020
      -> 200 {board, chip, status, detail,
              registers: [{name, value, width}], flags: [{name, on}], pc,
              memory: {at, bytes[]}, words: [{address, value}],
              uart: {present, bytes, dropped_bytes, text, undecodable_bytes},
              listing: {present, at, lines[]}}

**Registers are named and carry their width, and that is not decoration.**
This used to be sixteen positional words plus an `apsr` integer, which is the
Armv6-M register file and nothing else: an ATmega328P has thirty-two eight-bit
registers, SP and PC, and eight flags numbered from the bottom of SREG rather
than four from the top of APSR. `core/<core>/machine.py` reports what its
machine has and this passes it through, so adding a core changes no code here
and none in the page.

`pc` is on the wire for the same reason: `registers[15]` is the program
counter on one machine here and an ordinary working register on another.

`vector_table` and `stack_pointer` are **absent** rather than null on a board
that has neither. An AVR begins executing at word zero, so there is no table
and no stack-pointer word in the image -- and null would claim there is one
whose value is unknown. `entry` is on every board.

`uart` is **cumulative**: `text` is everything the board has transmitted since
the image was loaded, not what is new since the last poll. A console therefore
**replaces** its contents on each state call and must not append, or it prints
every line again on every poll. `bytes` is the total so a client can tell
"nothing new" without comparing strings, and `dropped_bytes` is how many of the
oldest were left out once the total passed `api.MAX_UART_BYTES`.

A byte that is not valid UTF-8 does not fail the request: it arrives as a
backslash-x escape and `undecodable_bytes` counts how many, so a page can say
"this is not text" rather than showing escapes as if the firmware printed them.
A board whose description has no UART answers `{"present": false, "note": ...}`
-- which is a fact about the model, and not the same as a program that ran and
printed nothing.

`base` and `vector_table` accept a number or a `0x` string, because a text
input hands over text. `words` is how a peripheral register is read: `at`/`len`
is a window over regions, and a mapped register is not a region -- the refusal
says so and names `words=` when someone tries.

Every refusal answers `{"error": ..., "reason": ...}` where `reason` is one of
`api.REASONS`, so a page can style the "build a core" case differently from
the "your image is linked at the wrong address" case without parsing English.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import http.server
import json
import pathlib
import sys
import threading
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from webui import api, emulator, firmware, targets  # noqa: E402
from webui.boards import catalogue as board_catalogue  # noqa: E402

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

#: The largest firmware artefact `/api/board/load` will accept. Sized from the
#: boards in the catalogue rather than picked: the RP2040 has 2 MiB of flash
#: and the largest part on the list has 4 MiB, so 8 MiB accepts any real image
#: with room to spare and still bounds one request.
MAX_IMAGE_BYTES = 8 << 20

#: A ceiling on the whole request body, checked from `Content-Length` **before
#: a byte is read**. Base64 inflates by four thirds, so this has to clear
#: `MAX_IMAGE_BYTES` with the JSON around it; 16 MiB does.
#:
#: Added with the upload route. Without it a declared Content-Length of any
#: size was allocated and read, which mattered little when every body was a
#: small JSON object and matters now that one route exists to be handed a
#: file.
MAX_BODY_BYTES = 16 << 20

#: Which HTTP status each of `api.REASONS` deserves.
#:
#: The distinction is the point of the endpoint, not decoration. **400** means
#: the request or the artefact is wrong and the caller can fix it. **409**
#: means this checkout cannot do it yet, and only building a core or writing a
#: board description will change that -- a different person doing a different
#: thing on a different day. **404** means the board named is not here at all.
#:
#: Collapsing these into one 400 would tell someone to fix their firmware when
#: what they actually need is `python tools/build_core.py`.
BOARD_ERROR_STATUS = {
    "unknown-board": 404,
    "core-not-built": 409,
    "chip-not-described": 409,
    "nothing-for-this-chip": 400,
    "outside-the-board-map": 400,
    "no-vector-table": 400,
    "budget-refused": 400,
    "window-refused": 400,
    "window-outside-the-map": 400,
}


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


#: The cores this server can actually put on screen.
#:
#: `webui/emulator.py` is an i8086 session and nothing else: its registers,
#: its disassembly and its sample programs are all 8086. A second core being
#: *built* does not make it drivable here, and letting one be selected anyway
#: would leave the UI showing 8086 state under an Arm label -- a worse lie
#: than not offering it.
#:
#: So this is separate from `targets.READY`, which answers "is there a built
#: core". Two orthogonal facts, and the UI shows both.
DRIVABLE = frozenset({"i8086"})

#: What the emulator view is running right now. Not `targets.default_name()`:
#: that returns the first *runnable* core, which became `cortexm0` the moment
#: a second core was built, and would have had the selector claim the page was
#: driving an Arm.
DRIVING = "i8086"


def _not_drivable(name: str) -> str:
    return (
        f"{name!r} is built, but this server drives only "
        f"{', '.join(sorted(DRIVABLE))}. webui/emulator.py is an i8086 session; "
        f"a core needs one of its own before it can be shown here."
    )


class Selection:
    """Which target the UI is pointed at, for the life of the server.

    A class rather than a bare string because the handler shares one of these
    across every request, exactly as it shares the session and the lock. It
    holds a name and not a `Target`, because a target's *status* is read from
    disk each time it is asked for -- deleting `build/lib/` under a running
    server has to be visible, and a cached `Target` would keep reporting
    `ready` at a library that is no longer there.
    """

    def __init__(self, name: str | None = None) -> None:
        self.name = name if name is not None else DRIVING


class BoardSlot:
    """The board session the page is watching, or none yet.

    Separate from the `emulator.Session` above and deliberately so: that is
    the i8086 this server was written around, and a board is a different core
    with a different state shape. One board at a time, because the page shows
    one.
    """

    def __init__(self) -> None:
        self.session: api.BoardSession | None = None

    def replace(self, loaded: api.BoardSession) -> None:
        """Adopt a session, releasing the one it displaces.

        A `BoardSession` owns a native allocation, so dropping the reference
        leaks it until the process exits. Loading a second image is the most
        ordinary thing a person does here, which would make that a leak per
        request rather than a rare one.
        """
        if self.session is not None:
            self.session.close()
        self.session = loaded

    def require(self) -> api.BoardSession:
        if self.session is None:
            raise ApiError(
                "no board is loaded; POST /api/board/load with a board name "
                "and a base64 image first"
            )
        return self.session


def _optional_int(payload: dict[str, object], name: str) -> int | None:
    """An integer field that may be absent, and may arrive as a hex string.

    A file-input page reads `0x10000100` out of a text box as text. Accepting
    that spelling saves every caller a parse; refusing anything that is not an
    int or a string keeps `int(value, 0)` from being handed a list.
    """
    value = payload.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ApiError(f"{name} must be an integer or a hex string, got {value!r}")
    if isinstance(value, int):
        return value
    try:
        return int(value, 0)
    except ValueError as exc:
        raise ApiError(f"{name}: {exc}") from exc


def _image_bytes(payload: dict[str, object]) -> bytes:
    """The uploaded artefact, decoded and bounded.

    `validate=True` so that base64 with rubbish in it is refused here rather
    than silently discarded and handed to a firmware parser as a short file.
    """
    encoded = payload.get("image")
    if not isinstance(encoded, str):
        raise ApiError("image must be a base64 string of the artefact's bytes")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError(f"image is not valid base64: {exc}") from exc
    if not data:
        raise ApiError("image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ApiError(
            f"{len(data)} bytes is larger than the {MAX_IMAGE_BYTES}-byte ceiling"
        )
    return data


def handle_board_api(boards: BoardSlot, route: str,
                     query: dict[str, list[str]],
                     payload: dict[str, object]) -> dict[str, object]:
    """Three routes: put an image on a board, run it, look at it.

    Thin, like everything else here. `webui/api.py` holds the behaviour and
    the refusals; this decodes a request into a call and the answer into JSON.
    A bug that can only be found through HTTP is a bug in these thirty lines.

    The board list itself is already at `/api/boards`, so nothing here has to
    enumerate anything: a page offers what that returns and posts a name back.
    """
    if route == "/api/board/load":
        board = payload.get("board")
        if not isinstance(board, str):
            raise ApiError(
                "board must be a string naming a board from /api/boards"
            )
        loaded = api.load_firmware(
            board,
            _image_bytes(payload),
            base=_optional_int(payload, "base"),
            vector_table=_optional_int(payload, "vector_table"),
        )
        boards.replace(loaded)
        return loaded.as_json()

    if route == "/api/board/run":
        result = boards.require().run(_int(payload, "steps", 10_000))
        return {"steps": result.steps, "status": result.status,
                "detail": result.detail}

    if route == "/api/board/state":
        at = query.get("at")
        # `words=` is comma-separated because a peripheral view watches a
        # handful of fixed addresses and repeating the key for each would make
        # the query string harder to read than the thing it describes.
        watched = [
            int(word, 0)
            for group in query.get("words", [])
            for word in group.split(",")
            if word
        ]
        return boards.require().state(
            memory_at=int(at[0], 0) if at else None,
            memory_length=int(query.get("len", ["64"])[0], 0),
            words=watched,
        )

    raise ApiError(f"no such route: {route}")


def handle_api(session: emulator.Session, selection: Selection, route: str,
               query: dict[str, list[str]],
               payload: dict[str, object],
               boards: BoardSlot | None = None) -> dict[str, object]:
    """The whole API. Adding a route means adding it here, on purpose.

    `boards` is last and optional so that a caller with no board slot -- a
    test reaching for one of the i8086 routes -- keeps working unchanged. The
    board routes refuse rather than inventing a slot, because a slot invented
    per call would hold a core nobody could step twice.
    """
    if route.startswith("/api/board/"):
        if boards is None:
            raise ApiError(f"{route} needs a board slot; this caller has none")
        return handle_board_api(boards, route, query, payload)

    if route == "/api/targets":
        listing = []
        for target in targets.catalogue():
            entry = target.as_json()
            entry["drivable"] = target.name in DRIVABLE
            if entry["selectable"] and not entry["drivable"]:
                # Overwrite rather than add a second reason field: the UI shows
                # one line per target, and "built and loadable" beside a
                # disabled option reads as a bug in the UI.
                entry["detail"] = _not_drivable(target.name)
                entry["selectable"] = False
            listing.append(entry)
        return {"targets": listing, "selected": selection.name, "driving": DRIVING}

    if route == "/api/boards":
        return {
            "boards": [b.as_json() for b in board_catalogue.catalogue()],
            "waiting": board_catalogue.missing_cores(),
        }

    if route == "/api/target":
        name = payload.get("name")
        if not isinstance(name, str):
            raise ApiError("name must be a string naming a core under core/")
        try:
            chosen = targets.require_selectable(name)
        except targets.TargetError as exc:
            raise ApiError(str(exc)) from exc
        if chosen.name not in DRIVABLE:
            raise ApiError(_not_drivable(chosen.name))
        selection.name = chosen.name
        return {"selected": selection.name, "target": chosen.as_json()}

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
    selection: Selection
    boards: BoardSlot
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
        if length > MAX_BODY_BYTES:
            # Checked from the header, before a byte is allocated. Reading a
            # declared length and then judging it is the thing this avoids.
            self._json(413, {"error": f"body of {length} bytes exceeds "
                                      f"{MAX_BODY_BYTES}"})
            return
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
                self._json(
                    200,
                    handle_api(self.session, self.selection, route, query,
                               payload, self.boards),
                )
        except api.BoardRunError as exc:
            # **Each refusal reaches the caller as itself.** Flattening these
            # into one 400 would lose the difference between "build a core"
            # and "your image is linked at the wrong address", which is the
            # only difference that matters to the person reading it.
            self._json(
                BOARD_ERROR_STATUS.get(exc.reason, 400),
                {"error": str(exc), "reason": exc.reason},
            )
        except firmware.FirmwareError as exc:
            self._json(400, {"error": str(exc), "reason": "unreadable-artefact"})
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
    Bound.selection = Selection()
    Bound.boards = BoardSlot()
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
