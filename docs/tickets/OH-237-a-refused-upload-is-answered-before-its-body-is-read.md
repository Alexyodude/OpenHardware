---
id: OH-237
title: A refused upload is answered before its body is read, so under load the client
  sees a reset instead of the 403
status: duplicate
priority: P3
created: '2026-10-14'
duplicate-of: OH-166
---

Seen 2026-10-14 by OH-161's Wire round: tests/webui/test_board_run.py::test_an_upload_from_another_origin_is_refused failed once with ConnectionAbortedError while the machine was loaded, and passed when run alone and in the confirmation pass's 210-test run. Diagnosis from reading, NOT reproduced: webui/emulator_server.py do_POST refuses on Origin (about :908-909) before it reads the request body (about :921). It sends the 403 with the declared body still unread, and on Windows closing a socket with unread data sends a reset (RST), so a client still writing or not yet reading can get ConnectionAbortedError instead of the 403. STEPS: 1. Reproduce: a test that posts a body larger than the socket buffer from a foreign Origin and asserts the 403 is read, run in a loop. 2. Read and discard the declared Content-Length, capped at MAX_BODY_BYTES, before any refusal that is sent after headers. 3. Check the other refusal paths in do_POST and bridge.py the same way. Claims nothing yet: emulator_server.py is OH-161's; borrow it when this starts.

**Note 2026-10-14:** Caveat on step 2: the 413 path (body over MAX_BODY_BYTES) deliberately judges the length from the header and never reads the body (its own comment says so); that must stay. For it, and for any refusal where reading is unwanted, the alternative is to send the response, shutdown(SHUT_WR), and drain with a short deadline rather than read the declared length. The Origin refusal is a different case: its body is at most MAX_BODY_BYTES once the 413 check runs first, so reorder or drain there.

Folded into OH-166.
