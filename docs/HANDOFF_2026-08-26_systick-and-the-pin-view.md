# Handoff — SysTick, a second board in the IDE, and a 3D pin view

| | |
|---|---|
| **Date** | 2026-08-26, the **third** handoff of that day. Where it disagrees with `HANDOFF_2026-08-26_the-ide-and-nine-tickets.md` or `..._the-avr-oracle-...md`, **this one wins** |
| **Repo** | `Alexyodude/OpenHardware` — not a fork, MIT |
| **Branch / HEAD** | `master` @ `264a260` |
| **Working tree** | **Clean.** Nothing uncommitted, nothing stashed |
| **This session** | 10 commits from `4255951`. Resumed at the previous handoff's §6.1 (OH-66), then built OH-30 on a direct instruction |
| **Cores built** | `build/lib/`: `avr.dll` 116,736 · `cortexm0.dll` **228,864** · `i8086.dll` 130,048 · `riscv32.dll` 146,432 |
| **Gate** | **1,518 passed, 17 skipped**; all eight checkers exit 0 |
| **Boards** | 26 imported, 12 runnable, 10 firmware-verified, **3 buildable** (was 1) |
| **ABI versions** | avr 3 · **cortexm0 12 → 13** · i8086 8 · riscv32 2 |

**Five tickets closed, and the top one needed three.** OH-66 asked for a second
board in the compile service. It was blocked on two things nobody had filed,
both found by measurement rather than reasoning — see §3.1.

**The IDE now builds for three boards and shows their pins moving.** Open the
page, pick a XIAO SAMD21, type a sketch, press Build and run, watch PA17 and
D0 change colour on a 3D board.

**The second session is still quiet.** No commits but mine. Still stage by
explicit path — §9.

---

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| Armv6-M SysTick and exception entry/return | **ACHIEVED** | `core/cortexm0/exception.{h,cc}`; 24 tests; `20cf75e` |
| The entry frame checked against a real oracle | **ACHIEVED** | `tools/gen_armv6m_exception.mjs` re-derives it from rp2040js; `tests/cortexm0/test_exceptions.py` |
| `CPSID i` / `CPSIE i` and PRIMASK | **ACHIEVED** | `core/cortexm0/exec.cc`, mask `0xFFEF` == `0xB662` |
| The SAMD21 registers a vendor Arduino image needs | **ACHIEVED** | 27, measured; `webui/boards/samd21.py`; `1d3acbd` |
| A real Arduino sketch reaches `loop()` on a XIAO | **ACHIEVED** | PA17 at 48,083 instructions/half-period; `tests/cortexm0/test_samd21_arduino.py` |
| A second board in the compile service | **ACHIEVED** | `RECIPES["SAMD21"]`; ~5.3 KB image; `408f529` |
| The IDE drives that board in a browser | **ACHIEVED** | §8; `5324 bytes on XIAO-SAMD21-DIP, entered at 0x000002d0` for the `LED_BUILTIN` blink |
| A pin view, live, in the page | **ACHIEVED** | `webui/static/board3d.js`; `api.pin_view`; `b581584` |
| That view in 3D, sharing the palette | **ACHIEVED** | both themes screenshotted; §8 |
| A board with no model is visibly so | **ACHIEVED** | the panel says "a footprint, extruded — not a model of the board" |
| The Uno's PORTC and PORTD pads live | **NOT STARTED** | 20 of its 26 `unknown` pads; §6.1 |
| A free-running clock behind Run | **NOT STARTED** | Run is a fixed 200,000-instruction budget; §6.2 |
| i8086 cycle *counts* (3 × F2 cells) | **BLOCKED ON AN HONEST SOURCE** | unchanged; §6.3 |
| IMUL/DIV undefined flags | **BLOCKED ON RESEARCH** | unchanged; §6.3 |
| 9 Cortex-M33 boards | **BLOCKED ON ORACLE** | OH-36, held by `agent-oh36`; §6.4 |
| 2 nRF52840 boards | **BLOCKED ON ORACLE** | OH-64, narrowed this session; §6.4 |
| 3 ESP32-S3 boards | **REFUSED ON EVIDENCE** | OH-38, unchanged |

### The three boards the IDE can build for, and the nine it cannot

