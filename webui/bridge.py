#!/usr/bin/env python3
# OpenHardware — websocket bridge from the browser to rcontrol.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Expose ``webui.api`` to a browser over a localhost websocket.

Transport A of the two described in
``docs/superpowers/plans/2026-08-10-webui.md``. The browser speaks JSON to this
process; this process speaks rcontrol's text protocol to a running
``picsimlab``. Transport B replaces both hops with a direct WASM ``ccall`` and
reuses ``webui.api`` unchanged — which is why the operation names here are the
contract, not the wire format.

Three properties this deliberately enforces:

**Requests are serialised.** rcontrol is one TCP session with request/response
framing and no request identifiers. Two commands in flight would interleave and
each reply could be attributed to the wrong request — silently, producing wrong
numbers rather than an error. One lock, one command at a time.

**It binds loopback only.** A bridge on a public interface hands anyone on the
network control of the simulator, including ``loadhex``.

**It checks Origin.** A websocket from a browser is not protected by the same
origin policy the way ``fetch`` is: any page you visit can open a socket to
``localhost``. Without this check, visiting a hostile page would let it drive
your simulator. Requests carrying an unexpected Origin are refused.

Operations are an explicit allowlist rather than passthrough. A browser cannot
send arbitrary rcontrol text, so the API surface is exactly what is written
here and can be reviewed in one place.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
import urllib.parse

import pathlib

try:
    from webui import pinmap, render_model
    from webui.api import ApiError, SimulatorApi
    from webui.assets import (
        AssetError,
        BoardArt,
        available_boards,
        available_parts,
        load_board,
        load_part,
        resolve_board_name,
        share_root,
    )
    from webui.parts.schema import SchemaError, load_all_schemas
    from webui.rcontrol import RControlClient, RControlError
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from webui import pinmap, render_model
    from webui.api import ApiError, SimulatorApi
    from webui.assets import (
        AssetError,
        BoardArt,
        available_boards,
        available_parts,
        load_board,
        load_part,
        resolve_board_name,
        share_root,
    )
    from webui.parts.schema import SchemaError, load_all_schemas
    from webui.rcontrol import RControlClient, RControlError

DEFAULT_BIND = "127.0.0.1"
DEFAULT_WS_PORT = 8787
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})

STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"

#: Only these extensions are served, and each with an explicit type. A default
#: of `application/octet-stream` for anything unrecognised would let a file
#: dropped into `static/` be served without anyone deciding it should be.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}

#: Parsing a board's art re-reads a quarter-megabyte SVG, so keep it. Keyed by
#: board name; the set of boards cannot change while the simulator runs.
_ART_CACHE: dict[str, BoardArt] = {}

#: Parts without art cache a None, so a missing-art part is looked up once
#: rather than re-failing on every frame of the render loop.
_PART_ART_CACHE: dict[str, BoardArt | None] = {}


def board_art(name: str) -> BoardArt:
    if name not in _ART_CACHE:
        _ART_CACHE[name] = load_board(name)
    return _ART_CACHE[name]


class BridgeError(Exception):
    """The bridge refused a request before it reached the simulator."""


#: How to (re)start the simulator, and where to reconnect afterwards.
#:
#: **There is no rcontrol command that changes board.** `help` lists the whole
#: surface and none of it sets one; `loadhex` takes hex/bin only. A board is
#: chosen when the process starts, from the workspace it is given, so switching
#: means restarting the simulator -- which the bridge can only do if it is told
#: how to start one.
#:
#: Left unset, `switch_board` refuses and prints the command to run by hand.
#: That is deliberate: launching a process is not something a websocket from a
#: browser should be able to do unless the operator asked for it at startup.
LAUNCH = {"command": None, "host": "127.0.0.1", "port": 5000,
          "process": None}


