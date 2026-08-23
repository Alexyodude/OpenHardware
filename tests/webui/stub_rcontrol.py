# OpenHardware — a stub rcontrol server for testing the client.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
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

#: How long a blocking socket call waits before re-checking the stop flag.
#: Short enough that teardown is not noticeably slower than closing the socket,
#: long enough not to spin.
_POLL = 0.05


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
        #: Poll rather than block, so `__exit__` can retire the thread instead of
        #: closing a socket out from under it. See the note there.
        self._sock.settimeout(_POLL)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def port(self) -> int:
        return self._sock.getsockname()[1]

    def __enter__(self) -> StubRControl:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        """Retire the server thread first, *then* close the socket.

        The order matters, and getting it wrong is not portable. Closing a
        listening socket while another thread blocks in ``accept()`` aborts that
        call on Windows but **not on Linux**, where the blocked call keeps the
        kernel socket alive and the port therefore keeps accepting connections
        after ``__exit__`` returns.

        `test_connecting_to_a_closed_port_raises` passed on Windows for that
        reason and failed on Linux the first time CI ran it. Joining a thread
        that polls a stop flag gives the same answer on both.
        """
        self._stop.set()
        self._thread.join(timeout=2)
        try:
            self._sock.close()
        except OSError:
            pass

    def _accept(self) -> socket.socket | None:
        """Wait for one connection, giving up as soon as `_stop` is set."""
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return None
            conn.settimeout(_POLL)
            return conn
        return None

    def _serve(self) -> None:
        conn = self._accept()
        if conn is None:
            return
        with conn:
            if self.behaviour == "no_banner":
                return
            conn.sendall(self.banner.encode())

            buffer = ""
            while not self._stop.is_set():
                try:
                    data = conn.recv(65536)
                except TimeoutError:
                    continue  # a silent stub still has to notice teardown
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