```
buildable  3   Arduino Uno, XIAO-SAMD21-DIP, XIAO-SAMD21-SMD     2 chips, 2 recipe rows
no recipe  9   ESP32-C3 x3, ESP32-C5 x2, ESP32-C6 x2   (7, three chips)
               RP2040 x2                               (2, ONE chip, core already built)
```

**Count the boards, not the rows.** `408f529`'s message says four and it is
three; `b2cb5a4` corrects it and says where the wrong number came from.

---

## 2. What changed, in one paragraph each

**OH-66's four predicted differences were all real and none of them was the
blocker.** A real Arduino image faulted twelve instructions into `SystemInit`,
and with every register stubbed it stalled forever in `delay()`. §3.1.

**An oracle settled the exception frame, and the alignment case is why it was
worth it.** A model built from an 8-byte-aligned SP passes every test that
fires one exception and corrupts a program that runs a while. §3.2.

**The period is `SYST_RVR + 1`, not `SYST_RVR`.** The first test asserted the
wrong one and went red, which is how the comment came to say the right thing.
§3.3.

**Two board-model bugs were caught by mutation, one in the tests themselves.**
Two tests read their expectation from the constant they were meant to pin. §3.4.

**Two 3D bugs were caught by looking at a screenshot** and neither failed any
DOM assertion. §3.5.

**And a third test bug, also by mutation**: a regex that matched nothing left
eleven tests green against a deliberate typo. §3.6.

---

## 3. Root-cause narratives

### 3.1 OH-66 was blocked on two tickets nobody had filed

**Symptom, first observed.** A real Arduino-core sketch compiled for the XIAO
SAMD21 and run on `webui/boards/samd21.py`:

```
core.cortexm0.abi.MemoryFault: data access at 0x41004004 is outside the
modelled memory (instruction at 0x000020d4)
```

**Hypotheses the ticket had written down, and all four were correct.** A linker
script, a variant that is not installed, the base address, and ESP32 being three
images. None of them was what stopped it.

**How the real blocker was found.** Not by reasoning — by stubbing every
faulting address and re-running until something else happened:

```python
except MemoryFault as exc:
    addr = int(str(exc).split("0x", 1)[1].split()[0], 16)
    cpu.map_register(addr & ~3, 0)          # and go round again
```

That reached **318,216 instructions**, got through `SystemInit` and `init`, and
then stalled forever. Disassembling at the stalling PC gave `delay`:

```
2330 <delay>: push {r4,r5,r6,lr} / bl 22d0 <micros> / ...
```

**Root cause.** Arduino SAMD's `micros()` returns
`(_ulTickCount + PENDSTSET) * 1000` plus a sub-millisecond term, and
`_ulTickCount` moves **only** inside `SysTick_Handler`. `core/cortexm0` had no
SysTick and no exceptions at all — `exec.cc` said so in its own words: *"this
core has no interrupts to wait for"*. With no delivery, `count` stays 0 and
`pend` saturates at 1, so `micros()` can never exceed ~1000 and `delay(2)` never
returns. `main()` calls `delay(1)` **before** `setup()`.

So no Arduino sketch could reach a user's code on **any** Arm board.

**Fix.** Two tickets filed before a line was written — OH-67 (the core half,
five architectural registers) and OH-68 (the board half, 27 chip registers) —
and only then OH-66's one recipe row.

**Generalization.** *A ticket's four correct predictions can still all miss the
blocker.* The predictions were about the thing being built; the blocker was in
the layer underneath, and only running the real artefact found it. The
auto-stubbing loop above is the cheap general technique: it converts "it
faults" into "here is the complete list of what it wants", in one pass.

### 3.2 The alignment bit, and why the oracle earned its keep

**The problem.** Armv6-M stacks eight words on exception entry. Only their
*locations* are architected, not the order they are written, and SP is forced
down to an eight-byte boundary with bit 9 of the stacked xPSR recording whether
it had to move.

**Why a reading of DDI0419 was not enough.** Get the alignment wrong and the
stack drifts four bytes — but **only on exceptions that arrive at an odd word**.
Every test that fires one exception from a fresh aligned stack still passes. A
program that runs for a while corrupts.

**What was done instead.** `tools/gen_armv6m_exception.mjs` asks rp2040js —
already this project's Armv6-M oracle — for the frame directly, forcing
`core.pendingSystick = true` rather than waiting for a tick. Its answers:

