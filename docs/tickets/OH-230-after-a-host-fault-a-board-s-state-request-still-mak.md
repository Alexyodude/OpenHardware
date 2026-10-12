---
id: OH-230
title: After a host fault, a board's state request still makes unguarded foreign reads
  and can be dropped
status: open
priority: P3
created: '2026-10-13'
---

Found by OH-225's review and recorded in its note (2026-10-13). OH-223 and OH-225 made a host fault in a core's step stop the session as "faulted" and answer every step and run request. But after such a fault -- one that may have corrupted the core's memory or the process heap -- `/api/board/state` still makes foreign calls with nothing around them:

- `BoardSession.state` through the machine module: `readable`, `is_register`, `word`, `view`, `read`;
- `uart_view`, `pin_levels` and `listing_view`.

If one of those faults on the host, ctypes raises OSError (on Windows), nothing above maps it, and the state request is dropped with no reply -- exactly what `/api/board/step` did before OH-225. The page polls state after every tick, so a board that faulted could leave the page unable to show anything about it. OH-223 did the same for the i8086 debugger's disassembly (a decoder fault becomes the listing's last line) but not for the board session.

STEPS:
1. Decide what `state()` should do when a read faults on the host: answer with what it could read plus a named line saying which read faulted (as the 8086 listing does since OH-223), not drop the request.
2. Wrap the foreign reads in each board core's binding as OH-225 wrapped `step` (HostFault from OSError, naming what was being read and where), and have `BoardSession.state` catch HostFault per section.
3. A test using OH-223's technique (monkeypatch the cached CDLL's read to raise OSError) through the real path to the server's answer, seen to fail first.

Claims: webui/api.py (OH-172's, lent to OH-161 then OH-225) and the board cores' abi.py; borrow when this starts.
