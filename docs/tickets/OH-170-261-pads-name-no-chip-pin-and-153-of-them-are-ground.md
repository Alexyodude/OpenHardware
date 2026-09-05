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
- webui/boards/XIAO-ESP32-S3-SMD.json
- webui/boards/XIAO-ESP32-S3-SMD_PAD.json
- webui/boards/XIAO-MG24-DIP.json
- webui/boards/XIAO-MG24-SMD.json
- webui/boards/XIAO-RP2350-SMD.json
- webui/boards/XIAO-nRF54LM20A-DIP.json
- webui/boards/XIAO-nRF54LM20A-SMD.json
- webui/boards/XIAO-nRF54l15-DIP.json
- webui/boards/XIAO-nRF54l15-SMD.json
- webui/boards/XIAO-XIAO STM32C5-SMD.json
- tests/webui/test_pin_view.py
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

**Note 2026-09-06:** STEP 3 was called `blocked on a vendor source` with the reason "there is
nothing to read". That is now measured to be wrong about two of its pads, and
the source had been in the tree the whole time.

`third_party/seeed-xiao/Seeed Studio XIAO Series Library/Seeed_Studio_XIAO_Series.kicad_sym`
is Seeed's own schematic symbol library, fetched by
`python tools/get_board_sources.py seeed-xiao`. Its `XIAO-STM32C5-SMD` symbol
has 35 pins, and pins 23 and 24 are named `SWDIO/PA13` and `SWCLK/PA14`. The
board file's own pad labels came from that library -- `import_kicad_board.py`
says so in its `derivation`, "Pin names joined from the symbol library on pad
number" -- so the pin was being printed on the pad and reported as unpublished
in the same file.

Read now, with a reader that sweeps the whole symbol and refuses if a pin it
was not opted in to read names one, so the board file's claim that the CAD
"names a pin beside those pad names and beside no others" is enforced rather
than asserted. Two of 35; the other 33 are unchanged and the ticket's own
sentence about them stands.

What is still blocked, and it is the part that mattered: `D0` through `D15`.
No source in the tree names a pin for any of them, the symbol library included
-- it prints them as bare `D0`..`D15`. That is 16 of this board's pads and
they need Seeed to publish something.

CORRECTED: this said 22, which is a real count of a different set. 22 is
the non-supply pads still null on this board -- the 16 bare `Dn` plus
`CANH`, `CANL`, `STM32C5_BOOT`, `STM32C5_RST`, `USB_D-` and `USB_D+`. The
sentence names `D0` through `D15` and there are 16 of those, counted from
the committed board file. No checker recomputes a number in a ticket note,
so this one is the reader's to verify and was wrong until a review did.

Three sentences the generator emitted were false the moment anything here
resolved, and all three are now derived rather than written down:

  - the board file's `derivation` said "`packages` is empty because there are
    none to name". It is not empty now.
  - its `assumption` said "null on every pad here". It counts them instead.
  - each pad's `why_null` said "no label on it resolves". It now says the CAD
    names no pin beside THIS pad, which is the per-pad fact.

`Package.firmware` is what keeps "no board-support package covers this board"
true across all of that. A schematic symbol library is CAD, not firmware, and
the three sentences key on that rather than on whether the board has any
source at all -- which was the same test only while it had none.

Also this pass: `nRF54_RST` on the nRF54LM20A SMD carried the generic sentence
while its two neighbours in the same debug cluster explained themselves. Seeed's
`nRF54LM20A.kicad_pcb` names that part's reset `nRESET_F2` on the net
`~{nRF54_RESET}`, apart from all sixty-six of its `Pn.nn` pads, so a reset has
no GPIO number to have. NOT claimed, because it was not traced: that the
exposed pad is on that net. No net in the file is called `nRF54_RST`; the
nearest, `nRF54_RST_CTL`, runs from the on-board ATSAMD11's `PA04_A3` to a
MOSFET gate whose drain sits on the reset net.

Counts after this pass, recomputed over every `webui/boards/*.json`:
naming 365, supplies 153, specific 42, generic 22, total 582.

