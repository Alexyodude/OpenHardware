# Handoff — the IDE, and nine tickets closed in series

| | |
|---|---|
| **Date** | 2026-08-26, later than `HANDOFF_2026-08-26_the-avr-oracle-and-an-ide-that-cannot-exist-yet.md`. Where they disagree, **this one wins** |
| **Repo** | `Alexyodude/OpenHardware` — not a fork, MIT |
| **Branch / HEAD** | `master` @ `706d162` |
| **Working tree** | **Clean.** Nothing uncommitted, nothing stashed |
| **This session** | 27 commits from `7566355`. Ran `/oh-my-claudecode:ralph` with "complete all tickets in series" |
| **Cores built** | `build/lib/`: `avr.dll` 116,736 · `cortexm0.dll` 222,208 · `i8086.dll` 130,048 · `riscv32.dll` 146,432 |
| **Gate** | **1,446 passed, 17 skipped**; all eight checkers exit 0 |
| **Boards** | 26 imported, **12 runnable, 10 firmware-verified** — unchanged, and §3.5 says why |
| **ABI versions moved** | avr 1 → **3**, i8086 7 → **8** |

**The second session is still quiet.** No commits but mine. Still stage by
explicit path — §9.

**There is now an IDE.** Open the page, pick Arduino Uno, type a sketch, press
Build and run, watch PB5 move. It works on **one** board of twenty-six, and
OH-66 is the ticket for the second.

---

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| `Serial.print` reaches the console pane | **ACHIEVED** | `b'hello\r\n'` via `api.uart_view`; `tests/avr/test_arduino_sketch.py`; `54e5469` |
| A compile service: source in, image out | **ACHIEVED** | `webui/compile.py`, 15 tests; `f287d49` |
| An editor in the browser | **ACHIEVED** | `webui/static/emulator.html` `#sketch`; verified in a real browser; `9169bbd` |
| Reach a build somebody already made | **ACHIEVED** | `--artefacts DIR`, 14 tests; `ceb8acc` |
| CI runs the documented command | **ACHIEVED** | `.github/workflows/rules.yml` runs bare `pytest`; `19b1b90` |
| Armv6-M corpus has a real floor | **ACHIEVED** | 27 × 500; `3a50a85` |
| i8086 single-step trap | **ACHIEVED** | `core/i8086/timing.h` sibling `interrupt.*`; 10 tests; `11d3135` |
| `import_kicad_board.py` retired | **ACHIEVED** | deleted in `cc36072` |
| The STM32C5 identified | **ACHIEVED** | Cortex-M33; `1be6998` |
| The IDE on a second board | **NOT STARTED** | OH-66 — §6.1, the top open item |
| A 3D board view | **BLOCKED ON SOURCE MATERIAL** | no board here has a mesh; §3.6 |
| i8086 cycle *counts* (3 × F2 cells) | **BLOCKED ON AN HONEST SOURCE** | the bound landed; §3.7 |
| IMUL/DIV undefined flags | **BLOCKED ON RESEARCH** | five hypotheses refuted; §3.8 |
| 8 → 9 Cortex-M33 boards | **BLOCKED ON ORACLE** | OH-36, held by `agent-oh36` |
| 3 ESP32-S3 boards | **REFUSED ON EVIDENCE** | OH-38, unchanged |
| 2 nRF52840 boards | **BLOCKED ON ORACLE** | OH-64, unchanged |

### The fourteen boards that do not run, now three reasons not four

```
cortexm33  9  MG24 x2, RP2350 x2, nRF54LM20A x2, nRF54l15 x2, STM32C5 x1   OH-36
xtensa     3  ESP32-S3 x3                                                  OH-38
cortexm4   2  nRF52840 x2                                                  OH-64
```

`unknown` is gone as a category. See §3.5.

---

## 2. What changed, in one paragraph each

**The IDE exists.** Three tickets — a compile service, an editor, and the
USART that makes `Serial` worth having. A request carries source and a board
name and cannot influence the command line.

**A ticket's central prediction was wrong, and measurement caught it.** OH-63
said `Serial` would need a second interrupt source. It does not. §3.1.

**A browser found a bug fifteen tests missed.** §3.4.

**`tests/avr` had never been in the gate.** Not one test of the AVR core had
ever run under the command `CLAUDE.md` tells people to use. §3.3.

