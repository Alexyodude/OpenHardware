---
id: OH-57
title: ESP32-C5 and C6 board descriptions, the four boards after the C3
status: done
priority: P2
created: '2026-08-25'
touches:
- webui/boards/esp32c5.py
- webui/boards/esp32c6.py
- webui/boards/catalogue.py
- tests/riscv32/test_esp32c5_board.py
- tests/riscv32/test_esp32c6_board.py
- tests/riscv32/c6blink/blink.c
- tests/riscv32/c6blink/blink.ld
- tests/riscv32/c6blink/blink.bin
- tests/rv32/conftest.py
- tests/rv32/test_gating.py
- tests/webui/test_board_catalogue.py
- tests/webui/test_board_run.py
- docs/esp-idf-reference.md
- .gitignore
---

Four of the seven C-series boards: XIAO-ESP32-C5-DIP/SMD and XIAO-ESP32-C6-DIP/SMD. Filed separately from OH-48's C3 because they are the widening pass, not the vertical slice, and because the C5 is not simply a C3 with different addresses.

catalogue.CHIPS records the difference and it is load-bearing:
    ESP32-C3  RV32IMC
    ESP32-C6  RV32IMAC
    ESP32-C5  RV32IMAC + Zcb/Zcmp/Zcmt

So the C6 adds A, and the C5 adds A plus three Zc* groups this core does not implement. core/riscv32/cpu.h:56 records kExtA as classified-and-refused, and cpu.h:72 records Zcb and Zcmp as absent from MODELLED rather than pretending the part lacks them.

That means a C5 board description written today would describe a part whose ISA this core cannot fully execute. THE HONEST MOVE IS TO SAY SO PER CHIP rather than to describe all three and let the difference surface as a fault twenty thousand instructions in. A board is runnable when a core is built and a description exists; whether that core implements the part's whole ISA is a separate claim, and rules/board-claims.md governs it -- only a named test that watched an image execute licenses "runs firmware".

So: describe the C6 and the C5, and let each one's FIRMWARE_VERIFIED entry be earned or withheld on its own evidence. Expect the C6 to be reachable and the C5 to need Zcb/Zcmp/Zcmt first, and record that rather than discovering it.

Also unresolved and worth the next reader's attention: the ESP32-C61 is a real Espressif part and webui/boards/catalogue.py's chip_for has a delimiter check specifically because XIAO-ESP32-C61-DIP once resolved to ESP32-C6. There is no C61 board in the catalogue today. If one arrives it is a different chip, not a C6 variant.

Depends on OH-54, OH-47 and OH-48. Done when the C6 and C5 boards report runnable in the catalogue, each states which of its ISA this core executes, and any firmware claim names a test that watched a real image.

**Note 2026-08-25:** Done 2026-08-25 (13d3148). 8 runnable boards -> 12, 8 firmware-verified -> 10.

SOURCE. The first obstacle was real and cost the first hour: no installed tree
carries esp32c6 or esp32c5 headers, and the PlatformIO registry's newest
framework-arduinoespressif32 is 3.20017 (ESP-IDF 4.4.7), so there was nothing
to upgrade to. Numbers now come from a sibling ESP-IDF v5.5.0 checkout
(8c750b0), documented in docs/esp-idf-reference.md. What licensed it is a test
rather than a judgement: v5.5's own esp32c3 headers reproduce every number
webui/boards/esp32c3.py carried from 4.4.7, checked by
test_the_new_header_tree_reproduces_the_board_this_repository_already_had.

WHAT THIS TICKET WAS RIGHT ABOUT. "The C5 is not simply a C3 with different
addresses" understates it. The C6 shares exactly one base address with the C3
and even that is a different size. The C5 shares the C6's GPIO base and not its
register offsets: GPIO_ENABLE moved 0x20 -> 0x34 and GPIO_IN 0x3c -> 0x64, so
0x3c, which is GPIO_IN on a C3 and a C6, is GPIO_ENABLE_W1TC on a C5. A copied
board would map a write-one-to-clear enable register where it believed a
read-only input was, and that does not fault -- it works, wrongly. Pinned by
test_the_c5_register_file_is_not_the_c6_one.

Two more per-chip facts worth not rediscovering: the C6's flash window top is a
BUILD OPTION (soc.h:155 writes it as SOC_IROM_LOW + (SOC_MMU_PAGE_SIZE<<8) and
soc_caps.h:298 marks the page size configurable), where the C5's soc.h prints
both ends as literals; and both parts have SOC_MMU_DI_VADDR_SHARED, so SRAM has
ONE address, not the C3's two -- their memory maps are complete where the C3's
is knowingly partial.

C6: earned. tests/riscv32/c6blink/blink.bin, its own image at its own
addresses, watched driving GPIO8 at a 606-instruction period. The evidence that
it is a different part rather than a renamed C3 is that the same amoor.w
encoding is Illegal on a C3 board and Unimplemented on a C6 one.

C5: described, claim withheld, as this ticket predicted. The board declares ISA
(the datasheet's string), EXECUTES (the subset set_isa is given) and ABSENT
(the difference). All 4,224 encodings the three Zc groups occupy were swept and
none executes.

KNOWN COST, NOT A GAP TO IGNORE. A Zc encoding on a C5 board is refused as
Illegal, which claims the silicon lacks it -- false. Unimplemented is the true
word and this core has no bit to classify Zcb/Zcmp/Zcmt with, so set_isa cannot
be told. Fixing it is core work (three bits, three letters) and is the same
work the withheld FIRMWARE_VERIFIED entry waits on. Asserted by
test_an_absent_group_is_refused_as_illegal_which_is_the_weaker_true_thing, so
doing that work fails a test that says what to change.

THE COUNTDOWN WAS THREE TESTS, NOT ONE. This ticket's warning named
test_each_refusal_arrives_as_itself. Two more depended on the same vanishing
example: test_every_refusal_has_a_reason_and_every_reason_is_documented, and
test_a_chip_nothing_describes_is_refused_even_with_a_built_core -- which had a
pytest.skip escape hatch and so DEGRADED SILENTLY rather than failing. All
three now use a tmp_path catalogue (only_undescribed / UNDESCRIBED in
tests/webui/test_board_run.py). Skip count is back to 17.

Also done: tests/rv32/conftest.py gained an ESP32-C5 TARGETS row, and
test_the_extension_letters_match_the_abi_bitmasks now checks TARGETS["ESP32-C5"]
- MODELLED equals webui/boards/esp32c5.py's ABSENT, so the two spellings cannot
drift.

RESIDUAL, deliberately not done here: the UI does not surface which of a
board's ISA this core executes. Both board modules state it and tests pin it,
but a person picking XIAO-ESP32-C5-DIP sees only catalogue.CHIPS's full string.
The wire has no field for it and adding one is UI work, not board work.
