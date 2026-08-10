# OpenHardware — client for PICSimLab's remote control protocol.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Speak the TCP protocol implemented by ``src/lib/rcontrol.cc``.

The protocol, read from that file rather than inferred:

* On connect the server sends a banner ending ``\\r\\n\\r\\n>``
  (``rcontrol.cc:217``).
* Every command's reply ends ``Ok\\r\\n>`` or ``ERROR\\r\\n>``.

So a message is framed by the terminator ``\\r\\n>``, and the line before it
carries the status. That is the whole framing rule.

**Everything that goes wrong raises.** A timeout, a closed peer, an unframed
reply, an empty reply — each is an exception, never a partial or empty result
handed back as though it were data. This matters more here than in most
clients: upstream's own ``tests/python/test_blink.py`` wraps its assertions in
``except ConnectionError: print(e)``, so when the simulator is not listening
nothing is asserted and the test passes. A suite of those reports green on a
machine where the simulator never started. This module exists partly so that
cannot happen again, and ``.claude/rules/conformance-fixtures.md`` section 4
records it.

This client does not interpret command semantics — that is ``webui/api.py``.
It moves framed strings and reports failure honestly.
"""

from __future__ import annotations

import dataclasses
import socket

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
DEFAULT_TIMEOUT = 10.0

TERMINATOR = "\r\n>"
_OK = "Ok"
_ERROR = "ERROR"

_RECV_BYTES = 65536


class RControlError(Exception):
    """Base for every failure this client reports."""


class RControlConnectionError(RControlError):
    """The connection could not be made, timed out, or closed mid-message."""


class RControlProtocolError(RControlError):
    """A reply arrived but did not obey the framing rule."""


class RControlCommandError(RControlError):
    """The server framed a reply correctly and reported ERROR."""


@dataclasses.dataclass(frozen=True)
class Response:
    """One framed reply.

    ``body`` excludes the status line and the terminator, so a command that
    returns no data has an empty body and ``ok`` True. That is a real, valid
    outcome and is distinct from a failure, which raises.
    """

    ok: bool
    body: str
    raw: str

    @property
    def lines(self) -> list[str]:
        return [line for line in self.body.splitlines() if line.strip()]


class RControlClient:
    """A blocking client for one rcontrol session."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self.banner = ""

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> str:
        """Open the socket and consume the banner. Returns it."""
        if self._sock is not None:
            raise RControlError("already connected")
        try:
            self._sock = socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            )
        except OSError as exc:
            raise RControlConnectionError(
                f"cannot reach rcontrol at {self.host}:{self.port}: {exc}"
            ) from exc
        self._sock.settimeout(self.timeout)
        self.banner = self._read_framed()
        return self.banner

    def close(self) -> None:
        if self._sock is None:
            return
        try:
            self._sock.close()
        finally:
            self._sock = None

    def __enter__(self) -> RControlClient:
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- commands ----------------------------------------------------------

    def command(self, text: str) -> Response:
        """Send one command and return its framed reply.

        Raises RControlCommandError when the server reports ERROR, so a caller
        that ignores the return value still cannot mistake a failure for
        success.
        """
        if self._sock is None:
            raise RControlError("not connected; call connect() first")
        if "\n" in text or "\r" in text:
            raise ValueError(f"command must be a single line: {text!r}")

        try:
            self._sock.sendall((text + "\n").encode("utf-8"))
        except OSError as exc:
            raise RControlConnectionError(f"send failed for {text!r}: {exc}") from exc

        raw = self._read_framed()
        return self._parse(text, raw)

    def try_command(self, text: str) -> Response:
        """Like command(), but returns the failed Response instead of raising.

        For callers that legitimately expect ERROR — probing whether a part
        index exists, say. Connection and framing failures still raise: those
        are never an expected answer.
        """
        try:
            return self.command(text)
        except RControlCommandError as exc:
            return exc.args[1]

    # -- internals ---------------------------------------------------------

    def _read_framed(self) -> str:
        """Accumulate until the terminator arrives. Anything else raises."""
        assert self._sock is not None
        chunks: list[str] = []
        while True:
            try:
                data = self._sock.recv(_RECV_BYTES)
            except socket.timeout as exc:
                raise RControlConnectionError(
                    f"timed out after {self.timeout}s waiting for {TERMINATOR!r}; "
                    f"received so far: {''.join(chunks)!r}"
                ) from exc
            except OSError as exc:
                raise RControlConnectionError(f"receive failed: {exc}") from exc

            if not data:
                raise RControlConnectionError(
                    f"peer closed before sending {TERMINATOR!r}; "
                    f"received so far: {''.join(chunks)!r}"
                )

            chunks.append(data.decode("utf-8", errors="replace"))
            if chunks[-1].endswith(TERMINATOR) or "".join(chunks).endswith(TERMINATOR):
                return "".join(chunks)

    def _parse(self, sent: str, raw: str) -> Response:
        if not raw.endswith(TERMINATOR):
            raise RControlProtocolError(
                f"reply to {sent!r} is not framed by {TERMINATOR!r}: {raw!r}"
            )
        payload = raw[: -len(TERMINATOR)]
        lines = payload.split("\r\n")
        status = lines[-1].strip() if lines else ""

        if status == _OK:
            return Response(ok=True, body="\r\n".join(lines[:-1]), raw=raw)
        if status == _ERROR:
            response = Response(ok=False, body="\r\n".join(lines[:-1]), raw=raw)
            raise RControlCommandError(
                f"{sent!r} returned ERROR", response
            )
        raise RControlProtocolError(
            f"reply to {sent!r} ended with {status!r}, expected {_OK!r} or {_ERROR!r}"
        )
