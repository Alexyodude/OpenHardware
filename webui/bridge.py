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
import sys

try:
    from webui.api import ApiError, SimulatorApi
    from webui.rcontrol import RControlClient, RControlError
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    import pathlib

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from webui.api import ApiError, SimulatorApi
    from webui.rcontrol import RControlClient, RControlError

DEFAULT_BIND = "127.0.0.1"
DEFAULT_WS_PORT = 8787
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


class BridgeError(Exception):
    """The bridge refused a request before it reached the simulator."""


def _pins(api: SimulatorApi) -> list[dict]:
    return [dataclasses.asdict(pin) for pin in api.pins()]


#: name -> (callable(api, args), required argument names)
OPERATIONS: dict[str, tuple] = {
    "version": (lambda api, a: api.version(), ()),
    "info": (lambda api, a: api.info(), ()),
    "supported_boards": (lambda api, a: api.supported_boards(), ()),
    "supported_mcus": (lambda api, a: api.supported_mcus(), ()),
    "supported_parts": (lambda api, a: api.supported_parts(), ()),
    "pins": (lambda api, a: _pins(api), ()),
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

        except (BridgeError, ApiError, RControlError, json.JSONDecodeError, KeyError) as exc:
            return build_error(request_id, exc)


async def serve(
    rcontrol_host: str,
    rcontrol_port: int,
    bind: str,
    ws_port: int,
    allowed_origins: frozenset[str],
) -> None:
    import websockets

    if bind not in LOOPBACK:
        raise BridgeError(
            f"refusing to bind {bind!r}: the bridge can drive the simulator, "
            f"including loading firmware. Loopback only ({sorted(LOOPBACK)})."
        )

    client = RControlClient(host=rcontrol_host, port=rcontrol_port)
    client.connect()
    bridge = Bridge(SimulatorApi(client), allowed_origins)

    print(f"bridge: rcontrol {rcontrol_host}:{rcontrol_port} -> ws://{bind}:{ws_port}")
    async with websockets.serve(bridge.handle, bind, ws_port):
        await asyncio.Future()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bridge a browser to rcontrol.")
    parser.add_argument("--rcontrol-host", default="127.0.0.1")
    parser.add_argument("--rcontrol-port", type=int, default=5000)
    parser.add_argument("--bind", default=DEFAULT_BIND)
    parser.add_argument("--ws-port", type=int, default=DEFAULT_WS_PORT)
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
