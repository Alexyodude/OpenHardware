# OpenHardware - a loopback HTTP front end for the emulators and the boards.
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
      -> 200 {steps, status: "running"|"stopped"|"faulted", detail}
         // "stopped": the core refused the firmware; "faulted": the core
         // itself faulted on the host, a bug in the simulator

    GET  /api/board/state?at=0x10000100&len=64&words=0xd0000010,0xd0000020
      -> 200 {board, chip, status, detail,
              registers: [{name, value, width}], flags: [{name, on}], pc,
              memory: {at, bytes[]}, words: [{address, value}],
              uart: {present, bytes, dropped_bytes, text, undecodable_bytes},
              listing: {present, at, lines[]}}

    POST /api/board/step?words=...   {"count": 1}
      -> 200 the state, as /api/board/state answers it; a step that stops
             the board answers here too, with status and detail saying why

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
# Aliased, because `compile` is a builtin and shadowing it inside a module this
# large is a trap somebody would eventually fall into.
from webui import compile as compile_service  # noqa: E402
# OH-10's headline: 42 tests of artefact discovery that nothing under webui/
# imported. This is the import.
from tools import import_firmware  # noqa: E402
from webui.boards import catalogue as board_catalogue  # noqa: E402

#: What this program calls itself, in the `Server:` header and on stdout.
#:
#: **The project, not one of the machines it runs.** It was
#: `OpenHardware-i8086` while this server had board routes serving an
#: ATmega328P -- see `DRIVING` below, which names a machine and is correct
#: to. One constant so the two places cannot drift apart again.
SERVER_NAME = "OpenHardware"

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
    # The vendors' own board models and the index naming them, written by
    # `tools/import_3d_model.py`. `model/gltf-binary` is glTF's registered
    # type; the browser never sniffs it, because `board3d.js` reads the file
    # as an ArrayBuffer, but a wrong type here would still be a wrong answer.
    ".glb": "model/gltf-binary",
    ".json": "application/json",
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
    if path == "/index.html":
        # The bridge's page, not this server's (OH-142): both servers read
        # one static/ directory, and this page dials a websocket this
        # server does not speak -- served here it renders and then hangs,
        # which reads as a broken UI rather than a wrong URL. The assets
        # stay common property; the ENTRY pages name a transport each.
        return None

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


def _query_int(query: dict[str, list[str]], name: str, default: str) -> int:
    """One query parameter as an int, or a refusal NAMING the parameter.

    `int(value, 0)`'s own message reads "invalid literal for int() with
    base 0: 'zz'" -- true, and useless in a reply to a request carrying
    three parameters. The body path already names its field (`_int`,
    `_optional_int`); the query path owed the same. (OH-139)
    """
    raw = query.get(name, [default])[0]
    try:
        return int(raw, 0)
    except ValueError:
        raise ApiError(f"{name} must be an integer, decimal or 0x hex, "
                       f"got {raw!r}") from None


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


class ArtefactSearch:
    """Where the server may look for builds, and what it found.

    **`roots is None` means off, and an empty list means on and nothing
    found.** They are different facts and a page says different things about
    them: one is "you did not turn this on", the other is "you have not built
    anything there yet".

    Module state rather than a parameter threaded through `handle_board_api`,
    because it is a property of how the server was STARTED. A request cannot
    reach it, which is the security property this whole route rests on --
    `tools/import_firmware.py` walks directories, and a route that took a path
    from a caller would walk any of them.
    """

    def __init__(self) -> None:
        self.roots: list[pathlib.Path] | None = None

    def allow(self, directories: list[str]) -> None:
        self.roots = [pathlib.Path(d).expanduser().resolve() for d in directories]

    def listing(self) -> list[dict[str, object]]:
        """Every artefact under every allowed root, newest first.

        Sorted by modification time, because the one somebody wants is almost
        always the one they just built -- and a list of forty firmware.elf
        ordered by path makes a person read all forty.
        """
        found: list[dict[str, object]] = []
        for root in self.roots or []:
            for artefact in import_firmware.find_artefacts(root):
                try:
                    stat = artefact.path.stat()
                except OSError:
                    # Vanished between the walk and the stat. Skipping it is
                    # right: it is not there to load either.
                    continue
                found.append({
                    "path": str(artefact.path),
                    "name": artefact.path.name,
                    "toolchain": artefact.toolchain,
                    "target": artefact.target,
                    "role": artefact.role,
                    "bytes": stat.st_size,
                    "modified": stat.st_mtime,
                    # A format that carries its own load address needs no base
                    # typed by hand. This is the field a page uses to decide
                    # whether to ask for one.
                    "needs_base": artefact.path.suffix.lower() == ".bin",
                })
        found.sort(key=lambda a: a["modified"], reverse=True)
        return found

    def resolve(self, wanted: str) -> pathlib.Path:
        """A path from a request, checked to be one this search offered.

        **Not `startswith`.** A root of `/home/me/build` would otherwise admit
        `/home/me/build-secrets`, which is the classic prefix mistake.
        `Path.is_relative_to` compares components.
        """
        if self.roots is None:
            raise ApiError(
                "artefact search is off. Start the server with --artefacts DIR."
            )
        candidate = pathlib.Path(wanted).expanduser().resolve()
        if not any(candidate.is_relative_to(root) for root in self.roots):
            raise ApiError(
                f"{wanted} is not under any directory this server was told to "
                f"search: {', '.join(str(r) for r in self.roots)}"
            )
        if not candidate.is_file():
            raise ApiError(f"{wanted} is not a file")
        return candidate


