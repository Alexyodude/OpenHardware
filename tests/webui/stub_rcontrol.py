# OpenHardware — a stub rcontrol server for testing the client.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""A real TCP server that speaks the protocol from ``src/lib/rcontrol.cc``.

Real, not mocked: it binds a socket and exchanges bytes, so the client's
framing, timeout, and disconnect handling are exercised for genuine rather than
simulated. Mocking the socket would test the mock.

It can also misbehave on purpose. Every failure mode the client claims to
detect — silence, an early close, a reply with no terminator, a reply with an
unknown status — has a behaviour here that produces it, because a client whose
error paths are never exercised has error paths nobody has checked.
"""

from __future__ import annotations

import socket
import threading

BANNER = (
    "\r\nPICSimLab Remote Control Interface\r\n\r\n"
    "  Type help to see supported commands\r\n\r\n>"
)

OK = "Ok\r\n>"
ERROR = "ERROR\r\n>"


def ok(body: str = "") -> str:
    """Frame a successful reply carrying `body`."""
    return f"{body}\r\n{OK}" if body else OK


class StubRControl:
    """A scripted rcontrol server on an ephemeral port.

    behaviour:
      "normal"      reply from `responses`, defaulting to Ok
      "silent"      send the banner, then never reply again
      "close_early" send the banner, then close on the first command
      "no_banner"   accept the connection and immediately close
    """

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        behaviour: str = "normal",
        banner: str = BANNER,
    ) -> None:
        self.responses = responses or {}
        self.behaviour = behaviour
        self.banner = banner
        self.received: list[str] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def port(self) -> int:
        return self._sock.getsockname()[1]

    def __enter__(self) -> StubRControl:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2)

    def _serve(self) -> None:
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return
        with conn:
            if self.behaviour == "no_banner":
                return
            conn.sendall(self.banner.encode())

            buffer = ""
            while not self._stop.is_set():
                try:
                    data = conn.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                buffer += data.decode("utf-8", errors="replace")

                while "\n" in buffer:
                    line, _, buffer = buffer.partition("\n")
                    command = line.strip()
                    self.received.append(command)

                    if self.behaviour == "close_early":
                        return
                    if self.behaviour == "silent":
                        continue

                    reply = self.responses.get(command, OK)
                    try:
                        conn.sendall(reply.encode())
                    except OSError:
                        return
