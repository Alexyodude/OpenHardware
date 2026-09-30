---
rule: board-claims
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_board_claims.py
    armed: true
  - tier: TEST-ENFORCED
    checker: tests/webui/test_board_catalogue.py
    armed: true
  - tier: TEST-ENFORCED
    checker: tests/webui/test_compile.py
    armed: true
  - tier: TEST-ENFORCED
    checker: tests/rules/test_board_manifest.py
    armed: true
---

# Board claims

A board may say it runs firmware only where a named test watched a real
compiled image execute on it. Everything else — a built core, a board
description, a chip whose siblings work — is a fact about this repository, and
none of them is evidence that anything has ever run.

## 0. 2026-08-25 — why this exists now

The mechanism was already here, as a dict and a docstring.
`webui/boards/catalogue.py` carries `FIRMWARE_VERIFIED`, mapping a chip to the
test that watched an image execute, and beside it the sentence that is the
whole principle:

> Having a built core and a board description means a board *could* run
> something; it is not evidence that anything has. The distinction is small on
> a good day and the whole difference on a bad one.

Today that is one entry — RP2040, `tests/cortexm0/test_blink.py` — and until
now one test checking the named file exists. As boards multiply, so does the
pressure to relax it. A chip whose core is built and whose siblings work *will*
look runnable, and nothing outside that dict stopped the word appearing beside
it.

The repository has already refused this twice, and both refusals were correct:

- **OH-13** refused to let the generated board list call 25 unwired boards
  "supported". 582 pads across 26 boards, 28 of them carrying a simulator pin
  index, and all 28 on one board — the data forced the honesty.
- **OH-19** kept surveyed-but-unbuilt chips out of the target selector
  entirely, rather than listing them disabled, because *"an option you can
  never pick is a promise the repo has not made."*

Both were decisions somebody made and somebody else has to remember. This rule
is what makes them structural instead.

## 1. 2026-08-25 — the register is `FIRMWARE_VERIFIED`, and it is the only licence

One dict, in `webui/boards/catalogue.py`, chip to test path. A chip is in it or
the claim cannot be made.

Adding an entry is not a matter of pointing at a plausible file. The named test
has to name a compiled image that exists beside it, read that image off disk,
and step a CPU over it — checked in §2.5, so an entry cannot be argued into
place.

Deliberately keyed by **chip, not board**. `XIAO-RP2040-DIP` and
`XIAO-RP2040-SMD` differ in their pads and not in what executes, so evidence
gathered on one is evidence for both. Keying by board would demand a blink test
per package, which buys nothing and would be quietly skipped.

## 2. 2026-08-25 — SCRIPT-ENFORCED: nothing outside the register may say it

`tools/check_board_claims.py`, run before every commit and in CI. Five checks,
because there are five separate ways the claim comes loose from its evidence:

| # | Function | Fails when |
|---|---|---|
| 1 | `unevidenced_chip_claims` | a chip from `CHIPS` is named on a line that says firmware runs, and that chip has no entry |
| 2 | `ungrounded_code_claims` | a code surface says firmware runs and never reads `firmware_verified` anywhere in the file |
| 3 | `claims_decided_by_a_weaker_fact` | `runnable`, `core_built`, `core_exists` or `described` decides a run-claim |
| 4 | `missing_evidence` | the register names a test that is not on disk |
| 5 | `evidence_that_never_loads_an_image` | the named test names no image that exists, or never reads one, or never steps |

Checks 1 and 2 are the same requirement seen from two sides, and neither alone
is enough. Check 1 reads a chip name, so it catches prose — the sentence in a
document that says the ESP32-C3 board runs firmware — and is blind to a badge
reading `RUNS FIRMWARE`, which names no chip at all. Check 2 catches exactly
that badge, by asking whether the file rendering it consults the register, and
is blind to the prose, because a document does not consult anything.

Check 3 is the mistake that has already happened. The badge did read
`RUNS FIRMWARE` for anything with a built core and a description, where an
empty `samd21.py` would have earned it. `runnable` is a true and useful fact —
it says an image *could* be attempted — and it is one word away from the claim
it is not.

Check 5 is what stops the register being satisfied by a file that merely
exists. All three of its conditions must hold **in the named file itself**:
evidence you have to chase through three modules is evidence nobody checks.

### It is a check on vocabulary, not on meaning

The phrase table in the checker is deliberately narrow: `runs firmware`,
`running firmware`, `ran firmware`, `firmware runs`, `firmware verified`, and
their inflections. Every entry is a phrase that would be a lie if no image had
executed.