**Two tickets turned out to be already done**, their notes stale — OH-17 and
half of OH-5. What was actually missing in each was smaller and sharper than
the ticket described, and in OH-17's case the existing floor was worse than no
floor. §3.2.

---

## 3. Root-cause narratives

### 3.1 The fast path, and a prediction that measurement refuted

**Symptom.** A `Serial.println` sketch ran 600,000 instructions and printed
nothing. `UCSR0B` read `0xB8`.

**The hypothesis the ticket wrote down, in its own words:** *"HardwareSerial is
interrupt-driven, not a busy-wait… assume the interrupt is required and
check."* It named splitting `core/avr`'s `Timer` into a general
`InterruptSource` list as the expected shape.

**How it was ruled out.** By reading `HardwareSerial::write` rather than
reasoning about it. It has two paths:

```c
if (_tx_buffer_head == _tx_buffer_tail && bit_is_set(*_ucsra, UDRE0)) {
  *_udr = c;          // straight out, no interrupt involved
  return 1;
}
```

`0xB8` decodes as `UDRIE0` **set** — the byte had gone into the ring buffer and
was waiting for `USART_UDRE`, which this core does not raise.

**Root cause.** `UDRE0` read clear, because `UCSR0A` was an ordinary byte of
memory. Making it read `UDRE0 | TXC0` regardless of what was written puts every
write on the fast path. Measured after: `UCSR0B` = `0x98`, `UDRIE0` **clear**,
`uart0_output` = `b'hello\r\n'`.

**Why the status register is not a constant.** `Serial.begin` writes `U2X0` and
`board.baud_rate` reads it back to know whether the divisor is over 8 or over
16. A constant loses it and is wrong by exactly a factor of two at every speed —
and still looks plausible.

**Generalization.** *A ticket's stated hypothesis is a lead, not a finding.*
This one would have produced a general interrupt table with no caller, which
rule 6 forbids — justified entirely by a prediction nobody had checked. The
ticket said "check"; checking took ten minutes and removed a day of work.

### 3.2 A floor computed from the data is not a floor

**Symptom.** None. OH-17's notes said the work had not started; the conformance
run had in fact existed since OH-39 and passed.

**What was actually missing**, and it was worse than absent:

```python
assert total >= len(FAMILIES), "corpus is suspiciously small"
```

`len(FAMILIES)` is 27. `--count` is a command-line argument, so a corpus
regenerated with `--count 1` is twenty-seven cases and **passes** — every
divergence explained, nothing wrong, and the core checked against a 399th of
what it had been.

**Fix.** `EXPECTED_CASES = len(FAMILIES) * 500`, verified red by raising
`CASES_PER_FAMILY` to 501.

**Generalization.** *A bound derived from the thing it constrains is not a
bound.* It moves with whatever it is meant to hold still. The same shape
appears in `tests/i8086/test_timing.py` and was avoided there on purpose: the
`4 × length` floor comes from the 8088's bus width, not from the corpus.

### 3.3 A whole suite outside the gate

**Symptom.** Adding 13 tests to `tests/avr/` left `pytest -q` reporting the
same 1,301 as before.

**Root cause.** `tests/avr` was absent from `pyproject.toml`'s `testpaths`.
Bare `pytest` collected 1,318 tests and the AVR suite's 35 were not among them
— so the core `webui/boards/catalogue.py` claims runs firmware on an Arduino
Uno had **never** been exercised by the documented gate. It passed because
somebody ran `pytest tests/avr/` by hand.

`test_ast_count_matches_pytest_collection` does not catch it and is not meant
to: it compares the ast model against pytest for `tests/rules/` alone, so a
whole directory can leave the configuration without moving either number.

**Fix.** Add it, plus `tests/rules/test_testpaths.py`, which finds suites by
walking `tests/` rather than from a second list, and checks both directions.
Then `19b1b90`: CI ran three directories by name, so four of the five cores
were in neither CI nor its reach. It runs bare `pytest` now, and
`test_ci_runs_every_suite_in_testpaths` keeps the two from drifting.

**Generalization.** *A suite nobody runs looks exactly like a suite that
passes.* Every other kind of failure announces itself.

### 3.4 A pane can be wrong in a way only a reader sees

**Symptom.** Fifteen tests green. In a browser:

