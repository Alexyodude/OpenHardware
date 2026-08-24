---
id: OH-43
title: Show a board's UART output in the browser
status: done
priority: P1
created: '2026-08-25'
touches:
- webui/static/emulator.html
- webui/static/emulator.js
---

OH-33 modelled UART0 and a real compiled image prints through it: tests/cortexm0/test_uart.py watches 'hello, world' come out of tests/cortexm0/uart/hello.bin, and webui/boards/rp2040.py's uart0_output() returns the bytes. What is missing is the last hop -- nothing shows them to a person.

OH-33's own done-when included 'a firmware printf reaches the UI' and this is the part of it that was NOT delivered, because the seam is in webui/emulator_server.py and webui/api.py, which OH-32 claims. That ticket already added POST /api/board/load, POST /api/board/run and GET /api/board/state, so the natural shape is for /api/board/state to carry the captured output alongside the registers it already returns, and for a console panel to render it.

Coordinate with OH-32 before starting: the route and the BoardSession are its files, and this ticket claims only the two static ones. A checker exists for the claim this must not make -- rules/board-claims.md -- so the panel must not describe a board as running firmware except where FIRMWARE_VERIFIED says so.

Done when a person can pick XIAO-RP2040-DIP in the browser, load tests/cortexm0/uart/hello.bin, press run, and read 'hello, world' on the page.