#: Set once from the command line. See `ArtefactSearch`.
SEARCH_ROOTS = ArtefactSearch()


def handle_board_api(boards: BoardSlot, route: str,
                     query: dict[str, list[str]],
                     payload: dict[str, object],
                     prepared=None) -> dict[str, object]:
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

    if route == "/api/board/artefacts":
        # **The request cannot name a directory, and that is the whole point.**
        #
        # OH-10 left this open: the compile-safety decision the user made on
        # 2026-08-25 was about running a compiler, not about reading a caller's
        # filesystem, and the ticket says to ask rather than assume the answer
        # carries over. It does not need asking if the answer is "off unless
        # the person running the server said otherwise" -- which is the same
        # shape `webui/compile.py` already keeps: the operator decides, the
        # request chooses among what the operator allowed.
        #
        # So `--artefacts DIR` on the command line is the only way this
        # answers anything. Absent, it reports that it is off and names the
        # flag, rather than 404 -- a route that exists and is disabled and a
        # route that does not exist are different facts, and a page can say so.
        if SEARCH_ROOTS.roots is None:
            return {
                "enabled": False,
                "note": (
                    "artefact search is off. Start the server with "
                    "--artefacts DIR to let it look for builds under DIR."
                ),
                "artefacts": [],
            }
        return {"enabled": True, "roots": [str(r) for r in SEARCH_ROOTS.roots],
                "artefacts": SEARCH_ROOTS.listing()}

    if route == "/api/board/compile":
        # **Build and load in one step, and the image never crosses the wire.**
        #
        # Not two routes. Returning bytes would mean base64 in a JSON body and
        # a client holding an image it has no use for -- the only thing it can
        # do with one is post it straight back. Doing both here also removes
        # the state where a build succeeded and a load has not happened yet,
        # which is a machine holding the previous sketch while the page shows
        # the new one's success.
        #
        # A build that FAILS leaves the board untouched. `boards.replace` is
        # reached only on success, so a syntax error does not cost a person the
        # program that was running.
        # Prepared OUTSIDE the lock by `_api` on the live server (OH-136);
        # prepared here, equivalently, for the tests that drive this handler
        # directly and for any second transport that grows one.
        board, built = (prepared if prepared is not None
                        else prepare_compile(payload))
        if not built.ok:
            return built.as_json()
        loaded = api.load_firmware(
            board, built.image, base=compile_service.recipe_for(board).base
        )
        boards.replace(loaded)
        return {**built.as_json(), "board": loaded.as_json()}

    if route == "/api/board/load-artefact":
        # Load one of the files `/api/board/artefacts` offered, by path.
        #
        # **The path is checked against the allowed roots, not trusted.** It
        # came back from this server a moment ago, but a request is a request:
        # nothing stops a caller sending a different one, and `resolve` is
        # what makes that harmless.
        board = payload.get("board")
        wanted = payload.get("path")
        if not isinstance(board, str):
            raise ApiError("board must be a string naming a board from /api/boards")
        if not isinstance(wanted, str):
            raise ApiError("path must be a string naming a file from /api/board/artefacts")
        path = SEARCH_ROOTS.resolve(wanted)
        # The same ceiling the body path enforces (OH-142): this route
        # skipped it, while the module docstring promised it everywhere an
        # image comes in. Checked on the size before a byte is read.
        size = path.stat().st_size
        if size > MAX_IMAGE_BYTES:
            raise ApiError(
                f"{wanted}: {size} bytes is larger than the "
                f"{MAX_IMAGE_BYTES}-byte ceiling"
            )
        loaded = api.load_firmware(
            board,
            path.read_bytes(),
            base=_optional_int(payload, "base"),
            vector_table=_optional_int(payload, "vector_table"),
        )
        boards.replace(loaded)
        return loaded.as_json()

    if route == "/api/board/run":
        result = boards.require().run(_int(payload, "steps", 10_000))
        return {"steps": result.steps, "status": result.status,
                "detail": result.detail}

    if route == "/api/board/pins":
        # **Fetched once per load, not per poll.** Where a pad sits is a
        # property of the board and the levels ride `/api/board/state`, which
        # the page already asks for many times a second. See `api.pin_levels`.
        #
        # **`?board=` answers for a board nobody has loaded, and OH-94 is why.**
        # This used to call `require()` first, so the pin view existed only
        # after a firmware load -- and since `reload()` in
        # `webui/static/board3d-panel.js` is the only thing that draws the
        # board, PICKING one drew nothing. The geometry never needed a session:
        # `api.pad_view` reads it out of `webui/boards/<board>.json`.
        #
        # Liveness is an OVERLAY rather than a second endpoint. If the session
        # is running the board being asked about, its levels are merged in;
        # otherwise every pad reads `unknown`, which the page already writes a
        # sentence for. One answer, so the picked board and the loaded board
        # cannot come to disagree about what a board looks like.
        asked = query.get("board", [""])[0] or None
        session = boards.session
        if asked is None:
            # No parameter is the old contract, and it still refuses by name.
            session = boards.require()
            asked = session.board
        if session is not None and session.board == asked:
            return api.pin_view(session.runtime, session.cpu, asked)
        return api.pad_view(asked, api.description_for(asked), None)

    if route == "/api/board/state":
        return _board_state(boards, query)

    if route == "/api/board/step":
        # `BoardSession.step` existed and no route exposed it (OH-140): the
        # 8086 could be single-stepped from the page and a board could not.
        # The stepped state comes back in the same reply so the page redraws
        # in one round-trip, and `words=` rides it exactly as on /state.
        #
        # **Through `run`, not `step`** (OH-225). `step` raises the core's
        # error, which nothing here maps, so a step that stopped got no reply
        # at all; and `step` did not check status, so after a host fault it
        # stepped the half-executed machine on. `run` reports a stop rather
        # than raising it and refuses a stopped board, so a step that stops
        # answers 200 as a run that stops does, the state saying why in
        # `status` and `detail`. `count` is a budget like `steps`, refused
        # outside 1..MAX_RUN_STEPS as `budget-refused`.
        boards.require().run(_int(payload, "count", 1))
        return _board_state(boards, query)

    raise ApiError(f"no such route: {route}")


