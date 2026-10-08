---
id: OH-212
title: 'The licence cell names a licence-shaped file, not the file the registry reads
  the licence from: Olimex''s GPL text backs their CERN-OHL'
status: open
priority: P2
created: '2026-10-09'
---

Found by OH-204's review (2026-10-09). Since OH-204 the ASSETS licence cell in `tools/inventory.py` (`_licence_cell`) reads each board's own registry tree, but it still grades a licence by finding a file whose name looks like a licence (`LICENCE_STEMS`), without opening it. Its docstring's premise, "a licence file in the tree it came from is the licence", is false for the two Olimex boards: their `LICENSE` is the GPL-3.0 text covering the repositories' software (GitHub's licence API agrees, and `tools/board_sources.py` already skips that file as "the GPL-3.0's text"), while their hardware licences are stated in README.md and, on the C6-EVB, in `Hardware-License-CERN_OHL_v_1_2.pdf`. So both cells read as backing a CERN-OHL hardware licence with a GPL file.

The registry already records, per source, the file its licence is read from and the words quoted from it (`licence.file`, `licence.quote`), and `tests/rules/test_board_sources.py` verifies the quote is in that file. Grade a registry board's cell from that: present where the named file is on disk (or indexed where only in the clone's index), naming it. That makes the Olimex boards present on README.md and turns most of today's `absent` cells present (the Glyph C3 and C6 on README.md, the Qwiic Pocket's .brd, the Thing Plus C5's .kicad_pcb); the Thing Plus C6 has `file=''` and stays absent. XIAOs and other footprint-only boards keep today's reading.

From the same review, LOW:
- An `indexed` cell's detail says "in the vendor's git tree" with no root, so an Olimex row reads as if it were Seeed's tree. Name the tree.
- `tools/inventory.py` ~276 says every other board's `source` names "the vendor file its pads were read from"; XIAOs name a footprint (PROVENANCE §2b already says "or the footprint in one").
- `test_a_board_naming_neither_a_registry_nor_a_footprint_has_no_tree_to_back_it` asserts two behaviours (the footprint fallback and the neither case): split it.
- `test_a_licence_read_from_a_fetched_file_is_in_that_file` skips when the named file is missing in a fetched tree; it should fail when the tree's directory exists (a wrong `file=` name today passes as "unfetched").
- `webui/boards/atmega328p.py`'s HEADER comment calls RESET "no port pin"; Arduino's pins_arduino.h draws ZU4 pin 1 as PC6, which this module does not number. Say that.

Done when every licence cell names the file the registry reads its licence from, or says why there is none, a test fails if a cell is backed by a file the registry does not name, and the five lows are fixed.