"runnable", "supported" and "works" are **not** in it. Those are claims about
the repository, they are legitimately used as such, and matching them would
report lines nobody can act on — which is how a check gets switched off, taking
the rest of it along.

The cost is that a surface which claims a board works while avoiding the word
"firmware" passes. That is a gap in the table, and widening the table is cheap;
it is not a gap in the mechanism.

## 3. 2026-08-25 — TEST-ENFORCED: the set itself is pinned

`test_only_the_board_a_real_image_ran_on_claims_to_have_run_one` in
`tests/webui/test_board_catalogue.py` asserts the verified set is exactly
`{"RP2040"}`.

That looks redundant beside §2 and is not. §2 checks that an entry is
*well-formed* — a real test, naming a real image, reading and stepping it. The
pin checks that an entry was *intended*: adding a chip means editing a test
whose name says what it is protecting, in a second file, on purpose. A
well-formed entry can still be a wrong one, and this is the layer that makes
adding one a decision rather than a diff.

## 4. 2026-08-25 — what is not a surface, and why each is not

The checker walks the tree and treats every file as a surface unless excluded.
Default-on is the right direction: the opposite default is how a new page ships
making an old claim.

| Excluded | Because |
|---|---|
| `tests/` | the evidence, not the claim |
| `third_party/` | a vendor talking about their own silicon |
| `patches/` | upstream code with a diff on it; upstream's words |
| `docs/tickets/`, `docs/HANDOFF_*` | the record of what was decided and when |
| `docs/research/` | somebody thinking, not the project speaking |
| `build/`, dot-directories | generated output, caches, editor state |
| `rules/board-claims.md`, `tools/check_board_claims.py` | this rule quotes the claim it governs |

`third_party/` is the one worth spelling out, because excluding it looks like a
convenience and is not. The first thing this checker found there was Seeed
saying their DAPLink firmware runs on a SAMD21. It does — on real silicon. What
a vendor says about their own hardware is not this repository claiming its
emulator runs anything, and collapsing the two would fail the check on
documents nobody here can edit.

## 5. 2026-08-25 — known weaknesses, stated rather than left implicit

**The checker sees the tree, not the index.** It walks the filesystem, so an
untracked machine-local directory of the wrong shape would be scanned. Dot-
directories and the table above cover what exists today; a new one needs an
entry. The failure mode is a false positive, which is loud, and that is the
direction a checker should fail in.

**Check 3 looks up, not down.** A weaker fact counts as deciding a run-claim
only on the claim line or the two above it — enough for a condition and its
body. It was symmetric first, and immediately reported the strip counter in
`webui/static/emulator.js`, where a `runnable` three lines up decides a
different cell entirely.

**A passing run is not evidence that a board works.** It proves every claim
points at a test that touches a real image. A test that loads an image and then
asserts nothing satisfies check 5 completely. That is what review is for, and
saying so here is cheaper than a rule that overstates its own enforcement.

## 6. 2026-09-29 — keyed by chip only while siblings build identically

§1 keys the register by chip because `XIAO-RP2040-DIP` and `XIAO-RP2040-SMD`
build one image from one variant. That reason is the whole licence for
sharing the claim, and it holds only while it is true of the boards sharing
it.

The SparkFun Thing Plus ESP32-C6 (OH-176) is the first board where it is not.
Its chip is in the register, and `webui/compile.py`'s ESP32-C6 recipe reads
its pin names from `arduino-esp32/variants/XIAO_ESP32C6`, not from the
board's own `sparkfun_esp32c6_thing_plus`. Built that way, its `SDA` and
`SCL` are other GPIOs than its own variant names.

**A board built against another board's variant does not inherit the claim.**
So for a row in `tools/board_manifest.py`, `recipe_for` refuses with
`UnknownBoard` naming the row's own variant, and `catalogue()` gives the
board no `firmware_evidence` and says why in `firmware_withheld`, while
`FIRMWARE_VERIFIED` stays keyed by chip. OH-179 is where such a row gets a
recipe of its own; the two refusals change with it, and not before.
`test_no_row_inherits_its_chips_evidence` in
`tests/rules/test_board_manifest.py` holds the second, which §7 keeps; §7
replaced the first, and the test that held it went with it.
`test_the_c6_recipes_variant_numbers_the_pilots_sda_and_scl_as_other_gpios`,
beside it, holds the `SDA` and `SCL` sentence.

## 7. 2026-09-29 — a manifest board holds its own evidence, or none