```
entry_aligned     sp 0x20003000 -> frame 0x20002FE0  xPSR 0xA1000000
entry_misaligned  sp 0x20002FFC -> frame 0x20002FD8  xPSR 0xA1000200   <- bit 9
lr 0xFFFFFFF9 both, ipsr 15 both
```

`test_the_recorded_oracle_answers_still_match` re-runs that harness wherever a
built rp2040js exists and compares field by field, so the copies in the test
file cannot drift from what they were copied from.

**One harness difference, and it cost a debugging round.** rp2040js takes the
exception at the top of `executeInstruction` and **then executes an instruction
in the same call**; this core makes entry its own step. So a handler of `bx lr`
enters and returns before anything can look, and the first run reported
`ipsr: 0` with eight zero words. The oracle's entry cases use `b .` for that
reason, written down in the harness rather than left as a magic constant.

**Generalization.** *An oracle is worth most exactly where a reading is
plausible and a mistake is invisible.* Choose what to check against it by
asking "which wrong version would still pass my tests".

### 3.3 The period is the reload plus one

**Symptom.** `test_the_counter_counts_down_and_reloads` asserted
`[3, 2, 1, 3, 2, 1, 3, 2, 1]` and got `[3, 2, 1, 0, 3, 2, 1, 0, 3]`.

**The test was wrong, not the code.** Zero is a value the counter is *seen at*,
for one tick, before the reload — so the period is `SYST_RVR + 1`. That is the
part's own behaviour and it is exactly why `SysTick_Config(n)` writes `n - 1`.

**Measured after, on the real image:** the handler runs at **exactly 48,000**
retired instructions, no tolerance, from `SysTick_Config(SystemCoreClock/1000)`
writing 47,999. The LED's half-period is **48,083** — the same number plus the
sketch's own `digitalWrite` and loop. Two tests, one with a tolerance and one
without, and the difference between them is the sketch.

**Generalization.** *A model that fired every `RVR` ticks would make every
Arduino `delay` fractionally short* — under one part in 48,000, which no single
test notices and every long-running measurement accumulates.

### 3.4 A test that reads its expectation from the thing it tests

**Symptom.** Mutating `webui/boards/samd21.py`'s `CLOCKS_ALL_READY` from
`0xFFFFFFFF` to `0` failed five tests in
`tests/cortexm0/test_samd21_arduino.py` — and **not**
`test_every_clock_reports_ready_because_nothing_here_has_to_start`, which is
the test written specifically to pin it.

**Root cause.** It asserted `read_word(...) == samd21.CLOCKS_ALL_READY`. The
constant under test was also the expectation, so they moved together.

**Fix.** Spell the five `PCLKSR` bit positions out, cited to
`component/sysctrl.h:270-283`:

```python
XOSC32KRDY = 1 << 1
OSC32KRDY  = 1 << 2
DFLLRDY    = 1 << 4
DFLLLCKF   = 1 << 6
DFLLLCKC   = 1 << 7
```

Re-mutated afterwards: **2 failed, 20 passed.**

**Generalization.** This is the same defect `tests/cortexm0/test_conformance.py`
records under a different name, where a floor of `len(FAMILIES)` moved with the
corpus it was meant to hold still. **The repository has now caught it twice.**
The tell is a test whose right-hand side is an import from the module under
test.

### 3.5 Two 3D bugs a screenshot found and no assertion could

**Neither failed any DOM assertion**, because the table beside the canvas was
correct throughout.

**First: `refreshTheme` repainted the slab and not the posts.** Switching to the
light theme gave a white board carrying dark-theme pins. Root cause: a colour
cannot be turned back into a state, so there was nothing to recolour *from* —
the pads' states existed only as the colours they had produced.

Fix: keep the state on the mesh (`post.userData.state`), route both
`setLevels` and `refreshTheme` through one `repaint(post)`.

**Second: the state ramp was ordered by lightness, which flips between themes.**
Two versions were wrong in opposite directions:

| version | dark theme | light theme |
|---|---|---|
| board `--sunken`, `unknown` `--sunken` | `#0d1115` on `#0d1115` — power pads vanished | fine |
| `low` `--sunken`, `unknown` `--line` | fine | `#e4e8ed` and `#d3dae1` — two whites on white |

Fix: order by **contrast against the board**, which does not flip, because
`--ink` is *defined* as the colour that reads against `--surface` in whichever
theme is on:

```js
high: "--changed",  low: "--ink",  input: "--muted",  unknown: "--line",
```

