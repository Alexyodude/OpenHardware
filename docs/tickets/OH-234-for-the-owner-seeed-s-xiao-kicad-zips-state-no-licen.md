---
id: OH-234
title: 'For the owner: Seeed''s XIAO KiCad zips state no licence, carry a CC BY-SA
  logo, and the repo records their basis two contradictory ways'
status: open
priority: P2
created: '2026-10-13'
---

FOR THE OWNER: a licence decision, found by OH-231 (2026-10-13) and left for you by the stand-in, because it sets the basis behind committed board files.

Seeed's XIAO KiCad project zips, downloaded by hand from files.seeedstudio.com into the gitignored third_party/seeed-pcb/, feed two things: tools/import_pindefs.py traces their nets into committed board files (which MCU pin each pad reaches), and tools/compose_board_3d.py composes gitignored meshes from their copper, silkscreen and placements. The repository states their licence two contradictory ways:
- tools/compose_board_3d.py ~2395-2398 (PCB_CACHE) and tools/import_3d_model.py ~46-48: the archives "state no licence at all".
- tools/import_pindefs.py ~1998-2005, Package "seeed-pcb": "OSHW, per Seeed's XIAO series repository" -- but that GitHub repository is MIT and holds only footprints, not these zips' content.
The second string is copied into each traced board file's "licence" field: webui/boards/XIAO-ESP32-C5-DIP.json webui/boards/XIAO-ESP32-C5-SMD.json webui/boards/XIAO-ESP32-C6-DIP.json webui/boards/XIAO-ESP32-C6-SMD.json webui/boards/XIAO-MG24-DIP.json webui/boards/XIAO-MG24-SMD.json webui/boards/XIAO-nRF54LM20A-DIP.json webui/boards/XIAO-nRF54LM20A-SMD.json webui/boards/XIAO-nRF54l15-DIP.json webui/boards/XIAO-nRF54l15-SMD.json 

What the zips carry: no LICENSE file in any. The ESP32-C3, ESP32-C5, ESP32-C6, MG24 and nRF54LM20A zips (and the new STM32C5 zip, OH-231) carry a LOGO_CC_BY-SA_4.0 symbol reading "CC BY-SA 4.0" on their schematic sheets; the RP2350 and nRF54L15 zips carry none, yet both nRF54L15 board files carry the OSHW string. The ESP32-C3 zip feeds only the 3D model. Seeed also publishes the STM32C5's pin map under Apache-2.0 in its Zephyr board (platform-seeedboards).

OPTIONS:
1. Record "none stated" for every seeed-pcb zip, agreeing with the composer; regenerate the board files.
2. Accept the logo as a CC BY-SA 4.0 grant where it appears, and decide whether ShareAlike reaches the committed pin tables (facts) or the local meshes.
3. Ask Seeed.

OH-231 meanwhile records the STM32C5 zip as "none stated", with the logo noted as seen and not taken as a grant, and cites this ticket; it does not change the shared package or the other board files.

Claims: none until decided; tools/import_pindefs.py (OH-172's, lent to OH-231), tools/compose_board_3d.py and tools/import_3d_model.py (OH-163's, lent to OH-226) are borrowed when this starts.