**Note 2026-09-06:** A review of this ticket's work said `read_seeed_traced` "does not require
exactly one footprint" and that the nRF54LM20A's traced source "can never
answer" because "every pad function there carries a ball suffix". The first
was true and is fixed. The second found something real and named the wrong
cause, so it is recorded here with what was measured.

THE BALL SUFFIX IS NOT THE CAUSE. `_CHIP_PIN_NAME` ends `(?:[/_]|$)` and reads
straight through one: `P0.00_K3` gives `P0.00`, `P1.01_J1` gives `P1.01`. What
returns nothing is `SWDIO_G2`, and it returns nothing because SWDIO is not a
pin name on any part, suffix or no suffix.

WHAT WAS ACTUALLY WRONG. The source asked for four labels and two of them were
on no net of the MCU footprint at all, so the reader returned the same empty
answer for two different situations:

  nRF54_SWDIO   net found, MCU pad `SWDIO_G2`   -> nothing. CORRECT: the
  nRF54_SWCLK   net found, MCU pad `SWDCLK_G1`  -> nothing. silicon has no
                                                   GPIO number for a debug
                                                   pad, and `_NRF54LM20A_DEBUG`
                                                   says exactly that in words.
  SHPHLD        NO net on the MCU               -> nothing. WRONG SHAPE: this
  nRF54_RST     NO net on the MCU               -> nothing. is a citation that
                                                   names something absent.

`SHPHLD` is a pin of the board's nPM1300 -- the net exists, on that part's
`SHPHLD_D4` pad, and the pad's own `why_null` has said so correctly all along.
`nRF54_RST`'s net is spelled `~{nRF54_RESET}` and no net carries the pad's own
name, which this ticket already recorded when the reset reason was written.

THE COST WAS NEVER THOSE TWO PADS. Both were answered by `Board.reasons`, so
removing them changes no output: `--write-boards` prints 25 unchanged. The cost
is that a traced label reaching nothing was indistinguishable from one reaching
a dedicated pad. If a vendor revision renamed the `SWDIO` net in
`MG24.kicad_pcb`, that board's `PA02` and `PA01` would have vanished exactly
this quietly and its two pads would have fallen back to a generic null with
nothing raised. That is the same shape as the three permanently-skipped tests
and the negative control filtering on an absent phrase, both found earlier on
this ticket: a check that cannot fail.

FIX. `read_seeed_traced` now raises when a label is on no net of the part,
and keeps returning nothing when the label reaches the part and the pad is
outside its GPIO numbering. `SHPHLD` and `nRF54_RST` are removed from the
traced tuple, because with the raise in place they would refuse the generator.

`test_a_traced_label_that_reaches_nothing_is_refused_rather_than_silent` holds
both halves and was verified to discriminate: with the raise replaced by `if
False:` it fails with `DID NOT RAISE`, and it also asserts the ball-suffix
claim above is false, so the wrong cause cannot be re-adopted.

Measured after: 67 tests in tests/rules/test_import_pindefs.py (was 66), all
25 board files unchanged, eleven non-pytest checkers OK.

**Note 2026-09-06:** An adversarial review of c6015aa returned 18 findings. Every pin VALUE it
checked was confirmed correct, and no board file changed except the STM32C5's
`assumption`, whose sentence was weakened to what is actually enforced. What
the review found was claims stronger than their checks, which is the same
failure this ticket has now hit five times.