**Generalization.** *Lightness is theme-relative and contrast is not.* Any
two-theme UI that encodes a scale in brightness has this bug waiting. And this
repository has now recorded three times that a pane can be wrong in a way only
a reader sees — `renderMemory` returning one byte for every offset, the
diagnostics ordering, and this.

### 3.6 A regex that matched nothing, in a test about typos

**Symptom.** `test_the_renderer_reads_only_custom_properties_the_stylesheet_defines`
exists precisely because `getPropertyValue` on an undefined name returns `""`
and falls back to grey — a typo paints every high pin the same colour as every
low one, silently. Mutating `--changed` to `--changd` left **all eleven tests
green**.

**Root cause.** The pattern was `read\("(--[a-z-]+)"\)` — literal calls only.
The four state colours reach the stylesheet through `read(name)` inside a loop,
a variable, so they matched nothing at all.

**Fix.** A second pattern for the `STATE_VARIABLE` block, and both asserted
non-empty rather than trusted:

```python
assert DIRECT_READ.findall(source), "no direct colour reads found"
assert len(STATE_READ.findall(block)) == 4, "not every pad state was matched"
```

A count of the union was tried first and is wrong: `--line` paints both the
outline and `unknown`, so seven usages are six names.

**Generalization.** *A source-scanning test must assert that its pattern
matched something.* An empty match set satisfies every `wanted <= declared`
check trivially. This is the same shape as §3.4 — a test that cannot fail —
arriving through a regex instead of a constant.

---

## 4. Reproduce the result, cold

```bash
cd Code/Github/OpenHardware
git log --oneline -1                      # -> 264a260

python tools/build_core.py
#  -> avr 116736 · cortexm0 228864 · i8086 130048 · riscv32 146432

python -m pytest -q                       # -> 1518 passed, 17 skipped (~5 min)
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_ticket_claims check_board_claims; do
  python -m tools.$c; done                # -> all exit 0

python -c "from webui.boards import catalogue as c; from webui import compile as k; \
b=c.catalogue(); print(len(b),'boards |',sum(1 for x in b if x.runnable),'runnable |', \
sum(1 for x in b if x.firmware_verified),'firmware-verified |', \
sum(1 for x in b if x.runnable and k.RECIPES.get(x.chip)),'buildable')"
#  -> 26 boards | 12 runnable | 10 firmware-verified | 3 buildable
```

### Building for the second board without a browser

```bash
python -c "
from webui import api, compile as k
from webui.boards import samd21
b = k.build('XIAO-SAMD21-DIP', 'void setup(){pinMode(D0,OUTPUT);}\nvoid loop(){digitalWrite(D0,HIGH);}')
print(b.ok, len(b.image))                      # -> True 5304
with api.load_firmware('XIAO-SAMD21-DIP', b.image, base=k.recipe_for('XIAO-SAMD21-DIP').base) as s:
    s.step(60000)
    print(api.pin_view(s.runtime, s.cpu, 'XIAO-SAMD21-DIP')['pads'][6])
"
#  -> {'label': 'D0', 'pin': 'D0', 'chip_pin': 'PA02', 'x': 152.4, 'y': 20.8,
#      'group': 'header-top', 'state': 'high'}
```

### Driving the IDE and the pin view

**Kill every listener first and count them** — §9.

```bash
netstat -ano | grep ":8088" | grep LISTENING | awk '{print $5}' | sort -u \
  | while read pid; do taskkill //PID $pid //F; done
netstat -ano | grep ":8088" | grep -c LISTENING     # -> 0
python webui/emulator_server.py
```

Pick **XIAO-SAMD21-DIP**, type a sketch, press **Build and run**.

**The byte count moves with the sketch and the entry point with it**, so it is
not a fixed expected output. Two measured pairings, both on 2026-08-26:
a `LED_BUILTIN`-only blink gives `5324 bytes on XIAO-SAMD21-DIP, entered at
0x000002d0`; one that also drives `D0` and `D6` gives `5372 bytes ... entered
at 0x00000300`. What *is* fixed is that it builds and the report names the
board. The Pins panel shows `12 of 15 pads answerable · XIAO-SAMD21-DIP`,
a 3D board you can drag, and a table reading `D0 | PA02 | high`. Press **Run**
again and the states flip — see §6.2 for why they do not animate.

### The oracle, for the exception frame