OH-179 replaced §6's two refusals. A row in `tools/board_manifest.py` is
in one of three states. It builds with its chip's recipe and its own
variant as the only pin table (`own_variant` in `webui/compile.py`); or
`recipe_for` refuses, naming what that table needs and this build lacks
(`unmet`, which `test_each_rows_verdict_is_the_compilers_own` holds to the
compiler); or its variant directory was never fetched, and `recipe_for`
resolves while the build is refused naming the fetch, as a XIAO's is
(OH-183). It still never inherits its chip's `FIRMWARE_VERIFIED` entry.

**A row's claim is its own.** `BOARD_FIRMWARE_VERIFIED`, beside
`FIRMWARE_VERIFIED` in `webui/boards/catalogue.py`, maps a row to a named
test that compiles a sketch for that board against its own variant, loads
the image, steps it, and watches a GPIO the variant names move on a pad the
board file maps. `FIRMWARE_VERIFIED` keeps its meaning for every board that
is not a row. `tools/check_board_claims.py` holds a board's entry to checks
4 and 5 as it holds a chip's, and to loading its board: the board's name is
the first argument, or `board_name=`, of a call to something named
`load_firmware` in the named test -- spelled out, or as a name bound by
exactly one plain `NAME = "..."` directly in the module's body that no
function, class body, lambda or comprehension enclosing the call binds.
Any other binding -- a local, a parameter or its default, a `global`
rebinding in `setup_module` or anywhere, tuple unpacking, an annotated
assignment, an assignment under `if` or `for`, an `import ... as`, or a
`from ... import *` anywhere in the module, read as binding every name --
leaves the name unresolved, and the entry fails. Only the file's text is
read. A name rebound as the test runs -- `globals()[...] =`, `setattr` on
the module, a monkeypatch of it from an autouse fixture or any other -- is
not detected, and nor is a wrapper called `load_firmware` or a monkeypatch
of the real one. A chip's test loads and steps an image too, and what makes a test
one board's is that it runs that board; the name in a variable nothing
loads does not (OH-183).
`test_only_the_manifest_board_its_own_image_ran_on_holds_its_own_evidence`
pins the set, as §3 pins the chips.

On the day: the Adafruit Feather ESP32-C6 held one,
`tests/webui/test_feather_esp32c6_board.py`, which watches the GPIO its own
variant calls `SDA` and the XIAO's does not. The SparkFun Thing Plus
ESP32-C6 and the Adafruit QT Py ESP32-C3 held none: their tables were
refused, the first for a `SOC_GPIO_PIN_COUNT` nothing here defined, the
second also for a `soc/soc_caps.h` on none of its include directories. §9
is how they came to hold their own.

## 8. 2026-09-29 — a row's name as the manifest spells it, beside a run-claim, is the row's claim

Check 1 matched chips only, and a row carries its chip in its name, so "The
SparkFun Thing Plus ESP32-C6 runs firmware." passed on the ESP32-C6's
`FIRMWARE_VERIFIED` entry: §7's refusal, undone by a sentence (OH-183).

`unevidenced_chip_claims` now reads each row's `board=` out of
`tools/board_manifest.py`, without importing it, and matches those names
first: as the manifest spells them, case-insensitively, with any run of
whitespace, `&nbsp;` or `<br>` between two words, in the claim line joined
to the rest of its sentence on the lines above. That reaches back to a
`.`, `!` or `?` before a space or a line's end, never past a blank line
or a table row, and over no more lines than the longest row's name has
words. So a name hard-wrapped across lines, as §7 wraps the pilot's, is
read, and a name in the sentence before an unrelated claim is not. A row
so named needs its own `BOARD_FIRMWARE_VERIFIED` entry, and its name is
taken out before chips are matched. A manifest that is not there, or a
row with no literal `board=`, is an error rather than a pass.
`test_the_pilot_beside_a_run_claim_fails_and_the_feather_passes` and
`test_the_pilot_hard_wrapped_across_two_lines_is_still_the_pilot` in
`tests/rules/test_board_claims.py` hold it against this repository's own
register and manifest, the pilot's own entry (§9) taken out;
`test_a_row_named_anywhere_in_the_claims_sentence_above_it_is_read` and
`test_a_row_named_above_an_unrelated_claim_is_not_that_claim` hold the
reach both ways.

**Only that spelling is read.** A paraphrase -- "Thing Plus ESP32-C6",
"SparkFun Thing Plus - ESP32-C6", "QT Py ESP32-C3" -- is not the row, and
is matched only as the chip it names, which passes wherever that chip holds
evidence. `test_a_paraphrase_of_a_rows_name_is_read_only_as_its_chip` holds
that limit where it is.

## 9. 2026-09-30 — the SparkFun Thing Plus ESP32-C6 and the QT Py ESP32-C3 hold their own