```
sketch.cpp:2:16:
      int broken = ;
                   ^ error: expected primary-expression before ';' token
```

**Root cause.** `renderDiagnostics` appended the quoted source line straight
after the location anchor, splitting the diagnostic in half — the caret above
the sentence explaining it.

**Fix.** Emit the rest of the message line first, then the quote.
`test_a_diagnostic_message_is_rendered_before_the_line_it_quotes` checks it by
position in the source, because Python cannot render the pane.

**Generalization.** This repository has now recorded this twice — the first was
`renderMemory` returning the same byte for every offset and surviving all 371
tests. **Drive a UI change in a real browser before closing it.** Kill
listeners first and count them; `pkill -f` does not work in Git Bash here.

### 3.5 The part existed; the search had not found it

**Symptom.** `webui/boards/catalogue.py` read `"unknown -- part not confirmed
to exist"` for the STM32C5.

**That was not wrong.** It was an honest report of a *search* — nobody could
place "STM32C5" among ST's families, so the catalogue refused to guess a core.
Correct on 2026-08-24.

**Root cause.** ST announced the STM32C5 in **March 2026**, after that entry was
written. A Cortex-M33 part, sold as low-cost with more performance than the
Cortex-M0+ STM32C0.

**The corroboration that carries the weight is not the wiki.** Seeed's own
KiCad library ships `XIAO-STM32C5-SMD.kicad_mod` in a commit dated 2026-07-15 —
four months after the announcement, from the vendor who would build the board.
A vendor does not draw a footprint for a part that does not exist.

**What local evidence could not do, and the ticket proposed all three.** The
`.kicad_mod` is the **module's** footprint, not the die's, so its 35 pads and
2.54 mm pitch describe the XIAO form factor and say nothing about the MCU —
that line of enquiry cannot work in principle. The symbol carries no MPN, no
datasheet, no description. The clone is shallow, so there is no history.

**Not reached:** `st.com`. Two `WebFetch` attempts timed out; recorded in the
catalogue comment so the next reader knows which source is missing rather than
assuming it was checked.

**Generalization.** *"Not confirmed to exist" is a statement about a search and
decays.* Re-run the search before building on it.

### 3.6 A view with nothing to draw

**Symptom.** OH-30 wants "one board renders" with selection shared between the
2D and 3D views.

**Root cause, measured.** Seeed publishes **37 `.kicad_mod` and zero
`.kicad_pcb`**. `tools/import_3d.py` — which OH-29 shipped — reads a
`.kicad_pcb` Edge.Cuts outline. It has nothing to read for any XIAO. No `.gltf`
or `.glb` exists outside `third_party/`. OH-29's own note already said it:
*"none of the 26 boards currently in this repository has a 3D model."*

**And the 2D half is also absent** — `emulator.html` has no pad map at all, so
"shared selection" needs both views built, and the ticket claims neither
`emulator.html` nor `emulator.js`.

**What already exists and is not this.** `webui/static/scene3d.js` draws a 3D
view today, and `app.js` has a working 2D/3D toggle — but that is the PICSimLab
**bridge** page, and `models3d.js`'s `hasModel()` answers about *peripherals on
a workbench*, not boards.

**Not attempted, deliberately:** a generic extruded rectangle for boards with
no model. The ticket forbids it in its own words.

### 3.7 A bound you can check, and a count you cannot

**The problem.** All three F2 cells need a per-opcode execution cost, and there
is nowhere honest to get one. Fitting a table to the corpus and then testing it
against the same corpus proves a table was fitted.

**What is different about the bound.** `cycles >= 4 × (length − queued)` falls
out of two architectural facts — the 8088 has an **eight-bit** external bus and
a **four-byte** prefetch queue — and neither number was read off the data.

**Measured over the whole corpus:** 2,857,000 cases, **zero violations,
521,944 tight**. The second number is what makes the first mean anything.

**A test lesson.** The first version read the **first** 24 opcode files and
never saw a 6-byte instruction, because the long encodings live further up the
opcode space. *A prefix of the opcode space is not a sample of it.* It reads
every 13th file now, and `test_the_sample_covers_every_length_and_both_queue_states`
asserts the sample's adequacy rather than leaving it to a comment.

**Also pinned, and it limits what OH-8 can ever prove here:** the corpus only
starts with a queue that is **empty or full**, never one, two or three bytes.
So it adjudicates the two extremes of the fetch cost and says nothing about the
middle — where a real prefetch model spends most of its time.