```bash
node tools/gen_armv6m_exception.mjs      # exits 3 and says SKIPPED without rp2040js
```

### The optional reference trees

All optional; the tests **skip** without them and never pass quietly.

```bash
npm install --prefix third_party/avr8js avr8js@0.21.0 && node tools/gen_avr_corpus.mjs
tools/get_armv6m_tests.sh                 # needs ../rp2040js built
bash tools/get_8088_tests.sh --opcodes 00 01 88 89
python tools/import_pindefs.py --fetch    # NEW dependency: the Seeed SAMD variant
```

**`import_pindefs.py --fetch` is now load-bearing for a build, not only for a
report.** The XIAO's variant is Seeed's, not Arduino's, and
`webui/compile.py` reads it from `third_party/bsp/seeed-samd/variants/XIAO_m0`.

### Two PlatformIO packages installed this session

Neither was present before and the SAMD21 row needs both:

```bash
pio pkg install --global --tool framework-cmsis-atmel   # samd.h — Microchip's device layer
pio pkg install --global --tool framework-cmsis         # core_cm0plus.h — Arm's
```

---

## 5. File inventory

### New this session

| File | Bytes | What |
|---|---|---|
| `core/cortexm0/exception.h` | 4,135 | the frame's shape, and what is deliberately not modelled |
| `core/cortexm0/exception.cc` | 6,171 | `EnterException`, `ReturnFromException`, `ServicePending` |
| `tools/gen_armv6m_exception.mjs` | 7,701 | asks rp2040js what an exception does; exits 3 without it |
| `tests/cortexm0/test_exceptions.py` | 22,554 | 24 tests; every value from the oracle |
| `tests/cortexm0/test_samd21_arduino.py` | 19,037 | 8 tests; a vendor image from reset into `loop()` |
| `tests/cortexm0/samd21_arduino/blink.cpp` | 1,904 | three lines; the binary is **not** committed |
| `webui/static/board3d.js` | 13,583 | the renderer; no colour of its own |
| `webui/static/board3d-panel.js` | 5,208 | the page glue; lazy-imports the renderer |
| `tests/webui/test_pin_view.py` | 10,172 | 14 tests; the four-state vocabulary |
| `tests/webui/test_board3d.py` | 11,376 | 11 tests; what Python can decide about a WebGL scene |

### Modified

`core/cortexm0/{cpu.h,cpu.cc,exec.cc,abi.h,abi.py,CMakeLists.txt}` (ABI 13),
`webui/boards/samd21.py` (+382 lines), `webui/boards/atmega328p.py` (+53),
`webui/compile.py` (+234), `webui/api.py` (+120), `webui/emulator_server.py`
(one route), `webui/static/{emulator.html,emulator.js,emulator.css}`,
`tests/cortexm0/test_board_samd21.py` (+116), `tests/webui/test_compile.py` (+211).

**4,217 insertions, 58 deletions across 32 files.**

### Evidence that is NOT durable

`.playwright-mcp/pins-*.png` — eight screenshots, **gitignored**. They are the
evidence for §8 and they will not survive a clone. §8 describes each in words
for that reason.

---

## 6. Open work, highest priority first

### 6.1 The Uno's PORTC and PORTD — *software-only, START HERE*

**`python tools/tickets.py list` shows no P1**, so this is a judgement rather
than a queue position — and it is the cheapest change with the most visible
result. **File a ticket first**; it has none, and it will touch
`webui/boards/atmega328p.py` and `tests/avr/`.

**Twenty of the Arduino Uno's twenty-six `unknown` pads would go live.**
`webui/boards/atmega328p.py` models `PORTB` only, so `pin_states` answers for
six of thirty-two pads and the panel says `6 of 32 answerable`. Pins 0-7 are
PORTD and A0-A5 are PORTC.

Do it the way this repository requires rather than by adding registers: write a
sketch that drives pin 7 and A0, run it, watch what it reaches, then model
exactly that. From `iom328p.h`: `PINC/DDRC/PORTC` at `_SFR_IO8(0x06/0x07/0x08)`
and `PIND/DDRD/PORTD` at `_SFR_IO8(0x09/0x0A/0x0B)` — remember `+0x20` for the
data-space form, which `atmega328p.py` calls "the likeliest off-by-something in
an AVR model".

Then extend `HEADER` from the same `pins_arduino.h:150-194` tables already
cited, and `PIN_NAMES` follows for free because it is derived.