def _board_state(boards: BoardSlot,
                 query: dict[str, list[str]]) -> dict[str, object]:
    """One reading of the board, as /api/board/state and /step both answer."""
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
        memory_length=_query_int(query, "len", "64"),
        words=watched,
    )


def handle_api(session: emulator.Session, route: str,
               query: dict[str, list[str]],
               payload: dict[str, object],
               boards: BoardSlot | None = None, prepared=None) -> dict[str, object]:
    """The whole API. Adding a route means adding it here, on purpose.

    `boards` is last and optional so that a caller with no board slot -- a
    test reaching for one of the i8086 routes -- keeps working unchanged. The
    board routes refuse rather than inventing a slot, because a slot invented
    per call would hold a core nobody could step twice.
    """
    if route.startswith("/api/board/"):
        if boards is None:
            raise ApiError(f"{route} needs a board slot; this caller has none")
        return handle_board_api(boards, route, query, payload,
                                prepared=prepared)

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
        return {"targets": listing, "driving": DRIVING}

    if route == "/api/boards":
        listing = []
        for described in board_catalogue.catalogue():
            entry = described.as_json()
            # Which boards the sketch panel can BUILD for is a fact about
            # this machine's recipes, stated here rather than discovered as
            # a 400 after typing a sketch (OH-140). The catalogue cannot
            # carry it: `compile` imports the catalogue, and layering points
            # one way. Asked of `recipe_for` rather than of `RECIPES`, which
            # has a row for the chip of a board it refuses (OH-176).
            try:
                compile_service.recipe_for(entry["name"])
            except compile_service.UnknownBoard:
                entry["buildable"] = False
            else:
                entry["buildable"] = True
            listing.append(entry)
        return {
            "boards": listing,
            "waiting": board_catalogue.missing_cores(),
        }

    if route == "/api/samples":
        return {"samples": [
            {"name": s.name, "hex": s.hex, "watch": s.watch,
             "listing": list(s.listing)}
            for s in emulator.SAMPLES
        ]}

    if route == "/api/state":
        at = _query_int(query, "at", "512")
        length = _query_int(query, "len", "256")
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