### 3.8 Five hypotheses refuted, and where the 33 cases were hiding

**Not solved.** No code changed and no floor lowered. What was established:

**The harness is validated** — MUL r/m8 is 100% on AH for SF, ZF and PF, and
IMUL's figures reproduce the ticket's exactly (98.1 / 96.1 / 70.1).

**The obvious hypothesis is dead.** IMUL differs from MUL only by the
conditional negate, so the flags should come from before it. Splitting by
operand signs gives PF **71.2 / 69.8 / 69.5%** — identical within noise.

**One real sub-rule.** Every PF mismatch has CF and OF set. With CF **clear**,
`parity(AH) == PF` in **67 of 67**.

**The flags are not preserved** — SF/ZF/PF/AF match the *incoming* flags at
49–52%, i.e. chance.

**The 33 IDIV cases are located, and where they are is the finding.** A strict
two-byte register-form filter finds 265 non-trapping cases and **zero**
disagreements. The 33 appear only once **prefixed** encodings are included —
they are 3- and 4-byte forms. So an attempt that filters prefixes away will
conclude, wrongly, that IDIV is already correct.

**Twelve bit-level predicates tested, none separating.** Best 0.288 on n=33,
which is noise.

---

## 4. Reproduce the result, cold

```bash
cd Code/Github/OpenHardware
git log --oneline -1                      # -> 706d162

python tools/build_core.py
#  -> avr 116736 · cortexm0 222208 · i8086 130048 · riscv32 146432

python -m pytest -q                       # -> 1446 passed, 17 skipped (~5 min)
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_ticket_claims check_board_claims; do
  python -m tools.$c; done                # -> all exit 0

python -c "from webui.boards import catalogue; c=catalogue.catalogue(); \
print(len(c),'boards |',sum(1 for b in c if b.runnable),'runnable |', \
sum(1 for b in c if b.firmware_verified),'firmware-verified')"
#  -> 26 boards | 12 runnable | 10 firmware-verified
```

### Driving the IDE

**Kill every listener first** — §9.

```bash
netstat -ano | grep ":8088" | grep LISTENING | awk '{print $5}' | sort -u \
  | while read pid; do taskkill //PID $pid //F; done
netstat -ano | grep ":8088" | grep -c LISTENING     # -> 0
python webui/emulator_server.py
```

Pick **Arduino Uno**, scroll to *Write a sketch*, press **Build and run**.
Expect `1946 bytes on Arduino Uno, entered at 0x00000000. Press Run.` Replace
the body with `int broken = ;` and press it again: *"Did not compile. The board
is unchanged."*, the location red and clickable, the source quoted with a caret.

To offer builds made elsewhere:

```bash
python webui/emulator_server.py --artefacts ~/projects
```

### The optional reference trees

All optional; the tests **skip** without them and never pass quietly.

```bash
npm install --prefix third_party/avr8js avr8js@0.21.0 && node tools/gen_avr_corpus.mjs
tools/get_armv6m_tests.sh                 # needs ../rp2040js built
bash tools/get_8088_tests.sh --opcodes 00 01 88 89
```

---

## 5. File inventory

### New this session

| File | Bytes | What |
|---|---|---|
| `webui/compile.py` | 16,070 | source + board name → image. The safety boundary is the whole design |
| `core/i8086/interrupt.h` / `.cc` | 2,141 / 1,671 | `RaiseInterrupt`, lifted out of `exec_core.cc` |
| `core/i8086/timing.h` / `.cc` | 2,951 / 480 | the bus-cycle floor, and why it is a bound |
| `tools/get_armv6m_tests.sh` | 2,252 | one command for the Armv6-M corpus |
| `tests/webui/test_compile.py` | 8,649 | 15 tests; the safety shape asserted structurally |
| `tests/webui/test_editor.py` | 10,737 | 15 tests; the route driven for real |
| `tests/webui/test_artefacts.py` | 9,286 | 14 tests; the prefix mistake has its own |
| `tests/avr/test_usart.py` | 7,802 | 14 tests; the fast-path measurement in its header |
| `tests/i8086/test_interrupts.py` | 9,876 | 10 tests; the trap, from the manual |
| `tests/i8086/test_timing.py` | 7,985 | 7 tests; the bound over the corpus |
| `tests/rules/test_testpaths.py` | 2,756 | the guard for §3.3 |
| `tests/avr/arduino/serial.cpp` | 1,006 | three lines; the binary is **not** committed |

