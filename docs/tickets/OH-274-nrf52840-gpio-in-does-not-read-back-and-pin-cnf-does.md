---
id: OH-274
title: 'nRF52840 GPIO: IN does not read back and PIN_CNF does not reset to 0x2'
status: open
priority: P3
created: '2026-11-05'
---

Found 2026-11-05 under OH-64. webui/boards/nrf52840.py maps PIN_CNF[n] bit 0 onto DIR bit n with the core's map_field primitive; the rest of PIN_CNF is a plain word that starts at zero, where the PS (v1.7, 6.9.2) resets it to 0x00000002 -- INPUT = disconnect. Nothing reads its other fields yet, so no answer is wrong today, and the module's comment says so. GPIO_IN (0x510) is not modelled at all: a sketch reading a button or its own output back reads whatever the core's memory holds.

Done when: PIN_CNF resets to 0x2, IN reflects driven outputs and the board's inputs with the INPUT field's buffer-disconnect honoured (disconnected reads 0), and a test reads each back. Needs OH-64.