What refused their tables (§7) was ESP-IDF's capability header, which this
build does not have. So the ESP32-C6 and ESP32-C3 variant directories under
`webui/arduino/` carry a `soc/soc_caps.h`, as the C5's now does for its
`oh_board.h`, each defining exactly the `SOC_` names that chip's build
uses, each value read from ESP-IDF v5.5 and cited by file and line;
`tests/webui/test_soc_caps.py` holds the values to the reference, the
citations to their lines, and the names to the build (OH-185).

`LED_BUILTIN` on both boards is `SOC_GPIO_PIN_COUNT` plus the RGB LED's
pin: no pad's `chip_index`, and no GPIO. A stock Blink is refused for it
with a hint saying it is an RGB LED this model does not drive
(`test_a_pin_the_compiler_knows_is_past_the_count_stops_the_build_and_says_why`
in `tests/webui/test_compile.py`), so the pin watched is `SDA`.

Each board then holds an entry of the Feather's shape:
`tests/webui/test_sparkfun_esp32c6_board.py` and
`tests/webui/test_qtpy_esp32c3_board.py` each compile an `SDA` blink for
their board by name against its own variant, rebuild the image beside
them byte for byte, run it, and watch the GPIO that variant calls `SDA`
move through the pad whose label names `SDA`, its `chip_index` read from
the board file, and never the GPIO the XIAO's `SDA` names.
`test_only_the_manifest_board_its_own_image_ran_on_holds_its_own_evidence`
pins the three.

## 10. 2026-09-30 — a row that builds holds its own by a test of that shape

The pin watched need not be `SDA`. It has to be one the board's own
variant names, on a header pad, at a GPIO other than the one the XIAO's
variant gives the same name, and other than a sibling row's on the same
chip, so that a build against the wrong table moves another pad or none
and the image is this board's alone. The pad is found by its `chip_index`
and must also carry that GPIO in the vendor's own net name.

The SparkFun Pro Micro ESP32-C3 (OH-188) shares `SDA`, GPIO5, with the QT
Py, whose `SDA` image is the same bytes, so
`tests/webui/test_sparkfun_pro_micro_esp32c3_board.py` watches `MOSI`:
GPIO3 on its `IOA3/PICO` pad, while the QT Py's `MOSI` and the XIAO's are
two other pads here, never enabled or driven and read `input` throughout.
The SparkFun Qwiic Pocket ESP32-C6's `SDA` reaches no header pad and its
`TX` is the XIAO's, so
`tests/webui/test_sparkfun_qwiic_pocket_esp32c6_board.py` watches `MOSI`
too: its `IO3` pad moves and the XIAO's, `IO18`, reads `input`
throughout. Each test asserts its reasons for not watching `SDA` or `TX`,
so it fails if one stops being true.
`test_only_the_manifest_board_its_own_image_ran_on_holds_its_own_evidence`
pins every entry.

## 11. 2026-09-30 — an RP2040 row holds its own by the chip's blink, built against its variant

§7's shape has no road to an RP2040 row. `webui/compile.py`'s `RECIPES`
has no RP2040 recipe, and a sketch built by arduino-pico calls into the
RP2040 boot ROM, which this repository does not ship
(`tests/cortexm0/test_blink.py` says where it stops). The chip's own
evidence is a bare-metal blink for that reason, and a row can claim no more
than its chip has shown. So a row on the RP2040 holds its own entry by the
chip's blink made that board's, and nothing weaker:

- **The image names its pin through the board's own variant.**
  `tests/webui/rp2040_rows/blink.c` toggles a name given with `-D` and
  includes one board header, the `pins_arduino.h` of the board's own
  arduino-pico variant, found through `-I` on that variant. The name may be
  declared there or in the `variants/generic/common.h` that file includes
  -- `MISO` is common.h's, set to the variant's `PIN_SPI0_MISO` -- and
  either way the number is the variant's. Nothing in the source or its
  build numbers a GPIO, so the same source built against another board's
  table toggles that board's pin. It is built by the chip blink's
  `arm-none-eabi-gcc`, with its flags and its linker script, committed
  beside the test, and rebuilt byte for byte wherever that toolchain is.
- **It selects SIO on the pad first, as silicon requires.** An RP2040's
  processors drive a GPIO only where its `FUNCSEL` selects SIO (RP2040
  Datasheet 3184e62, Table 280), and `FUNCSEL` resets to NULL (Table 285).
  `webui/boards/rp2040.py` maps each GPIO's `CTRL` register in IO_BANK0,
  and `api.row_levels` gives a row's pad SIO's level only where its
  `FUNCSEL` selects SIO: `input` where it is NULL, `unknown` where it is a
  peripheral nothing here models. So an image that never selects SIO, as
  the chip's own blink does not, moves no row's pad.