### Modified

`core/avr/{cpu.h,cpu.cc,exec.cc,abi.*}` (USART, ABI 3), `core/i8086/{exec_core.cc,abi.*,CMakeLists.txt}`
(ABI 8), `webui/emulator_server.py` (two routes, `--artefacts`),
`webui/static/{emulator.html,emulator.js,emulator.css}`, `webui/boards/{atmega328p.py,catalogue.py}`,
`pyproject.toml`, `.github/workflows/rules.yml`, and six test files whose
tripwires fired.

### Deleted

`tools/import_kicad_board.py`. **The 25 board JSONs naming it in `derivation`
are untouched** — that field records how a file was *made*.

---

## 6. Open work, highest priority first

### 6.1 OH-66 — a second board in the compile service — *software-only, START HERE*

`RECIPES` in `webui/compile.py` has **one row**. Twelve boards are runnable and
eleven cannot be built for.

Start by reading `webui/compile.py`'s `RECIPES` and `Recipe`, then the ticket,
which names the four things that will differ from the AVR row so you do not
find them one at a time:

1. **A linker script.** `avr-gcc` knows where flash starts from `-mmcu` alone.
   An Arm board does not, and `Recipe` has no field for one.
2. **A variant that is not installed.** `framework-arduino-samd` ships
   Arduino's own boards; the XIAO-SAMD21 variant is in
   `framework-arduino-seeed-samd`, which is **not** here. Check before
   promising SAMD21.
3. **The base address.** Take it from `webui/boards/samd21.py` or `esp32c3.py`,
   which carry it with citations — not from a constant in the recipe.
4. **An ESP32 build is three images**, not one. `tools/import_firmware.py`
   already models that with its `role` field.

**Done when** a sketch typed into the editor builds and runs on a second board,
watched by a named test that checks the pin the way
`tests/webui/test_compile.py` checks PB5.

### 6.2 OH-8 — the next timing slice — *software-only*

An EU cost table for the register form, taken from **Intel's published timing
table** rather than fitted, verified against the 123 opcodes measured
deterministic. Deriving it from the corpus instead needs a held-out split to
mean anything, and should say so loudly.

### 6.3 OH-11 — three leads, in order — *software-only, research*

(a) The 33 IDIV cases are all **prefixed** encodings — check whether the
discriminator is instruction *length* rather than an arithmetic property, which
would move this from a microcode question to a decode one. (b) Solve per-case
for the byte set consistent with all three flags and look for structure against
|q| and |r|. (c) Ken Shirriff's published 8086 microcode disassembly is the only
source that would settle either half, and this repository has not consulted it.

### 6.4 Blocked, and why — *do not start these*

- **OH-36** — Cortex-M33, now **nine** boards. Blocked on an oracle **and held
  by a live session lock** (`agent-oh36`). Do not steal it.
- **OH-64** — Cortex-M4, 2 boards. Decode is done and swept; execution has no
  oracle. QEMU absent, and a single source cannot adjudicate.
- **OH-38** — Xtensa, 3 boards. Refused on evidence.
- **OH-30** — 3D view. §3.6.
- **OH-9** — PICSimLab adapter.

### 6.5 Residuals

1. **`core.avr.abi.Cpu` after `close()` segfaults** the interpreter instead of
   raising — the handle is `None` and ctypes calls through it. Cost one
   confusing traceback. Two lines, in nobody's ticket.
2. `sh1add`/`bset` accounted in the RISC-V sweep — unchanged.
3. `core/riscv32` has no `map_constant`/`map_stream`/`map_counter` — deliberate.
4. `PYI034` on `__enter__` in all four cores — known, `ruff` is not adopted.
5. The UI does not surface which of a board's ISA the core executes.

---

## 7. Commits this session

