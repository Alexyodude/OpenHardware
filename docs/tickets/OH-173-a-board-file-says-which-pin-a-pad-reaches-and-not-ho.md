---
id: OH-173
title: 'a board file says which pin a pad reaches and not how strongly that is known:
  12 pads rest on other vendors'' boards and read identically to the 331 that do not'
status: open
priority: P2
created: '2026-09-06'
---

The committed board files drop the per-pad citation, so two pins with very
different evidence behind them are written identically.

`board_report` records it. `python tools/import_pindefs.py XIAO-ESP32-S3-SMD`
prints, for two pads of the same board:

  D0     = GPIO1   zephyr boards/seeed/xiao_esp32s3/seeed_xiao_connector.dtsi
                   arduino-esp32 variants/XIAO_ESP32S3/pins_arduino.h
  MTMS   = GPIO42  arduino-esp32 variants/*/pins_arduino.h for every esp32s3
                   board in boards.txt

`D0` is Seeed's own statement about this board, twice over. `MTMS` is what 158
esp32s3 variants agree on -- Espressif's own development kit among them, but
also Heltec's and Waveshare's boards, which are not this board. `read_chip_pins`
already says in its own docstring that the agreement is a regression alarm and
not a proof, and that what makes those six safe is an allowlist somebody checked
against the part's IO_MUX table.

`filled_board` then writes `label`, `pin`, `chip_pin`, `chip_index`, `why_null`,
`x`, `y`, `group` -- and no source. So the file that the page and every other
reader consult cannot tell the two apart, and a reader who wants to knows to run
a command instead. The distinction survives only in a docstring in
`tools/import_pindefs.py`, which is not where a consumer of the data looks.

Measured 2026-09-06 over the 25 registry boards, by which source answered:

   114  arduino-esp32 + zephyr        the board's own files, both packages
    63  zephyr                        the board's own devicetree
    44  arduino-pico + zephyr         the board's own files
    22  silabs-arduino + zephyr       the board's own files
    22  seeed-samd + zephyr           the board's own files
    22  seeed-nrf52 + zephyr          the board's own files
    16  silabs-arduino                the board's own variant
    16  arduino-pico                  the board's own variant
    12  arduino-esp32                 EVERY esp32s3 variant, not this board
     8  seeed-pcb                     the board's own CAD, traced
     2  seeed-xiao                    the board's own schematic symbol
   ...
   343 total, of which 12 rest on files that are not about this board, and
   they are the 12 in the `arduino-esp32` row: `MTMS`, `MTDI`, `MTDO`, `MTCK`,
   `USB_DN` and `USB_DP`, six each on `XIAO-ESP32-S3-SMD` and its `_PAD` twin.
   A first draft of this ticket said 26 and added "the fourteen read the same
   way on the C3 and C5". There are none: the C5's and C6's JTAG pads were
   read and deliberately not written, because writing them changes what
   `esp32c5.py` and `esp32c6.py` must state and those belong to OH-161. The
   number above is counted, not carried over.

The 22 Arduino Uno pads are not in this count -- that board is not in
`import_pindefs`'s registry and its pins come from `webui/pinmap.py`, measured
off PICSimLab's own board.svg.

TWO SHAPES, and the choice is the ticket:

1. Carry `sources` per pad into the board file, as `board_report` already
   builds it. Truest and largest: every file grows by a line per resolved pad,
   and a pad's record then changes whenever a vendor's revision does, which is
   already true of the file's `packages` block but not of its pads.

2. Carry one word. A `pin_source` of `own` / `family` per pad -- whether the
   files read were about this board or about other boards carrying the same
   part. That is exactly the distinction above and nothing else, and it does
   not move when a vendor commits.

Shape 2 is smaller and answers the question that was asked. Shape 1 answers
questions nobody has asked yet. Decide before writing either.

DO NOT let this become a third meaning for `chip_pin`. OH-172 is open on that
field already carrying two, and a provenance answer smuggled into the same
column would make it three.

Found in review of OH-170, which added the sources that make the asymmetry
visible: before it, no pad was resolved from another board's files at all.
