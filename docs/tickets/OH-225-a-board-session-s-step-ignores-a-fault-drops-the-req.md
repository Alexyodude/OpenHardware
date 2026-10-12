---
id: OH-225
title: A board session's step ignores a fault, drops the request on any core error,
  and the Cortex-M0 and RISC-V bindings let a host fault escape
status: open
priority: P2
created: '2026-10-12'
---

Found by OH-223 and its review (2026-10-12), by reading and through a live server. OH-223 gave the i8086 and AVR bindings a `HostFault(AbiError)` for a fault ctypes catches on the host, and made the 8086 debugger's session stop as "faulted". The board side is not done, because its files belong elsewhere:

1. `core/cortexm0/abi.py` and `core/riscv32/abi.py`: `cortexm0_step` and `riscv32_step` are bare foreign calls, so an `OSError` escapes `Cpu.step` and `BoardSession.run`, and `/api/board/run` drops the request. Each wants the AVR treatment from OH-223 (a HostFault naming where the core left the PC, no per-step read), or the instruction-start export OH-223's review recommended for the i8086.
2. `webui/api.py`'s `BoardSession.step` does not check status: after a run stopped on a host fault, `POST /api/board/step` answers 200 and steps the half-executed machine on (seen: the AVR's pc moved to 22).
3. `BoardSession.step` re-raises the core's `AbiError` and `Handler._api` maps none, so `POST /api/board/step` whose step faults gets no reply (RemoteDisconnected). That is true today for `Unimplemented` and `MemoryFault` as well as a host fault.
4. `BoardSession.run` reports a host fault as "stopped", the word a firmware memory fault gets; a distinct "faulted" would let the page say the simulator is at fault, as the 8086 debugger now does.

Claims: `core/riscv32/**` and the borrowed `webui/api.py` are OH-161's (api.py is OH-172's, lent to OH-161); `core/cortexm0/abi.py` and `webui/emulator_server.py` check with `tools/tickets.py owner` when this starts. Borrow rather than overlap.

STEPS: each of the four, with a test seen to fail first using OH-223's technique (monkeypatch the cached CDLL's step to raise OSError on the Nth call) through the real path to the server's answer.