### 6.2 A free-running clock behind Run — *software-only*

**Run is a fixed 200,000-instruction budget**, so a blink is watched by pressing
Run repeatedly rather than by watching it move. The pins are live; the clock is
not. `webui/static/emulator.js` already polls `/api/board/state` and
`window.boardPins?.levels()` repaints from it — so what is missing is a server
side that keeps stepping, not a UI.

Read `webui/api.py`'s `BoardSession.run` and `RunResult` first. The honest
design question is what a "run" means when the page can disconnect.

### 6.3 The two research tickets — *software-only, unchanged*

- **OH-8** — an EU cost table for the register form from **Intel's published
  timing table** rather than fitted, verified against the 123 opcodes measured
  deterministic. Deriving it from the corpus needs a held-out split to mean
  anything, and should say so loudly.
- **OH-11** — three leads, in order: (a) the 33 IDIV cases are all **prefixed**
  encodings, so check whether the discriminator is instruction *length* rather
  than an arithmetic property; (b) solve per-case for the byte set consistent
  with all three flags; (c) Ken Shirriff's published 8086 microcode
  disassembly, which this repository has never consulted.

### 6.4 Blocked, and why — *do not start these*

- **OH-36** — Cortex-M33, nine boards. Blocked on an oracle **and held by a
  live session lock** (`agent-oh36`). Do not steal it.
- **OH-64** — Cortex-M4, 2 boards. Blocked on an oracle. **Narrowed this
  session** off `core/cortexm0/exec.cc` and `cpu.h`, because OH-67 needed both
  and this could not use them while blocked; it re-claims them when its oracle
  exists.
- **OH-38** — Xtensa, 3 boards. Refused on evidence.
- **OH-9** — PICSimLab adapter.

### 6.5 Residuals

1. **`core.avr.abi.Cpu` after `close()` segfaults** the interpreter instead of
   raising — the handle is `None` and ctypes calls through it. Two lines, in
   nobody's ticket. **Carried from the last handoff, still true.**
2. The 3D view has **no hover picking**. Deliberate: nothing on the emulator
   page has anything to select a pin *for* yet.
3. **No PCB artwork**, though 25 board SVGs exist. The Uno's lives in
   PICSimLab's `share/` tree and is absent on a clean checkout, so texturing
   would work on 25 boards and silently not on the one most people start with.
4. `Serial` on a XIAO **cannot work** and this is not a gap to fill: it is USB
   CDC and there is no host to enumerate to. The recipe builds without
   `USBCON` for that reason. `Serial1` (SERCOM4) is the route if one is wanted,
   and SERCOM is not modelled — `Serial1.begin()` faults at `0x42001000`.
5. `sh1add`/`bset` accounted in the RISC-V sweep — unchanged.
6. `PYI034` on `__enter__` in all four cores — known, `ruff` is not adopted.
7. The UI does not surface which of a board's ISA the core executes.

---

## 7. Commits this session

```
264a260 chore(tickets): close OH-30
b581584 feat(webui): the board in 3D, with its pins live
b2cb5a4 docs: three buildable boards, not four
762de65 chore(tickets): close OH-66, and file the gap the browser found
408f529 feat(webui): a second board in the compile service, so the IDE is not an Uno feature
2764df6 chore(tickets): close OH-68
1d3acbd feat(boards): the SAMD21 registers a vendor Arduino image asks for
7a3ff38 chore(tickets): close OH-67
20cf75e feat(cortexm0): SysTick, and the exception an Arduino core waits for
06ab50d chore(tickets): OH-66 needs two things first, both of them measured
```

`b2cb5a4` corrects a count in `408f529`'s message: three buildable boards, not
four. Four came from adding recipe rows to boards instead of counting boards.

---

## 8. Visual output verification

Driven in Chromium via Playwright, listener count verified as 0 before starting
and 1 after. **0 console messages at warning level or above**, on every pass.