```
706d162 chore(tickets): file OH-66, a second board for the compile service
4536266 chore(tickets): OH-11 attempted and not solved, with the search recorded
7463f08 chore(tickets): OH-8's first slice, and the limit the corpus imposes
a5a21ef feat(i8086): the bus-cycle floor, which the oracle can actually check
f65d339 chore(tickets): OH-30 is blocked on source material, measured
ee6d192 chore(tickets): close OH-65
1be6998 fix(boards): the STM32C5 exists, and it is a Cortex-M33
f185d4e chore(tickets): close OH-41
cc36072 chore(tools): retire import_kicad_board.py
f8b537b chore(tickets): close OH-5
11d3135 feat(i8086): the single-step trap, and RaiseInterrupt in a file of its own
7ac9bf5 chore(tickets): close OH-17
f653a6e chore(tickets): close OH-17
3a50a85 test(cortexm0): a floor the corpus cannot quietly fall below
b708803 chore(tickets): narrow OH-64 off the Armv6-M conformance test
5b80c16 chore(tickets): close OH-60
19b1b90 ci: run the whole suite, not three directories of it
148fb80 chore(tickets): close OH-10
ceb8acc feat(webui): reach a build somebody already made
28a5fda chore(tickets): close OH-62
6ff7457 fix(webui): a diagnostic's message goes before the line it quotes
9169bbd feat(webui): the editor -- type a sketch, build it, watch it run
548acbf chore(tickets): close OH-61
f287d49 feat(webui): a compile service, source in and a loadable image out
201884e chore(tickets): close OH-63
54e5469 feat(avr): USART0, and the interrupt it turned out not to need
a8cfe68 feat(avr): ijmp, icall, sbrc and sbrs, which a Serial sketch reaches
```

`f653a6e` and `7ac9bf5` are both "close OH-17" — the first landed with a phrase
eaten by shell backtick substitution and the second repairs it. See §9.

---

## 8. Visual output verification

Checked in a real browser via Playwright, listener count verified as 1 first.
**0 console messages at warning level or above.**

**The sketch panel, error state.** Dark theme. Heading *Write a sketch* with
`POST /api/board/compile` beside it. Two paragraphs of prose stating that the
server chooses the compiler and that `#include <Arduino.h>` is added for you. A
monospace textarea on the sunken background holding the broken sketch. Below
it, a *Build and run* button and the text *"Did not compile. The board is
unchanged."* At the bottom, a pane with a red left border containing three
lines: `sketch.cpp: In function 'void setup()':`, then `sketch.cpp:2:16:` in red
and underlined-dotted (it is clickable and moves the cursor), then the message,
then the quoted source line `int broken = ;` with a caret under the `;`.

**The success path.** `1946 bytes on Arduino Uno, entered at 0x00000000. Press
Run.` in the report line; the board report reads *"Built from the sketch: 1946
bytes of bin on Arduino Uno, a ATmega328P on the avr core."*; the Run button
enabled; the errors pane hidden.

---

## 9. Known limitations and traps

- **Backticks in a Bash heredoc are command-substituted and silently eat
  text.** It cost two ticket notes this session — `f653a6e` had "`total >=
  len(FAMILIES)` is twenty-seven" reduced to " is twenty-seven", and OH-66 lost
  the word `role`. **Use Python for any note or file containing backticks**,
  the same way the earlier handoff says to use Write/Edit for anything with
  `\n` escapes.
- **`tools/tickets.py stop` releases only what the CURRENT pid holds.** Every
  CLI invocation is a new pid, so `start` in one command and `stop` in another
  leaves the lock. Locks live in `.omc/ticket-locks/` (gitignored); this
  session cleared its own by deleting the files.
- **The stale-server trap.** `pkill -f` does not work in Git Bash here. Always
  count listeners before trusting the page.
- **`~` is not the home directory in Git Bash here.** `HOME=/c/SPB_Data`. Use
  `$USERPROFILE`.
- **`WebSearch` is exhausted for this session** (200 of 200). `WebFetch` still
  works; `st.com` timed out twice at 60 s.
- **The `/browse` skill is not available** in this session despite `CLAUDE.md`
  naming it. `WebFetch` is the working path.
- **A ralph run does not get an independent reviewer here.** The skill's step 7
  calls an architect agent; the operating instructions forbid the Agent tool
  unless the user asks. Every ticket was self-verified with a full gate, which
  is not the same thing — say so rather than implying a review happened.
- **avr8js does not refuse**, and `neg` of 0x80 is its second known defect
  after the half-carry — unchanged.
- **Do not add `@pytest.mark.parametrize`.** `tools/inventory.py` counts
  `def test_*` with `ast`. Loop inside one test.
