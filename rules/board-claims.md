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
assignment, an assignment under `if` or `for`, an `import ... as` -- leaves
the name unresolved, and the entry fails. Only the call's name is read: a
wrapper called `load_firmware`, or a monkeypatch of the real one, is not
detected. A chip's test loads and steps an image too, and what makes a test
one board's is that it runs that board; the name in a variable nothing
loads does not (OH-183).
`test_only_the_manifest_board_its_own_image_ran_on_holds_its_own_evidence`
pins the set, as §3 pins the chips.

On the day: the Adafruit Feather ESP32-C6 holds one,
`tests/webui/test_feather_esp32c6_board.py`, which watches the GPIO its own
variant calls `SDA` and the XIAO's does not. The SparkFun Thing Plus
ESP32-C6 and the Adafruit QT Py ESP32-C3 hold none: their tables are refused,
the first for a `SOC_GPIO_PIN_COUNT` nothing here defines, the second for a
`soc/soc_caps.h` on none of its include directories, as
`tests/webui/test_compile.py` asserts.

## 8. 2026-09-29 — a row's name as the manifest spells it, beside a run-claim, is the row's claim

Check 1 matched chips only, and a row carries its chip in its name, so "The
SparkFun Thing Plus ESP32-C6 runs firmware." passed on the ESP32-C6's
`FIRMWARE_VERIFIED` entry: §7's refusal, undone by a sentence (OH-183).

`unevidenced_chip_claims` now reads each row's `board=` out of
`tools/board_manifest.py`, without importing it, and matches those names
first, in the claim line joined to the line above it: as the manifest
spells them, case-insensitively, with any run of whitespace or `&nbsp;`
between two words, so a name hard-wrapped across the two lines, as §7
wraps the pilot's, is read. A row so named needs its own
`BOARD_FIRMWARE_VERIFIED` entry, and its name is taken out before chips
are matched. A manifest that is not there, or a row with no literal
`board=`, is an error rather than a pass.
`test_the_pilot_beside_a_run_claim_fails_and_the_feather_passes` and
`test_the_pilot_hard_wrapped_across_two_lines_is_still_the_pilot` in
`tests/rules/test_board_claims.py` hold it against this repository's own
register and manifest.

**Only that spelling is read.** A paraphrase -- "Thing Plus ESP32-C6",
"SparkFun Thing Plus - ESP32-C6", "QT Py ESP32-C3" -- is not the row, and
is matched only as the chip it names, which passes wherever that chip holds
evidence. `test_a_paraphrase_of_a_rows_name_is_read_only_as_its_chip` holds
that limit where it is.
