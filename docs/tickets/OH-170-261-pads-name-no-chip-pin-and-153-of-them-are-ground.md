---
id: OH-170
title: '261 pads name no chip pin, and 153 of them are ground: the other 108 are three
  separate jobs'
status: open
priority: P1
created: '2026-09-06'
touches:
- webui/boards/Arduino Uno.json
- tools/import_pindefs.py
- tests/rules/test_import_pindefs.py
---

261 of 582 pads still name no chip pin, and the reasons are three different things wearing one null.

OH-167 made the resolved map reach the page: 343 pads now name their MCU pin where 147 did. This ticket is the rest of them, counted and separated, because "not complete" is true and a single number hides three unrelated jobs.

Measured 2026-09-06 over every `webui/boards/*.json`, by the label on the pad:

  153  power and ground, correctly null. GND on 62 pads, 3V3_OUT on 29,
       VBUS 24, VBAT 12, EN 9, NC 4, VIN 3, and the Uno's AREF, IOREF and
       RESET. A GND is not a GPIO and a chip pin for one would be a
       sentence about the program where the truth is about the board --
       `atmega328p.HEADER` already deliberately excludes exactly this set,
       and `test_the_uno_maps_every_pad_with_an_mcu_pin_behind_it` holds it.
       **Nothing to do here and it is the largest group**, which is why the
       raw 261 is the wrong number to work from.

  108  not power. These are the ticket, and they are three jobs:

STEP 1 -- the Arduino Uno, 22 pads, and the data is already in hand twice.

Its pad records carry `label`, `pin`, `x`, `y`, `group` and nothing else: no `chip_pin`, no `chip_index`, and no `why_null` either, so its 32 nulls are the only ones in the tree with no reason recorded beside them. `tools/import_pindefs.py` is keyed on XIAO board names (`_BOARDS` at :636) and has never seen this board.

It is the inverse of the thirteen boards OH-167 fixed: there the file spoke and the module was silent, here the module speaks and the file is silent. The page is right today only because `atmega328p.PIN_NAMES` supplies all 22 -- `13` -> `PB5`, `SDA` -> `PC4` and so on -- so this is a file-format inconsistency and not a missing fact.

Two independent sources for it, both already in the tree: `PIN_NAMES` itself, and `third_party/arduino-uno/UNO-TH_Rev3e.brd`, whose nets this repository has already read twice -- the Uno's own `assumption` field records every label being confirmed against the net its pad sits on, 2026-08-27, and OH-169 traced the LED through the same file. Done when the Uno's file states what its module states, the two are asserted equal rather than merged by hand, and `chip_pin_of` becomes a fallback nothing needs on this board rather than the only thing holding it up.

STEP 2 -- the debug, strap, USB and NFC pads, about 60 across eleven boards. `requires reading a datasheet per chip`.

  SWDIO, SWCLK          5 and 4 boards; the Arm debug port
  MTDI, MTDO, MTMS,
    MTCK                4 boards each; the ESP32's JTAG, which ARE GPIOs
  BOOT                  3 boards; a strap pin, also a GPIO after reset
  NFC1, NFC2            3 boards; the nRF's NFC antenna pins, GPIOs when
                        the NFCT protection bit is cleared
  USB_DN, USB_DP        2 boards
  CANH, CANL            the STM32C5
  USER_LED              the nRF54L15 SMD -- and OH-169 wants exactly this

Every one is a real pin of the chip. They are null because `import_pindefs.py` reads Arduino board-support packages, which define Arduino digital labels and nothing else: a JTAG pad is not `D6`, so nothing in a `pins_arduino.h` mentions it. The mapping is in each chip's datasheet pin table, which is a different source and a different reader.

**`SAMD11_*` and the `nRF54_*` pairs are NOT this**, and lumping them in would be the error this ticket exists to avoid. `SAMD11_SWDIO`, `SAMD11_SWCLK`, `SAMD11_EN`, `SAMD11_RST2` are pins of the on-board DEBUGGER's own SAMD11, a second chip. `chip_pin` on those pads would have to say which chip it means, and today the field cannot. Decide that before writing any of them; leaving them null is honest and writing the wrong chip's pin is not.

STEP 3 -- XIAO-XIAO STM32C5-SMD, 26 pads including `D0` through `D15`. `blocked on a vendor source`.

The only board where the ordinary header pins are unresolved. Its file states the reason itself: "no board-support package covers this board at all, so no label on it resolves". OH-26 measured the same, 0 of 35, and recorded that this board has no page on the vendor's wiki either -- it is also the one board with no 3D model, for the same absence.

Blocked and not merely undone: there is nothing to read. It needs Seeed to publish something, or a schematic. Do not fill it from a family resemblance to the C3 -- OH-26's first trap is that the label is not the GPIO and the mapping is per board, measured, with `D6` being GPIO0 on an RP2040 and GPIO21 on an ESP32-C3.

Also noticed and not fixed here: `webui/boards/XIAO-XIAO STM32C5-SMD.json` has a doubled name prefix, which OH-26 flagged as a likely OH-25 import bug and which nobody has picked up since.

WHAT DONE LOOKS LIKE. Not "582 of 582", which would mean inventing a GPIO for every ground pad. The number to move is the 108, and step 1 is 22 of them with the answer already written down in two places.

**Note 2026-09-06:** Step 1 done 2026-09-06: the Uno's file states its 22 chip pins and every null pad says why. Board files now state 343 of 582, which is exactly what the page shows -- before, the files said 321 and the page 343, the difference being the Uno's module propping it up. Pads with no chip pin and no recorded reason: 0, down from 32. Steps 2 and 3 remain, and step 3 is blocked on a vendor source that does not exist.

**Note 2026-09-06:** Steps 1-3 done 2026-09-06; 321 -> 363 of 582 pads name a chip pin, and every pad now sits in one of four counted states (363 named, 153 supply, 43 with a specific reason, 23 generic). Three new sources in import_pindefs.py: arduino_chip reads every variant of a chip and refuses on disagreement (the ESP32-S3's JTAG and USB, five agreeing variants); seeed_pcb reads Seeed's own KiCad net names (the C5/C6 JTAG, the NFC pairs); seeed_pcb_traced follows a pad's net to the board's own MCU footprint (the MG24's SWDIO=PA02, SWCLK=PA01). Per-label reasons replace the generic sentence where the fact is different: a dedicated debug pad outside the GPIO numbering (RP2350, nRF54L15, nRF54LM20A), a pin of the on-board ATSAMD11 debugger, and a pin of the nPM1300 power IC. STILL OUTSTANDING, 23 pads: the C5's and C6's ten are READ and blocked only on OH-161 releasing webui/boards/esp32c5.py and esp32c6.py, with the values in the registry's comments; SWDIO/SWCLK on the RP2040, SAMD21 and nRF52840 need a datasheet because Seeed publish no KiCad for those three in this tree; and BOOT on the C6 and RP2350, MG24_EN, nRF54_EN, nRF54_RST, USER_LED, 54L15_RX20/TX20 have nets naming no pin. The STM32C5's 35 already carried the specific 'no package covers this board at all'.