- **The GPIO watched is read, not typed**, by OH-181's reader, with the
  flags the board's own build is given. For these variants that reading is
  the preprocessor's: by hand the reader refuses a header that
  `#include`s, as both boards' do, so where no `arm-none-eabi-g++` is
  installed -- CI among them -- every test in both files skips, and check 5
  is all that holds these entries there. The image is compiled without
  those flags, so two readings of one variant have to agree for the tests
  to pass: the compiler's, in the image, and the reader's, in the test. A
  name whose value turned on one of those flags would disagree, and fail.
- **The board is loaded by name** through `api.load_firmware`, stepped on
  the Cortex-M0+ core, and watched through the pin view at the pad whose
  `chip_index` is that GPIO. For that, `webui/boards/rp2040.py` names SIO's
  output-enable and output words as the `GPIO_ENABLE` and `GPIO_OUT`
  `api.row_levels` reads; until then an RP2040 row's pads read no level at
  all.
- **The vendor names the GPIO too** (§10). Where a net is named for the
  function rather than the GPIO, as Adafruit's `MISO` is, the vendor's own
  statement is its schematic's name for the chip's pin on that net.
- **The siblings are every other RP2040 row in `tools/board_manifest.py`,
  the XIAO RP2040s' variant, and arduino-pico's own default table** -- the
  variant whose `common.h` the board's own includes, as the reader reports
  having read it -- each read the same way. The default is there so that a
  pin a variant leaves at arduino-pico's default is never the one watched:
  a row pointing at the Pico's table would pass on it. The watched name
  must number another GPIO in each, those pads read `input` throughout,
  and the same source built against each sibling's variant, run on this
  board, must drive that sibling's pin and leave this board's pad `input`.
  That last is §10's condition run rather than argued, wherever the
  toolchain is.

`tests/webui/test_kb2040_board.py` watches the Adafruit KB2040's `MISO`;
its `MOSI` is the default table's. `tests/webui/test_glyph_mini_rp2040_board.py`
watches the PCBCUPID Glyph Mini RP2040's `PIN_WIRE0_SDA`: the pin its `SDA`
names, under the spelling every sibling's table numbers, because the XIAO
RP2040's `SDA` is a macro naming another macro, which the reader refuses to
number. Each test asserts why it watches what it does, so it fails if a
reason stops being true.
`test_only_the_manifest_board_its_own_image_ran_on_holds_its_own_evidence`
pins both entries with the rest.

**What this is not.** It is not a page build: an RP2040 row gets a compile
recipe from OH-161's compile service or not at all, and nothing here adds
one. It is not a sketch, whose path still stops at the boot ROM. And it
does not close `FUNCSEL` for the XIAO RP2040s: `rp2040.pin_states`, which
their levels are read through, does not ask it, and the chip's own blink
never selects SIO, so a XIAO's pad reads SIO's level whatever `FUNCSEL`
holds. That is left open, on the chip's evidence rather than these rows'.

## 12. 2026-09-30 — check 5 finds the image at the path the test builds

Check 5 found a named image by its name anywhere under the test's
directory, so the KB2040's entry passed with its image deleted: the test
spelled `blink.bin` for a temporary build output, and another test's
`blink.bin` sat under `tests/webui/` (OH-196's review). An image now counts
only where the named test joins its name onto its own location --
`pathlib.Path(__file__)`, `.resolve()`, `.parent`, `.parents[n]` and `/`
with a string, directly or through names one plain module-level assignment
binds -- and that path is a file under the test's own directory. Every
entry names its image that way already. `tests/rules/test_board_claims.py`
holds the case the review found, a name joined onto a temporary directory,
and a path climbing out of the test's directory.
## 13. 2026-09-30 — a row may watch `LED_BUILTIN` where no sibling numbers it alike

§10's conditions do not name a label, and the PCBCUPID Glyph C3 (OH-194)
meets them on `LED_BUILTIN`, on the header pads its board file puts on
PCBCUPID's `/GPIO_1`. Every other table on the ESP32-C3 numbers
`LED_BUILTIN` another GPIO, or no pin at all -- it defines none, or defines
it as something other than an integer, as an RGB LED past the chip's GPIO
count is -- and then a build against it is refused and moves nothing.
`tests/webui/test_pcbcupid_glyph_c3_board.py` reads each table for it, and
asserts why not `SDA`: its net, `/SDA`, carries no GPIO.
