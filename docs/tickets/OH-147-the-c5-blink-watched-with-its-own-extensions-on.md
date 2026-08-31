---
id: OH-147
title: The C5 blink, watched with its own extensions on
status: done
priority: P2
created: '2026-08-31'
touches:
- tests/riscv32/c5blink/blink.c
- tests/riscv32/c5blink/blink.ld
- tests/riscv32/c5blink/blink.bin
- tests/riscv32/test_esp32c5_board.py
- webui/boards/catalogue.py
- tests/webui/test_board_catalogue.py
---

The half OH-146 deliberately left: `FIRMWARE_VERIFIED` names the chips a
real compiled image has been watched executing on, and the C5 is not in
it. The bar its own board file set was never "the core has the bits" —
it was an image compiled for this part **with its own extensions on**,
loaded by name and watched driving a pin.

The fixture is `c5blink`, the third sibling of `c3blink` and `c6blink`,
and reading the three side by side stays the point: same `_start`, same
shape, not one address in common with either — GPIO at 0x60091000 with
ENABLE at +0x34 where the C6's sits at +0x20, SRAM topping out at
0x40860000, all from ESP-IDF v5.5's esp32c5 headers as
`webui/boards/esp32c5.py` already cites them. Unlike its siblings it
USES the part's three groups: the delay's frame is `cm.push`/`cm.popret`
(Zcmp), the loop body round-trips `c.not` (Zcb), and the call reaches the
delay through `cm.jalt` and a 64-aligned JVT table (Zcmt) — hand-encoded
`.hword`s with the fields stated, because this machine's GCC 8.4
predates Zc and hand encodings the emulator's tests already verify are
better provenance than a newer toolchain nobody else here has.

DONE WHEN the image loads by board name at the C5's own flash window and
a watch sees GPIO8 blink with a steady period; the test asserts the
image contains all three groups' encodings, so the claim "with its own
extensions on" is checked rather than remembered; `FIRMWARE_VERIFIED`
gains ESP32-C5 naming `tests/riscv32/test_esp32c5_board.py`; the
described-and-claims-no-firmware test flips to described-and-verified;
and /api/boards reports both XIAO ESP32-C5 boards firmware_verified.

---

**CLOSED 2026-08-31.** The image is 260 bytes and does what the ticket
demanded: `_start` sets the stack at the C5's own SRAM top, `main` aims
JVT at a 64-aligned table with `csrw`, and the loop toggles GPIO8 through
`cm.jalt 32` into a delay framed by `cm.push {ra,s0}`/`cm.popret` whose
body round-trips `c.not` two hundred times. Measured on the emulated
board: on at step 15, then a single steady 408-step period, ENABLE
reading 0x100 -- and the period IS the Zc evidence, since every cycle of
it runs all three groups.

Three watch tests in the C6's shape (the blink, the output-and-period,
and the image-contains-the-encodings test that keeps "with its own
extensions on" checked rather than remembered), the
described-and-claims-no-firmware test flipped to
described-and-the-watching-is-named, and `FIRMWARE_VERIFIED` gained
ESP32-C5 naming this file -- its sixth chip, accepted by
`check_board_claims`. Two mutations killed: the C6's image swapped in
(three tests fail -- wrong GPIO offsets and no Zc halfwords), and the
catalogue claim dropped (the naming test fails).

The hand-encoded halfwords are provenance, not a shortcut: GCC 8.4
refuses `-march=rv32imac_zcb_zcmp_zcmt`, and each of the four `.hword`s
is already executed and asserted by `tests/riscv32/test_zc.py` before
this image runs them in sequence.