FIXED, code:

  - The reader's docstring said the other nineteen symbols name `D0` through
    `D15`. Swept: they run D0 through D27, and 51 of their names are not `Dn`
    at all -- supplies, function names, and nine pins literally named "15"
    through "23" on XIAO-Add-On-Plus. The load-bearing half (none of them
    names a pin) was true and is what the sweep checks; the decorative half
    was measured wrong. Same class as the "thirty-two pads that was 66".

  - `describe_registry` still keyed on `board.sources` being empty, so
    `--list` no longer marked the one board no firmware package covers -- the
    exact question its own docstring says it answers -- and its fallback
    became a branch no board can enter. Now keys on `firmware`, and a test
    asserts the mark appears on exactly one line.

  - `--fetch` printed "download by hand" for `seeed-xiao`, which
    `tools/get_board_sources.py seeed-xiao` fetches in one command, and the
    missing-checkout error told the user to run `--fetch`, which skips every
    `cloned=False` package -- a loop. `cloned=False` was carrying two
    meanings, which is what `Package.firmware`'s own docstring warns about.
    New `Package.fetch` and `how_to_fetch()`; both messages now name the
    command that works.

  - The sweep recognises a pin by `_CHIP_PIN_NAME`, which has no `P[E-H]`
    branch -- so a republished library naming `PE2` on this same STM32 part,
    or a Renesas `P100`, would pass it. The board file was generating "names
    a pin beside those pad names and beside no others", an absolute nothing
    checked. It now states the enforced claim: the only names carrying a pin
    in a spelling this tool recognises.

  - The sweep read only `(name "...")`. KiCad publishes a pin's function in
    `(alternate "...")` too, and the file has zero today, so an alternate is
    now refused (never resolved from) rather than being a second way past an
    alarm the board file's sentence rests on.

  - A pin naming two opted-in labels used to `continue` silently, and a label
    named twice took the last write. `read_seeed_net_names` refuses both, so
    one file held two rules for one situation. Both now raise.

  - `(text,) = texts` raised `ValueError`, which `main` does not catch, so a
    second path would have printed a traceback where every sibling prints a
    message.

  - The digest justification claimed a hand-downloaded source has no commit
    and `git rev-parse` inside it answers OpenHardware's own head. True of
    `seeed-pcb`, which has no `.git`. False of `seeed-xiao`, which has one
    answering f07e6ff. Both comments now state the reason that covers both:
    neither lives under `third_party/bsp/`, which is all `revision()` reads.

FIXED, tests:

  - The sweep's non-vacuity half named three of the nineteen symbols, 16% of
    a set the docstring and the board file both rest on. Derived from
    `_SYMBOL.findall` now, so all nineteen are checked.

  - Four raises in the symbol reader had no test at all, and `not named` is
    one line from the data (`XIAO-RP2040-SMD`, `SWDIO`). All five refusals are
    now reached by `test_every_refusal_in_the_symbol_reader_can_be_reached`.

  - `test_the_eight_committed_files_..._are_the_eight_oh_26_named` asserted
    nine, and an inline comment said so. A number in a test name is a claim
    under the same rule as a comment. Renamed; the count lives in the list.

  - `test_the_boards_with_no_source_are_deliberate` asserts the board HAS a
    source. Renamed to `test_the_board_no_firmware_package_covers_is_deliberate`.

  - "P0.00 through P3.12" was the one quoted number nothing recomputed -- the
    net name and the count of 66 were held, the span was not. Now derived per
    port from the vendor file.

Every new guard was verified to discriminate by breaking it on purpose: all
six go red (two opted-in labels, a label named twice, more than one library,
the alternate sweep, a traced label reaching nothing, and `describe_registry`
keyed back on `bool(sources)`).

NOT FIXED, and it is not mine to fix: `docs/tickets/OH-171-*.md` line 36 names
`test_the_boards_with_no_source_are_deliberate`, which is now
`test_the_board_no_firmware_package_covers_is_deliberate`. That file is
claimed by OH-171 and a ticket owns its own file, so whoever takes OH-171
should update the reference.

WHAT THE REVIEW CONFIRMED, so it is not re-litigated: every written pin value;
the symbol slicing (`^\t\(symbol` matched exactly the 20 top-level symbols and
excluded every nested unit); `covered` consistent across both call sites;
`--write-boards` exactly reproducible; the digest newline-stable at
1ac7294e54a5 despite the CRLF worktree; `_PIN_TOKEN` correct for a
port-numbered part with no falsy-zero bug; and the un-claimed trace boundary
on `nRF54_RST` holding, with `"reaches" not in why_null` a real discriminator.
