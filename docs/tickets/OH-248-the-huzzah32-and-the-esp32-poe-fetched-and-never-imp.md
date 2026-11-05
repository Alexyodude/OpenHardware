---
id: OH-248
title: 'The HUZZAH32 and the ESP32-POE, fetched and never imported, become manifest
  boards: three twin layers on a chip with no core'
status: open
priority: P2
created: '2026-11-05'
---

Slice of OH-174 (its fourth: 'the other two fetched sources, HUZZAH32 and ESP32-POE'). Filed 2026-11-05 with no claims; take it and claim with tickets.py set --touches.

tools/board_sources.py fetches adafruit-huzzah32 (Adafruit-HUZZAH32-ESP32-Feather-PCB: 'Adafruit HUZZAH32 ESP32 Feather.brd', EAGLE 6.6.0 XML) and olimex-esp32-poe (OLIMEX/ESP32-POE HARDWARE/, KiCad revisions B1 to M2; OH-198 made its KiCad 5 revisions read). Neither is a row in tools/board_manifest.py, so neither is in webui/boards/ or in the TWINS section of tools/inventory.py. Both vendors' pins are already on disk: third_party/bsp/arduino-esp32/variants/feather_esp32/ and variants/esp32-poe/.

Both are the classic ESP32 (Xtensa LX6), which has no core and is not in catalogue.FIRMWARE_VERIFIED, so they reach three layers (geometry, model, pins) and their runs cell reads ESP32:no. That is the order OH-174 gives: boards whose chip runs first, then boards that wait for a core. Whether a manifest row may name a chip with no core, and what the page shows for one, is part of this ticket; rules/board-claims.md is what the board must not overstate.

KNOWN BEFORE STARTING. (1) Licence: the HUZZAH32 repository's licence.txt is CC BY-SA 3.0 Unported (registry row, read 2026-08-25) -- the kind of question OH-234 raises for Seeed's files -- and ShareAlike reaches what is derived from the design files; decide, by rules/licence-hygiene.md, what of a derived board file may be committed before writing one. Olimex's ESP32-POE is Apache-2.0 (its sibling ESP32-POE-ISO has no LICENSE file, only a Licensee.pdf, and is out of scope). (2) The registry's own cell calls the HUZZAH32 .sch 'proprietary binary'; the .brd on disk is EAGLE XML, and OH-23's note already corrected the same mistake for three vendors. Check the .sch before relying on it for nets. (3) Which ESP32-POE revision is the board: the newest (M2, KiCad 7) unless a reason is written down. (4) OH-198 records that the PoE's KiCad 5 revisions B1 to I mark LAN_CON1, the RJ45, virtual, and that this is not read as not fitted.

DONE WHEN both boards are manifest rows that pass board_manifest.py --check, each pad names its chip pin or says why not, compose_board_3d.py composes each from its own file (as OH-180 did the Thing Plus), TWINS lists both with runs ESP32:no, and nothing on the page or in the catalogue claims either runs firmware.