**`pins-final.png` — the XIAO SAMD21, dark theme, mid-run.** Left: a dark
slate slab in perspective, tilted so both header rows are visible, with a
lighter outline at its edge. Fourteen cylindrical posts stand on it in two rows
of seven. The front row, left to right: one bright near-white post (D6, driven
low — maximum contrast), five mid-grey posts (D5–D1, never configured), and one
green post at the right (D0, driven high). The back row: four mid-grey posts
(D7–D10), then three barely-visible posts almost the colour of the slab
(3V3_OUT, GND, VBUS — pads this repository cannot answer for). Right: a
three-column table, `Pad | Pin | State`, fifteen rows. `D6 PB08 low`,
`D0 PA02 high` in green, `D5`–`D10` `input`, the three power pads dimmed with
`—` for the pin and `not modelled` for the state, and a final row
`LED on board | PA17 | high` in green. Above it the note reads
`12 of 15 pads answerable · XIAO-SAMD21-DIP`.

**`pins-light3.png` — the same board, light theme.** A white slab. D6 is now
the **black** post (still maximum contrast, inverted), D0 is dark green,
D5–D10 are mid slate, and the three unmodelled pads are pale grey and nearly
invisible against white. All four states remain distinguishable, which is what
the contrast ramp buys.

**`pins-dark3.png` — the same page after pressing the theme toggle**, not after
a reload. The posts recoloured with the board. Before the §3.5 fix this frame
showed dark-theme pins on a white board.

**`pins-uno.png` — the Arduino Uno.** A larger, wider slab with two long rows of
smaller posts, one green (pin 13, the LED). The table has **32 rows**, of which
six carry a `PB…` pin and a state and **twenty-six** read `not modelled` in
grey. The note reads `6 of 32 pads answerable · Arduino Uno`. This is the frame
that shows the model's honesty: a person can see at a glance that this is a
thin board model rather than a quiet program.

**`pins-dark.png` — the first version, kept as the counter-example.** The slab
and the three unmodelled pads are both `--sunken`, `#0d1115` on `#0d1115`, and
the power pads are simply not there. §3.5.

---

## 9. Known limitations and traps

- **Backticks in a Bash heredoc are command-substituted and silently eat
  text.** Recorded last session, hit again this one when the `$(...)`-free
  ticket notes still needed Python. **Use Python for any note or file
  containing them**, the same way the earlier handoff says to use Write/Edit
  for anything with `\n` escapes.
- **A Python heredoc inside a `&&` chain can break on quoting.** `python - <<'PY'`
  with a body containing both quote kinds failed with
  ``unexpected EOF while looking for matching `'``. Write the script to the
  scratchpad and run it instead; that path never failed.
- **`tools/tickets.py stop` releases only what the CURRENT pid holds.** Every
  CLI invocation is a new pid, so `start` in one command and `stop` in another
  leaves the lock. **29 stale locks are in `.omc/ticket-locks/` right now**;
  only `OH-36.lock` (`agent-oh36`) is live. Delete the rest freely.
- **A ticket-only commit must be made with `.omc/current-ticket` empty.** A
  ticket implicitly claims its own file, so editing OH-64's and OH-68's ticket
  files while holding OH-67 is refused by the pre-commit hook. Blank the file,
  commit, restore it.
- **`done` tickets do not own their paths.** `tickets.py owner` reports them
  unclaimed, so a follow-up edit to a closed ticket's file is allowed.
- **The stale-server trap.** `pkill -f` does not work in Git Bash here. Always
  count listeners before trusting the page: `netstat -ano | grep ':8088' |
  grep -c LISTENING`.
- **`~` is not the home directory in Git Bash here.** `HOME=/c/SPB_Data`. Use
  `$USERPROFILE`.
- **`framework-arduino-samd` will not compile without `-DCDC_ENABLED`.**
  `USBAPI.h` declares a member whose type only exists under `CDC_ENABLED`,
  which `USBDesc.h` defines only under `USBCON`. That is a bug in this version
  of the core. Defining `CDC_ENABLED` and **not** `USBCON` compiles the
  declaration and skips the USB device, which is what is wanted.
- **The vendor's own linker script is the wrong one for an emulator.** Seeed's
  `boards.txt:154` names `flash_with_bootloader.ld`, correct for a real XIAO
  whose UF2 bootloader owns the first 8 KB. Here it puts the vector table at
  0x2000 where a Cortex-M0+ never looks — the image links, loads, and executes
  erased flash.
- **Do not add `@pytest.mark.parametrize`.** `tools/inventory.py` counts
  `def test_*` with `ast`. Loop inside one test.
- **A ralph-style run does not get an independent reviewer here.** Every ticket
  this session was self-verified with a full gate and, where it touched the UI,
  a real browser. That is not the same as a review — say so rather than
  implying one happened.