#: Every API route and the verbs that may reach it (OH-141).
#:
#: **A route that mutates answers only POST**, and the reason is the Origin
#: policy's own edge: a MISSING Origin is allowed by design -- curl and the
#: test suite send none -- and a cross-site `<img src="/api/reset">` sends
#: none either. The tag cannot read the reply (no CORS), so nothing is
#: disclosed; but before this table the request EXECUTED, and another tab
#: could reset the session or burn steps on a loaded board. State
#: corruption, not disclosure, and a 405 closes it. **The loopback-and-
#: Origin posture itself is unchanged**; this is a gap inside it, not a
#: challenge to it.
#:
#: Read-only routes accept both verbs: a POST-shaped read mutates nothing,
#: and refusing it would break no attack. A route absent from this table
#: does not exist; `test_every_route_states_its_methods` holds the two
#: lists together.
ROUTE_METHODS: dict[str, frozenset[str]] = {
    "/api/board/load": frozenset({"POST"}),
    "/api/board/compile": frozenset({"POST"}),
    "/api/board/load-artefact": frozenset({"POST"}),
    "/api/board/run": frozenset({"POST"}),
    "/api/board/step": frozenset({"POST"}),
    "/api/step": frozenset({"POST"}),
    "/api/run": frozenset({"POST"}),
    "/api/reset": frozenset({"POST"}),
    "/api/load": frozenset({"POST"}),
    "/api/board/artefacts": frozenset({"GET", "POST"}),
    "/api/board/pins": frozenset({"GET", "POST"}),
    "/api/board/state": frozenset({"GET", "POST"}),
    "/api/targets": frozenset({"GET", "POST"}),
    "/api/boards": frozenset({"GET", "POST"}),
    "/api/samples": frozenset({"GET", "POST"}),
    "/api/state": frozenset({"GET", "POST"}),
}


def prepare_compile(payload: dict[str, object]) -> tuple[str, object]:
    """The unlocked half of /api/board/compile: validate, then BUILD.

    **A build is subprocess work against a temporary directory and touches
    no session state until its image is loaded** (OH-136). It used to run
    inside the session lock, and the page froze for the whole of it --
    measured: a GET /api/state issued 0.7 s into a SAMD21 build answered
    after 15.79 s. `_api` calls this before taking the lock; the locked
    handler receives the finished build and does only the load.
    """
    board = payload.get("board")
    source = payload.get("source")
    if not isinstance(board, str):
        raise ApiError("board must be a string naming a board from /api/boards")
    if not isinstance(source, str):
        raise ApiError("source must be a string holding the sketch")
    try:
        return board, compile_service.build(board, source)
    except compile_service.CompileError as exc:
        # Cannot be attempted: an unknown board, or a toolchain this machine
        # does not have. Distinct from a sketch that does not compile, which
        # is a 200 with `ok: false` and the diagnostics.
        raise ApiError(str(exc)) from exc