def _switch_board(api: SimulatorApi, name: str) -> dict:
    """Restart the simulator on another board and reconnect to it."""
    import shlex
    import subprocess
    import time

    try:
        resolved = resolve_board_name(name)
    except AssetError as exc:
        raise BridgeError(str(exc)) from exc

    workspace = share_root() / "boards" / resolved / "demo.pzw"
    if not workspace.is_file():
        raise BridgeError(
            f"{resolved} ships no demo.pzw, so there is no workspace to start "
            f"it from. Boards are chosen by workspace, not by command."
        )

    if not LAUNCH["command"]:
        raise BridgeError(
            f"this bridge was not told how to start a simulator, so it will "
            f"not start one. Run the bridge with --sim-command to enable "
            f"switching, or relaunch picsimlab yourself with this workspace: "
            f"{workspace}"
        )

    # `resolved` comes from the shipped board list, never from the request, so
    # the only interpolation into the shell is a name this repository owns.
    #
    # `{board}` exists as well as `{workspace}` because the simulator often
    # runs somewhere the bridge's own paths do not reach -- here it is inside
    # WSL, where this repo's `C:\...\share` is `/root/oh/share`. Substituting
    # the name lets the template build the path in the simulator's world.
    command = (
        LAUNCH["command"]
        .replace("{workspace}", str(workspace))
        .replace("{board}", resolved)
    )

    # Split into argv and run without a shell. Going through one is both
    # unnecessary -- Popen already detaches -- and actively wrong on Windows,
    # where `shell=True` means cmd.exe: `&` is a command separator there, so a
    # template ending in the `&` that backgrounds the process *inside WSL* got
    # torn in half before wsl.exe ever saw it, and the nested quoting collapsed
    # with it. shlex keeps the whole `bash -lc` script as one argument.
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise BridgeError(f"--sim-command is not parseable: {exc}") from exc
    if not argv:
        raise BridgeError("--sim-command is empty")

    # The launched process is deliberately held rather than backgrounded. A
    # template ending in `&` looks right and does not work through `wsl.exe`:
    # when the foreground command of a WSL session returns, the session is torn
    # down and its background children go with it -- measured, `setsid nohup
    # ... &` returned 0 and left no process. `exec` in the template plus this
    # Popen keeps the simulator alive for as long as the bridge runs.
    previous = LAUNCH.get("process")
    if previous is not None and previous.poll() is None:
        previous.terminate()

    # No console window, and no inherited pipes.
    #
    # On Windows every child process gets its own console unless told not to,
    # so each board switch popped a window in front of whatever the operator
    # was doing -- from a UI they were driving in a browser. CREATE_NO_WINDOW
    # exists only on Windows, hence the guard rather than a platform check.
    #
    # stdout and stderr go to DEVNULL as well: an inherited pipe nobody reads
    # fills and blocks the simulator once it has written enough, which would
    # look like the board hanging some minutes after a switch.
    options: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        options["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        self_held = subprocess.Popen(argv, **options)
    except OSError as exc:
        raise BridgeError(f"could not run {argv[0]!r}: {exc}") from exc
    LAUNCH["process"] = self_held

    deadline = time.monotonic() + 30
    last = ""
    while time.monotonic() < deadline:
        time.sleep(1.0)
        probe = RControlClient(host=LAUNCH["host"], port=LAUNCH["port"], timeout=3)
        try:
            probe.connect()
        except RControlError as exc:
            last = str(exc)
            continue
        running = render_model.parse_info(SimulatorApi(probe).info()).board
        if running == resolved:
            try:
                api.client.close()
            except OSError:
                pass
            api.client = probe
            _ART_CACHE.pop(resolved, None)
            return {"board": running, "workspace": str(workspace)}
        probe.close()
        last = f"simulator came up on {running!r}, not {resolved!r}"

    raise BridgeError(
        f"restarted for {resolved} but no simulator answered on "
        f"{LAUNCH['host']}:{LAUNCH['port']} within 30s. Last: {last or 'no reply'}. "
        f"Four boards segfault on this build for want of QEMU "
        f"(docs/known-issues.md 4a-bis) -- check whether {resolved} is one."
    )


def _pins(api: SimulatorApi) -> list[dict]:
    return [dataclasses.asdict(pin) for pin in api.pins()]


#: Schemas are loaded once. A part with no schema is not an error -- coverage
#: is deliberately partial (peripherals design §6) -- so callers get None and
#: the UI offers raw config editing instead of named fields.
_SCHEMAS: dict | None = None


def _schemas() -> dict:
    global _SCHEMAS
    if _SCHEMAS is None:
        _SCHEMAS = load_all_schemas(pathlib.Path(__file__).resolve().parent / "parts" / "schemas")
    return _SCHEMAS


def _schema_for(name: str) -> dict | None:
    schema = _schemas().get(name)
    if schema is None:
        return None
    return {
        "part": schema.part,
        "source": schema.source,
        "verified": getattr(schema, "verified", None),
        "arity": schema.arity,
        "fields": [
            {
                "role": field.role,
                "dir": getattr(field, "dir", None),
                "type": getattr(field, "type", None),
                "label": field.label,
            }
            for field in schema.fields
        ],
    }


def _require_schema(name: str):
    schema = _schemas().get(name)
    if schema is None:
        raise BridgeError(
            f"no schema for {name!r}; its config layout has not been read from "
            f"source, and guessing one would miswire the circuit while "
            f"reporting success. Known: {sorted(_schemas())}"
        )
    return schema


def _read_wiring(api: SimulatorApi, index: int, name: str) -> dict:
    return api.read_wiring(int(index), _require_schema(name))


def _connect(api: SimulatorApi, index: int, name: str, label: str, pin: int) -> None:
    schema = _require_schema(name)
    if int(pin) == 0:
        api.disconnect(int(index), schema, label)
    else:
        api.connect(int(index), schema, label, int(pin))


def _part_art(name: str) -> BoardArt | None:
    """Art for a placed part, or None when it ships none.

    Three of the fifty-one placeable parts have an SVG but no map, and one has
    neither. Returning None keeps those placeable and configurable while the
    draw list reports them as not drawable, which is better than refusing to
    render the whole board because one peripheral lacks art.
    """
    if name not in _PART_ART_CACHE:
        try:
            _PART_ART_CACHE[name] = load_part(name)
        except AssetError:
            _PART_ART_CACHE[name] = None
    return _PART_ART_CACHE[name]


def _part_detail(api: SimulatorApi):
    """Per-part pin labels and current wiring, for the render model.

    Injected rather than imported so `render_model` keeps doing no I/O. Returns
    None for a part with no schema -- its pins cannot be named, so it gets no
    anchors and the UI offers the raw form instead.
    """

    def detail(index: int, name: str) -> dict | None:
        schema = _schemas().get(name)
        if schema is None:
            return None
        try:
            wiring = api.read_wiring(index, schema)
        except (ApiError, SchemaError, RControlError):
            # A part whose config cannot be read right now must not take the
            # whole frame down; it simply gets no anchors this pass.
            return None
        return {
            "labels": [field.label for _, field in schema.pin_fields],
            "wiring": {k: v for k, v in wiring.items() if isinstance(v, int)},
        }

    return detail


def _render(api: SimulatorApi) -> dict:
    """One `info` round trip, resolved against the art into a draw list.

    This is the render loop's whole server side. `info` carries the board
    identity and every placed part as well as the values, so the art is chosen
    by what the simulator says it is running rather than by anything the
    browser asserts.
    """
    state = render_model.parse_info(api.info())
    return render_model.build(
        state,
        board_art(state.board),
        part_art=_part_art,
        part_detail=_part_detail(api),
    )


def _pinmap(api: SimulatorApi) -> dict | None:
    """Where the running board's header pins sit on its image, if authored.

    None is not an error: coverage is partial by design and a board without a
    map falls back to the pin rail. See webui/pinmap.py.
    """
    board = render_model.parse_info(api.info()).board
    found = pinmap.load(board)
    if found is not None:
        return found.as_dict()
    # No authored map: lay the simulator's own pins out along the board edge so
    # the board is still wireable. Marked derived so the UI does not present a
    # schematic header as a real pinout.
    art = board_art(board)
    return pinmap.synthesise(board, api.pins(), art.width, art.height).as_dict()


def _catalogue(api: SimulatorApi) -> dict:
    """What can be placed, and what the simulator agrees exists.

    `splist` is the authority on what `spadd` accepts; `share/parts/` is the
    authority on what can be drawn. Reporting both, and their disagreement,
    keeps a part that is placeable-but-invisible from looking like a bug.
    """
    placeable = api.supported_parts()
    with_art = available_parts()
    return {
        "parts": [
            {
                "name": name,
                "category": with_art.get(name, "Uncategorised"),
                "drawable": name in with_art,
            }
            for name in sorted(placeable)
        ],
        "art_without_part": sorted(set(with_art) - set(placeable)),
    }


def _boards(api: SimulatorApi) -> dict:
    """Every board the simulator supports, matched to its art.

    `blist` reports the sanitised name and `info` the display name
    (`src/lib/board.cc:585`), so both are resolved here rather than in the
    browser. There is no rcontrol command that changes board -- `help` lists
    the whole surface and none of it sets one -- so `active` is reported and
    switching is not offered.
    """
    active = render_model.parse_info(api.info()).board
    rows = []
    for name in api.supported_boards():
        try:
            resolved = resolve_board_name(name)
        except AssetError:
            resolved = None
        rows.append(
            {
                "name": name,
                "art": resolved,
                "active": resolved is not None and resolved == active,
            }
        )
    return {"active": active, "boards": rows}


#: name -> (callable(api, args), required argument names)
OPERATIONS: dict[str, tuple] = {
    "version": (lambda api, a: api.version(), ()),
    "info": (lambda api, a: api.info(), ()),
    "supported_boards": (lambda api, a: api.supported_boards(), ()),
    "supported_mcus": (lambda api, a: api.supported_mcus(), ()),
    "supported_parts": (lambda api, a: api.supported_parts(), ()),
    "pins": (lambda api, a: _pins(api), ()),
    "render": (lambda api, a: _render(api), ()),
    "board_art_names": (lambda api, a: list(available_boards()), ()),
    "boards": (lambda api, a: _boards(api), ()),
    "pinmap": (lambda api, a: _pinmap(api), ()),
    "switch_board": (lambda api, a: _switch_board(api, a["name"]), ("name",)),
    "catalogue": (lambda api, a: _catalogue(api), ()),
    "enable_spare_parts": (lambda api, a: api.client.command("spshow 1").body, ()),
    "place_part": (
        lambda api, a: api.place_part(a["name"], int(a.get("x", 100)), int(a.get("y", 100))),
        ("name",),
    ),
    "part_schema": (lambda api, a: _schema_for(a["name"]), ("name",)),
    "read_wiring": (lambda api, a: _read_wiring(api, a["index"], a["name"]), ("index", "name")),
    "connect": (
        lambda api, a: _connect(api, a["index"], a["name"], a["label"], a["pin"]),
        ("index", "name", "label", "pin"),
    ),
    "get_pin": (lambda api, a: api.get_pin(a["index"]), ("index",)),
    "get_apin": (lambda api, a: api.get_apin(a["index"]), ("index",)),
    "set_pin": (lambda api, a: api.set_pin(a["index"], a["value"]), ("index", "value")),
    "set_apin": (
        lambda api, a: api.set_apin(a["index"], a["value"]),
        ("index", "value"),
    ),
    "get_board_input": (lambda api, a: api.get_board_input(a["index"]), ("index",)),
    "get_board_output": (lambda api, a: api.get_board_output(a["index"]), ("index",)),
    "set_board_input": (
        lambda api, a: api.set_board_input(a["index"], a["value"]),
        ("index", "value"),
    ),
    "get_part_input": (
        lambda api, a: api.get_part_input(a["part"], a["index"]),
        ("part", "index"),
    ),
    "get_part_output": (
        lambda api, a: api.get_part_output(a["part"], a["index"]),
        ("part", "index"),
    ),
    "set_part_input": (
        lambda api, a: api.set_part_input(a["part"], a["index"], a["value"]),
        ("part", "index", "value"),
    ),
    "add_part": (
        lambda api, a: api.add_part(a["name"], a.get("x", 0), a.get("y", 0)),
        ("name",),
    ),
    "remove_part": (lambda api, a: api.remove_part(a["index"]), ("index",)),
    "read_part_config": (lambda api, a: api.read_part_config(a["index"]), ("index",)),
    "run": (lambda api, a: api.run(), ()),
    "pause": (lambda api, a: api.pause(), ()),
    "reset": (lambda api, a: api.reset(), ()),
    "load_firmware": (lambda api, a: api.load_firmware(a["path"]), ("path",)),
    "scope_measures": (lambda api, a: api.scope_measures(a["channel"]), ("channel",)),
}


def dispatch(api: SimulatorApi, op: str, args: dict) -> object:
    """Run one allowlisted operation. Unknown names and missing args raise."""
    entry = OPERATIONS.get(op)
    if entry is None:
        raise BridgeError(f"unknown operation {op!r}; known: {sorted(OPERATIONS)}")
    handler, required = entry
    missing = [name for name in required if name not in args]
    if missing:
        raise BridgeError(f"{op!r} requires {list(required)}, missing {missing}")
    return handler(api, args)


def build_reply(request_id: object, result: object) -> str:
    return json.dumps({"id": request_id, "ok": True, "result": result})


def build_error(request_id: object, exc: Exception) -> str:
    return json.dumps(
        {
            "id": request_id,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    )


def resolve_static(target: str) -> tuple[bytes, str] | None:
    """Map a request path to file bytes and a content type, or None for 404.

    Path traversal is blocked by resolving the candidate and requiring it to
    stay under `static/`. `..` in a URL is not exotic; it is the first thing
    anyone tries against a file server, and this one runs beside a simulator
    that can load firmware.
    """
    path = target.split("?", 1)[0]
    if path in ("", "/"):
        path = "/index.html"

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


def resolve_board_svg(target: str) -> tuple[bytes, str] | None:
    """Serve `/board.svg?name=<board>` from `share/`, never from `static/`.

    The art is upstream's and stays where upstream put it. Copying it into
    `static/` would fork 108 files that already exist and would go stale the
    first time upstream redraws a board.
    """
    path, _, query = target.partition("?")
    if path != "/board.svg":
        return None
    params = urllib.parse.parse_qs(query)
    names = params.get("name")
    if not names:
        return None
    try:
        return board_art(names[0]).svg, "image/svg+xml"
    except AssetError:
        return None


def resolve_part_svg(target: str) -> tuple[bytes, str] | None:
    """Serve `/part.svg?name=<part>` from `share/parts/`."""
    path, _, query = target.partition("?")
    if path != "/part.svg":
        return None
    names = urllib.parse.parse_qs(query).get("name")
    if not names:
        return None
    art = _part_art(names[0])
    return None if art is None else (art.svg, "image/svg+xml")


def origin_is_allowed(origin: str | None, allowed: frozenset[str]) -> bool:
    """Reject any Origin not explicitly allowed.

    A missing Origin is allowed: non-browser clients such as the test suite and
    command-line tools do not send one, while browsers always do. So this stops
    a hostile page without locking out scripted use.
    """
    if origin is None:
        return True
    return origin in allowed


class Bridge:
    """One websocket endpoint in front of one rcontrol session."""

    def __init__(self, api: SimulatorApi, allowed_origins: frozenset[str]) -> None:
        self.api = api
        self.allowed_origins = allowed_origins
        self._lock = asyncio.Lock()

    async def handle(self, websocket) -> None:
        origin = websocket.request.headers.get("Origin")
        if not origin_is_allowed(origin, self.allowed_origins):
            await websocket.close(code=1008, reason="origin not allowed")
            return

        async for message in websocket:
            await websocket.send(await self.handle_message(message))

    async def handle_message(self, message: str) -> str:
        request_id = None
        try:
            payload = json.loads(message)
            request_id = payload.get("id")
            op = payload.get("op")
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                raise BridgeError("`args` must be an object")

            # One command at a time: rcontrol has no request ids, so concurrent
            # commands would let a reply be matched to the wrong request.
            async with self._lock:
                result = await asyncio.to_thread(dispatch, self.api, op, args)
            return build_reply(request_id, result)

        except (
            BridgeError,
            ApiError,
            AssetError,
            SchemaError,
            pinmap.PinMapError,
            render_model.StateError,
            RControlError,
            json.JSONDecodeError,
            KeyError,
        ) as exc:
            return build_error(request_id, exc)


async def serve(
    rcontrol_host: str,
    rcontrol_port: int,
    bind: str,
    ws_port: int,
    allowed_origins: frozenset[str],
) -> None:
    import websockets
    from websockets.datastructures import Headers
    from websockets.http11 import Response

    if bind not in LOOPBACK:
        raise BridgeError(
            f"refusing to bind {bind!r}: the bridge can drive the simulator, "
            f"including loading firmware. Loopback only ({sorted(LOOPBACK)})."
        )

    LAUNCH["host"], LAUNCH["port"] = rcontrol_host, rcontrol_port
    client = RControlClient(host=rcontrol_host, port=rcontrol_port)
    client.connect()
    bridge = Bridge(SimulatorApi(client), allowed_origins)

    def process_request(connection, request):
        """Serve the page over HTTP; let websocket handshakes through.

        One port serves both, so the page's own origin is the origin the
        websocket check already allows and `python webui/bridge.py` stays the
        entire install.
        """
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None

        served = (
            resolve_static(request.path)
            or resolve_board_svg(request.path)
            or resolve_part_svg(request.path)
        )
        if served is None:
            return Response(
                404,
                "Not Found",
                Headers({"Content-Length": "0", "Connection": "close"}),
                b"",
            )

        body, content_type = served
        return Response(
            200,
            "OK",
            Headers(
                {
                    "Content-Type": content_type,
                    "Content-Length": str(len(body)),
                    # The bridge is a development server for a local simulator;
                    # a stale cached app.js is a debugging session nobody wants.
                    "Cache-Control": "no-store",
                    # **Say that the socket is closing.** websockets serves one
                    # HTTP response per connection and then closes it, but
                    # HTTP/1.1 defaults to keep-alive, so without this a browser
                    # reuses the socket for style.css and app.js and every one
                    # of those requests dies on a closed connection -- which
                    # renders as a blank page with the document itself
                    # discarded. `urllib` never saw it because it opens a fresh
                    # connection per request; a browser does not.
                    "Connection": "close",
                }
            ),
            body,
        )

    print(f"bridge: rcontrol {rcontrol_host}:{rcontrol_port}")
    print(f"bridge: open http://{bind}:{ws_port}/")
    async with websockets.serve(
        bridge.handle, bind, ws_port, process_request=process_request
    ):
        await asyncio.Future()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bridge a browser to rcontrol.")
    parser.add_argument("--rcontrol-host", default="127.0.0.1")
    parser.add_argument("--rcontrol-port", type=int, default=5000)
    parser.add_argument("--bind", default=DEFAULT_BIND)
    parser.add_argument("--ws-port", type=int, default=DEFAULT_WS_PORT)
    parser.add_argument(
        "--sim-command",
        default=None,
        help=(
            "command that starts picsimlab, enabling board switching from the "
            "UI. {workspace} is the board's demo.pzw path as this process sees "
            "it; {board} is its name, for when the simulator lives somewhere "
            "with different paths. Split with shlex and run without a shell. "
            "**Do not background it** -- this process holds it -- and stop any "
            "running simulator first, or the new one cannot bind the rcontrol "
            "port. Use `pkill -x`, not `pkill -f`: the launching shell's own "
            "command line contains the word picsimlab, so -f makes it kill "
            "itself. Example for a simulator in WSL: "
            "wsl -d Ubuntu-22.04 -- bash -lc \"pkill -x picsimlab; sleep 2; "
            "cd /root/oh/src && DISPLAY=:0 exec ./picsimlab "
            "'/root/oh/share/boards/{board}/demo.pzw'\""
        ),
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=None,
        help="repeatable; defaults to the local page's own origins",
    )
    args = parser.parse_args(argv)

    origins = frozenset(
        args.allow_origin
        or [f"http://127.0.0.1:{args.ws_port}", f"http://localhost:{args.ws_port}"]
    )

    # An environment variable as well as a flag, because this value is a shell
    # command full of nested quotes and passing it through another shell --
    # cmd.exe, PowerShell, a .cmd launcher -- mangles it. An environment
    # variable carries it verbatim. The flag wins when both are set.
    LAUNCH["command"] = args.sim_command or os.environ.get("OPENHARDWARE_SIM_COMMAND")

    try:
        asyncio.run(
            serve(
                args.rcontrol_host,
                args.rcontrol_port,
                args.bind,
                args.ws_port,
                origins,
            )
        )
    except (BridgeError, RControlError) as exc:
        print(f"bridge: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
