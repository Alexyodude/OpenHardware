---
id: OH-87
title: Reloading the page prints a stack trace, because the client hung up
status: done
priority: P2
created: '2026-08-28'
touches:
- webui/emulator_server.py
- tests/webui/test_emulator.py
---

REPORTED BY THE USER, pasted from their own terminal while asking why the 3D
model was not loading:

    Exception occurred during processing of request from ('127.0.0.1', 55568)
    Traceback (most recent call last):
      ...
      File "webui/emulator_server.py", line 790, in _send
        self.wfile.write(body)
    ConnectionAbortedError: [WinError 10053] An established connection was
    aborted by the software in your host machine

**NOTHING IS BROKEN AND THAT IS THE PROBLEM.** WinError 10053 on a write is the
client having gone away before the response finished: the page was reloaded, or
navigated away from, while a poll was in flight. `emulator.js` polls
`/api/board/state` on a timer, so every single reload of a running board
produces one of these. The request is lost, which is correct -- there is nobody
left to send it to -- and `ThreadingHTTPServer.handle_error` then prints a
twenty-line traceback about it.

So the one thing this server prints during normal use is a stack trace, and the
first thing a reader does with a stack trace is assume it explains whatever else
they were confused about. It is why the report arrived attached to a question
about the 3D view, which has nothing to do with it.

## WHAT IT IS NOT

Not a bug in `_send`, not a bug in the API, and not something a retry would fix.
A peer closing a connection is an ordinary event in HTTP and not an error this
program made. `http.server` reports it because its `handle_error` reports
everything.

## THE NARROW FIX, AND WHY IT IS NOT CATCH-AND-DEFAULT

`.claude/rules/python.md` rule 1 and `CLAUDE.md` rule 9 both refuse
catch-and-default, and this has to be written so it is not one. The three types
that mean "the peer hung up" -- `ConnectionAbortedError`, `ConnectionResetError`
and `BrokenPipeError` -- are declined by name, and every other exception still
reaches the default reporter with its traceback intact. No value is defaulted
and no failure is converted into a success: there is simply nothing to report
about a socket the other end has already closed.

## DONE WHEN

Reloading the page while a board is running prints nothing, a handler that
raises anything else still prints its traceback, and there is a test that can
tell those two apart.
