---
id: OH-183
title: 'OH-179''s follow-ups: a prose run-claim about a manifest board is caught,
  and buildability is asked of the compiler'
status: open
priority: P1
created: '2026-09-29'
touches:
- docs/tickets/OH-183-*
---

Part of OH-174. OH-179's approving review (2026-09-29) found these; none blocked it. Two are MEDIUM and come first.

1. **A run-claim in prose about a manifest board is not caught.** tools/check_board_claims.py check 1 (lines ~312-331 at OH-179's tip) matches chip names, so "The SparkFun Thing Plus ESP32-C6 runs firmware." passes because the name contains ESP32-C6 and ESP32-C6 is in `FIRMWARE_VERIFIED`, while "The SAMD21 runs firmware." is caught. Match manifest board names before chip names; a board name beside a run-claim needs its own `BOARD_FIRMWARE_VERIFIED` entry. Pre-existing, and now reachable because manifest boards carry chip names.

2. **`unmet` in webui/compile.py reads C with regexes.** Compared against a real empty-sketch compile over all 404 upstream arduino-esp32 variants on the C6 and C3 recipes, it agreed on 402; the two misses (`kodedot`, `wt32-eth01`) are false refusals from several constants declared on one line. Constructed cases it gets wrong both ways include `#ifdef`'d definitions and uses, `<...>` includes, casts, `sizeof`, two-word types and `#undef`. A wrong pass only means the compiler then refuses; a wrong refusal switches off a buildable board; neither can make a false run-claim. Ask the compiler (a syntax-only compile of the table with the recipe's include path, cached) when the toolchain is installed, keep the header reading as the fallback, and add the all-variants comparison as a slow test.

3. The per-board name check accepts a test that names the board in an unused variable and loads a XIAO; rules/board-claims.md s7 says more than the check reads. Require the board name as the argument of the load call, or say only what is checked.
4. Both Feather tests fail rather than skip when the BSP is not fetched: they call `recipe_for` before the skip. Check the table file first.
5. A stock `LED_BUILTIN` blink on the Feather toggles GPIO15 in the core and nothing moves on the page, because the `IO15` pad has no `chip_index`. `pad_view`'s docstring promises the pin a stock Blink drives is reported. Decide whether a manifest board reports its variant's `LED_BUILTIN` as an on-board entry, as the XIAO's `LED` is, or whether OH-178's CAD-sourced pins close it (IO15 is a traced GPIO), and make the docstring true either way.
6. Stale prose: board-claims s6 names a test that no longer exists; compile.py ~281-288 says it builds for ten boards and now builds for eleven (cut the count); import_board.py ~600 says artwork is needed at `image.file`, which nothing reads.
7. "Is this a manifest board" is written out four times (api.py, compile.py, catalogue.py twice) while `board_manifest.row()` exists; one `find(name) -> Row | None`.
8. A manifest board with its BSP missing is refused at `recipe_for` (Build off); a XIAO in the same state gets ToolchainMissing at build time naming the fetch. Make them one behaviour.

Run after OH-178, which edits tools/board_manifest.py. webui/compile.py and tests/webui/test_compile.py return to OH-161 when this closes.