class Handler(http.server.BaseHTTPRequestHandler):
    """One session, shared by every request, guarded by one lock."""

    session: emulator.Session
    boards: BoardSlot
    lock: threading.Lock
    allowed_origins: frozenset[str]

    protocol_version = "HTTP/1.1"
    server_version = SERVER_NAME

    def log_message(self, fmt: str, *args: object) -> None:
        """Quiet by default. The default handler writes a line per request to
        stderr, which buries anything the emulator itself has to say."""

    # --- the two verbs ------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802  (http.server's naming)
        if not self._origin_is_allowed():
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._api(parsed.path, urllib.parse.parse_qs(parsed.query), {},
                      "GET")
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
        self._api(parsed.path, urllib.parse.parse_qs(parsed.query), payload,
                  "POST")

    # --- helpers ------------------------------------------------------------

    def _api(self, route: str, query: dict[str, list[str]],
             payload: dict[str, object], verb: str) -> None:
        # Before anything runs, even the unlocked compile prelude: a wrong
        # verb is refused while the machine is still untouched (OH-141).
        allowed = ROUTE_METHODS.get(route)
        if allowed is not None and verb not in allowed:
            self._json(405, {"error": (
                f"{route} changes the machine and answers only "
                f"{'/'.join(sorted(allowed))}; a {verb} must not mutate"
            )})
            return
        try:
            # **A compile BUILDS before the lock is taken** (OH-136): the
            # subprocess work touches no session state, so only the load
            # that follows it belongs inside. Every other route but
            # /api/boards is unchanged: state stays guarded by the one lock.
            prepared = None
            if route == "/api/board/compile":
                prepared = prepare_compile(payload)
            if route == "/api/boards":
                # **Never under the lock** (OH-183): it reads the catalogue
                # and asks `recipe_for` of every board, which runs a
                # compiler for a manifest board's table, and it touches no
                # session state -- OH-136's reason, for a listing.
                self._json(200, handle_api(self.session, route, query,
                                           payload, self.boards))
                return
            with self.lock:
                self._json(
                    200,
                    handle_api(self.session, route, query,
                               payload, self.boards, prepared=prepared),
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


#: The three ways a socket says "the other end has already gone".
#:
#: Windows raises `ConnectionAbortedError` (WinError 10053) where POSIX raises
#: `BrokenPipeError`, and either platform can produce `ConnectionResetError`
#: first if the peer sent an RST. Named as a set so the three read as one fact
#: rather than as three special cases.
HUNG_UP = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)


class Server(http.server.ThreadingHTTPServer):
    """`ThreadingHTTPServer`, quiet about clients that go away mid-response."""

    def handle_error(self, request, client_address) -> None:
        """Report every failure except the peer closing the connection.

        **A reload used to print a twenty-line traceback.** `emulator.js` polls
        `/api/board/state` on a timer, so any reload of a running board leaves
        a response half-written to a socket nobody is reading; the write then
        raises WinError 10053 and `http.server`'s own `handle_error` prints the
        stack. The user who reported this attached it to a question about the
        3D view, which is exactly what a stack trace during normal use does --
        it becomes the explanation for whatever else was confusing.

        **This is not catch-and-default and the distinction is the whole
        design.** No value is substituted, no failure becomes a success, and
        nothing is retried: a peer hanging up is an ordinary event in HTTP and
        not something this program did. Every other exception reaches the base
        class with its traceback intact, which is what
        `test_a_handler_that_fails_for_any_other_reason_still_says_so` holds in
        place.
        """
        if isinstance(sys.exc_info()[1], HUNG_UP):
            return
        super().handle_error(request, client_address)


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
    Bound.boards = BoardSlot()
    Bound.lock = threading.Lock()
    server = Server((bind, port), Bound)

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
    parser.add_argument(
        "--artefacts", action="append", metavar="DIR", default=[],
        help="let the server look for PlatformIO, arduino-cli and STM32CubeIDE "
             "builds under DIR, so an image can be picked from a list instead "
             "of a file dialog. OFF unless given, and repeatable. A request "
             "can never name a directory -- only choose among what is found "
             "under these.",
    )
    args = parser.parse_args(argv)
    if args.artefacts:
        SEARCH_ROOTS.allow(args.artefacts)

    try:
        server = build_server(args.bind, args.port)
    except ValueError as exc:
        print(f"emulator-server: {exc}", file=sys.stderr)
        return 2

    host, port = server.server_address[:2]
    print(f"{SERVER_NAME} on http://{host}:{port}/  (ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
