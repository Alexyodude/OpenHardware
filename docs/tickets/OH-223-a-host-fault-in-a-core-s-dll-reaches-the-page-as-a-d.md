---
id: OH-223
title: A host fault in a core's DLL reaches the page as a dropped request and a half-executed
  machine that keeps running
status: in-progress
priority: P2
created: '2026-10-10'
touches:
- webui/emulator.py
- webui/emulator_server.py
- core/i8086/abi.py
- core/avr/abi.py
- tests/webui/test_host_fault.py
- tests/avr/test_host_fault.py
- webui/static/emulator.css
---

Found by OH-222's review (2026-10-10), by running it. When a core's DLL faults on the host -- a divide error, an access violation -- ctypes on Windows catches the structured exception around the foreign call and raises `OSError` out of `Cpu.step()`. Nothing above it expects that:

- `webui/emulator.py`'s `Session.step` (~153-158) catches only `abi.Unimplemented`;
- `webui/emulator_server.py`'s `Handler._api` (~886-899) catches BoardRunError, FirmwareError and (ApiError, EmulatorError, ValueError), not OSError.

So the request gets no reply (RemoteDisconnected, a traceback on the server's stderr), and the machine is left half-executed: the core had already advanced IP past the instruction when it faulted, so the next step runs the instruction after it, status still "running". Shown with OH-222's IDIV against the unguarded DLL: the IDIV was silently skipped and the following HLT ran. OH-222 removed that one fault; this ticket is for the next one, whatever it is.

A fault in the core is the core's bug, and the page should say so and stop, not carry on from a state no instruction produced (rule 9: handle it at the boundary where it entered, with the values that caused it).

STEPS:
1. In each core's `abi.Cpu.step` (i8086 first; check avr, cortexm0, riscv32 for the same shape), turn an `OSError` from the foreign call into an `AbiError` subclass that names the core, CS:IP or PC, and the opcode bytes at it, chained from the OSError.
2. In `Session.step` (and the board session's run loop, if it has its own), set status to a terminal "faulted" with that detail and stop stepping; the page shows it the way it shows other stops.
3. A test that provokes a host fault deterministically without a real core bug -- e.g. a test-only export, or a stub library -- and asserts the status and the message, seen to fail first.
4. Say what happens on Linux, where the same fault is a signal ctypes does not catch and the process ends; whether anything should be done there (a subprocess per session is a larger design) is a decision to record, not to make silently.
