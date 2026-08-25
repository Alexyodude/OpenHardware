# Handoff — the AVR oracle, and an IDE that cannot exist yet

| | |
|---|---|
| **Date** | 2026-08-26. Newer than `HANDOFF_2026-08-25_the-esp32-c-series.md`; where they disagree, **this one wins** |
| **Repo** | `Alexyodude/OpenHardware` — not a fork, MIT |
| **Branch / HEAD** | `master` @ `0b841bd` |
| **Working tree** | **Clean.** Nothing uncommitted, nothing stashed |
| **Toolchain** | MSVC 19.44; Python 3.13; node 24.11.1 / npm 11.6.2; **arm-none-eabi GCC 12.3.1**, **avr-gcc 7.3.0**, **riscv32-esp-elf GCC 8.4.0**, all under `~/.platformio/packages/` |
| **Cores built** | `build/lib/`: `avr.dll` 96,256 · `cortexm0.dll` 222,208 · `i8086.dll` 129,024 · `riscv32.dll` 146,432 |
| **Gate** | **1,301 passed, 17 skipped** (1,318 collected); all eight checkers exit 0 |
| **Boards** | 26 imported, **12 runnable, 10 firmware-verified** (was 8 and 8) |
| **Reference trees** | `../esp-idf-reference` (v5.5.0 `8c750b0`, sparse) · `../rp2040js` · `third_party/avr8js/node_modules/avr8js` (0.21.0) |

**The second session that was committing here is still quiet.** No commits but
mine since `a15b398`. Still stage by explicit path — see §9.

**QEMU is not installed on this machine.** Verified again this session: no
`qemu-system-arm`, no PlatformIO package, nothing in Program Files. Two tickets
turn on that fact.

---

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| ESP32-C6 board, runnable and firmware-verified | **ACHIEVED** | `tests/riscv32/test_esp32c6_board.py`, 16 tests; `13d3148` |
| ESP32-C5 board, described, firmware claim withheld | **ACHIEVED** | `webui/boards/esp32c5.py`; `catalogue.FIRMWARE_VERIFIED` has no C5 row |
| A citable header source for both parts | **ACHIEVED** | `docs/esp-idf-reference.md`; ESP-IDF v5.5.0 `8c750b0` |
| Armv7E-M **decode** | **ACHIEVED** | 172,032 wide + 1,260 IT encodings, 0 disagreements; `ca38cb7` |
| Armv7E-M **execution** | **BLOCKED ON ORACLE** | QEMU absent; OH-50 closed on its second Done-when |
| `parse_uf2` load-nothing-report-success | **ACHIEVED** | `firmware.EmptyImage`; `5e7c6ae` |
| An AVR oracle that can verify instruction work | **ACHIEVED** | avr8js corpus + `tests/avr/test_conformance.py`; `f721f35` |
| **A real Arduino sketch running on the Uno** | **NOT STARTED** | OH-58 — §6.1, the top open item. 45 mnemonics in `STILL_MISSING` |
| An in-browser IDE | **NOT STARTED** | Blocked behind OH-58 by the user's decision — see §3.5 |
| 8 Cortex-M33 boards | **BLOCKED ON ORACLE** | OH-36, held by `agent-oh36` |
| 3 ESP32-S3 boards | **REFUSED ON EVIDENCE** | OH-38, unchanged |

### The twelve runnable boards

```
Arduino Uno           ATmega328P  avr       tests/avr/test_uno_board.py
XIAO-ESP32-C3-DIP     ESP32-C3    riscv32   tests/riscv32/test_esp32c3_board.py
XIAO-ESP32-C3-DIP-SMD ESP32-C3    riscv32   tests/riscv32/test_esp32c3_board.py
XIAO-ESP32-C3-SMD     ESP32-C3    riscv32   tests/riscv32/test_esp32c3_board.py
XIAO-ESP32-C5-DIP     ESP32-C5    riscv32   described only -- no firmware claim
XIAO-ESP32-C5-SMD     ESP32-C5    riscv32   described only -- no firmware claim
XIAO-ESP32-C6-DIP     ESP32-C6    riscv32   tests/riscv32/test_esp32c6_board.py
XIAO-ESP32-C6-SMD     ESP32-C6    riscv32   tests/riscv32/test_esp32c6_board.py
XIAO-RP2040-DIP       RP2040      cortexm0  tests/cortexm0/test_blink.py
XIAO-RP2040-SMD       RP2040      cortexm0  tests/cortexm0/test_blink.py
XIAO-SAMD21-DIP       SAMD21      cortexm0  tests/cortexm0/test_samd21_blink.py
XIAO-SAMD21-SMD       SAMD21      cortexm0  tests/cortexm0/test_samd21_blink.py
```

---

## 2. What changed, in one paragraph each

**The last four ESP32-C boards landed.** The vendor headers were not installed
and could not be, so the numbers come from a second reference checkout whose
admissibility is itself a test.

**`core/cortexm0` reads Armv7E-M.** A `Profile` gate, the Armv7-M
instruction-length rule, and the Thumb-2 encodings a Cortex-M4 executes. The
decoder only — nothing executes an Armv7E-M instruction and the reason is
recorded rather than left as an absence.

**Four firmware parsers now refuse to load nothing.** Two of them used to
return an empty Image and report success.

**The AVR core has an oracle for the first time**, and the first thing it did
was find a bug in itself. No AVR instruction has been implemented yet.

---

## 3. Root-cause narratives

### 3.1 The ESP32-C5's GPIO offsets are not the C6's, and the base *is*

**Symptom.** None yet — this was caught before writing the board file, by
reading the headers rather than the neighbour.

**Wrong hypothesis, and how it was ruled out.** OH-57's own text says "the C5 is
not simply a C3 with different addresses", which reads as a warning about the
*ISA*. Measured, the memory maps differ too, and the dangerous part is where
they agree:

```
                 ESP32-C3     ESP32-C6     ESP32-C5
DR_REG_GPIO_BASE 0x60004000   0x60091000   0x60091000   <- C5 and C6 the same
GPIO_OUT_REG     base + 0x04  base + 0x04  base + 0x04
GPIO_ENABLE_REG  base + 0x20  base + 0x20  base + 0x34  <- moved
GPIO_IN_REG      base + 0x3c  base + 0x3c  base + 0x64  <- moved
```

**Root cause.** `+ 0x3c` is `GPIO_IN` on a C3 and a C6 and
`GPIO_ENABLE_W1TC` on a C5. A board written by copying its neighbour would map
a write-one-to-clear enable register at the address it believed was a read-only
input. **That does not fault** — the address is mapped, so firmware disabling an
output would appear to be reading pins.

**Fix.** Every constant read from the header it cites, and the collision pinned:
`test_the_c5_register_file_is_not_the_c6_one` asserts
`esp32c5.GPIO_ENABLE_W1TC == esp32c6.GPIO_IN == 0x3C`.

**Generalization.** *A shared base makes a divergent register file more
dangerous, not less.* The number a copy would sanity-check is the one that
matches.

### 3.2 The headers did not exist here, so the source itself needed a test

**Symptom.** `framework-arduinoespressif32/tools/sdk/` holds
`esp32 esp32c3 esp32s2 esp32s3` and nothing else. PlatformIO's registry has no
newer version of that package — 3.20017 is ESP-IDF 4.4.7 and is the newest.

**Root cause.** Every address in `webui/boards/esp32c3.py` cites a line in that
tree, and this repository does not accept remembered numbers. Describing a C5
or C6 meant reading a *different* tree, which is a different claim.

**Fix.** A sibling ESP-IDF v5.5.0 checkout (`docs/esp-idf-reference.md`), made
admissible by a control: v5.5's own `esp32c3` headers must reproduce every
number `esp32c3.py` already carries from 4.4.7.
`test_the_new_header_tree_reproduces_the_board_this_repository_already_had`
runs that check. **`esp32c3` is in the sparse checkout for no other reason.**

**Generalization.** *Adopting a second source is a claim, and the cheapest way
to license it is to make it reproduce the first.*

### 3.3 Three tests were counting down to the same day, and one had already fired

**Symptom.** After `webui/boards/esp32c6.py` landed,
`test_each_refusal_arrives_as_itself` failed and
`test_a_chip_nothing_describes_is_refused_even_with_a_built_core` **skipped**
with `every board with a built core is described`.

**Root cause.** `chip-not-described` needs a board that is core-built and
undescribed. There has always been one, and never the same one for long —
SAMD21 until OH-39 (`bdcc8c9`), ESP32-C3 until OH-48 (`3ccfe87`), ESP32-C6
until this ticket. Three tests depended on that example; OH-57's own text
warned about **one** of them. The third had a `pytest.skip` escape hatch and so
degraded silently instead of failing.

**Fix.** `only_undescribed()` in `tests/webui/test_board_run.py` — a `tmp_path`
catalogue holding one board JSON and no `.py`. After OH-57 there is **no fifth
name to move to**: every remaining chip needs a core that is not built and
answers `core-not-built` instead.

**Generalization.** *A test that finds its example in live data is on a
countdown, and the loudest failure is the kind option.* A skip is better than a
vacuous pass and still is not a test.

### 3.4 Armv7E-M is not a superset in the way that matters

**Symptom.** None — this was measured before choosing a shape, and it decided
the shape.

**Root cause, two of them.**

`core/cortexm0/exec.cc:642` decided instruction length with
`(encoding & 0xF800) == 0xF000`: Armv6-M's rule, where `BL` is the only 32-bit
instruction. Armv7-M has three wide prefixes. And the failure is quiet: `0xE8B0`
read as narrow leaves `0x0006` next, which is a real `movs r6, r0`, so an
Armv6-M reading of a Cortex-M4 image is **a plausible listing, shifted** rather
than obvious rubbish.

Second: Armv7E-M adds **16-bit** encodings too — `CBZ`, `CBNZ`, `IT` — in space
Armv6-M leaves undefined. So the profile had to reach the narrow decoder, not
only the width test. `IT` then needed *state*: it makes the following
instructions conditional and suppresses their flag-setting, so `movs r3, #11`
renders as `movls r3, #11`.

**Fix.** `disasm.Profile`, `is_wide()`, `_narrow_v7em()`, and an `_ItBlock`
queue that `disassemble()` walks.

**Generalization.** *"Strict superset" is a statement about the instruction
set, not about the decoder.* Ask what changes upstream of decode.

### 3.5 A real Arduino sketch stops on instruction one

**Symptom.** Compiled a real sketch — `setup()`/`loop()`/`pinMode()`/
`digitalWrite()`/`delay()` against `framework-arduino-avr`, 1,058 bytes — loaded
it on the Uno board:

```
STOPPED after 0 steps: Unimplemented: no implementation for 0x940c at word 0x0000
```

**Wrong hypothesis, ruled out by measurement.** The obvious guess is
*peripherals*: `webui/boards/atmega328p.py` calls `configure()` and maps no
registers, so `delay()` would hang on a timer that never ticks. That is true and
it is **not** what stops it. `0x940C` is `JMP`, the reset entry of the vector
table, and every Arduino image begins with one.

**Root cause, sized.** Stepping every distinct encoding in that image:

```
246 distinct encodings
114 the core executes
132 the core refuses
```

32 mnemonics have **no** encoding implemented: `.word adc add and andi call cli
com cp cpse dec inc jmp lds lpm lsr mov movw mul muls mulsu neg nop or ori pop
ret reti ror sbc sbci sbic sbis sbiw sec sei sez sts sub subi swap`. Two more
are partial: `ld` (2 of 6), `st` (1 of 7). Without `call`/`ret` there are no
function calls; without `pop` no prologue unwinds.

**This is not a defect in `core/avr`.** It was built for
`tests/avr/blink/blink.c` and its header says so in the first line. OH-49
claimed exactly what it delivered.

**Fix.** None yet — OH-58 is the ticket, and §6.1 is where it starts.

**Generalization.** *A core sized to one image is not a core, and only a
different image finds out.* The blink test passed throughout.

### 3.6 The oracle was wrong and the code under test was right

**Symptom.** The very first conformance run reported 11 disagreements, all
`cpc` and `cpi`, all on one SREG bit:

```
cpc r0, r1 (variant 1): SREG 0b00011000 != 0b00111000
cpi r20, 1 (variant 0): SREG 0b00000000 != 0b00100000
```

Bit 5 is **H**, the half-carry.

**Wrong hypothesis, and it is the dangerous one.** The reflex on a differential
failure is that the thing under test is wrong. Ruled out by computing the
datasheet's own formula by hand for the failing operands, which agreed with
`core/avr` and not with the oracle.

**Root cause**, `third_party/avr8js/node_modules/avr8js/dist/cjs/cpu/instruction.js:32`:

```js
sreg |= 1 & ((d & r) | (r & ~R) | (~R & d)) ? 0x20 : 0;
```

`d` and `r` are raw register bytes, never shifted, so this reads **bit 0** where
the datasheet's `Rd3·Rr3 + Rr3·/R3 + /R3·Rd3` reads **bit 3**. All eleven of
avr8js's H expressions do it. The case needing no formula at all:

```
add 0x8,0x8 -> R=0x10  datasheet H=1  avr8js H=0   <-- DISAGREE
```

`0x08 + 0x08 = 0x10` obviously carries out of the low nibble.

**Fix.** A case carries **two sources that are never blended**: `avr8js` for
registers, PC, SP, memory and SREG-without-H; `manual` for H alone, from the
datasheet's boolean expression, stored with the expression it came from. 62 of
147 half-carry cases disagree, and
`test_the_oracle_half_carry_is_still_wrong` asserts they do — so the exclusion
cannot outlive the bug.

**Generalization.** *An oracle is a second opinion, not an authority.* Had the
core been "fixed" to match, working code would have been broken to reproduce an
upstream bug — and every later AVR instruction would have been written against
a wrong half-carry.

### 3.7 A test was pinning a defect in place

**Symptom.** `parse_uf2` returns an Image with zero segments when the requested
family is absent — OH-32 reported it 2026-08-25, reproduced 2026-08-26.

**Worse than reported.** The empty Image also carried
`family=uf2_family_name(wanted)` — the family that had been *asked for* — so a
caller saw `format="uf2", family="RP2040"` and no bytes.

**And it was not alone.** `parse_hex` did the same for a file with only an
end-of-file record. Nobody had reported that one.

**Root cause of its survival.** `tests/webui/test_board_run.py:431` read

```python
assert firmware.parse_uf2(wrong, family="RP2040").segments == ()
```

The seam caught the empty result at the API, so nothing broke — and the
assertion held the workaround steady. Every *other* caller of
`firmware.load_image` still had the bug.

**Fix.** `firmware.EmptyImage`, a subclass of `FirmwareError`, raised by all
four parsers. `webui/api.py` catches it by type and re-raises as
`nothing-for-this-chip`, because "your file is for another chip" and "your file
is broken" send a person to different places.

**Generalization.** *A test pins a workaround exactly as well as it pins a
fix.* An assertion describing behaviour somebody called a bug deserves a look at
who is meant to fix it.

### 3.8 Two harness bugs, each caught by its own shape

**19,968 disagreements that were all one constant.** The first Thumb-2 sweep
reported every branch wrong by exactly `0x8000` — `BASE`. objdump numbers a raw
binary from zero. Fixed with `--adjust-vma`; **not** by setting `BASE` to zero,
which would have made the sweep agree with a decoder that forgot the base.

**A sweep that was blind to a whole sub-group.** `wide_space()`'s second-halfword
spread reached no encoding with `hw2[7:4]` set, so `clz`, `rbit`, `rev.w` and
`revsh.w` sat outside it while the summary read `0 wrong`. Adding six values
immediately found 91 real disagreements.

**Generalization.** *A large round failure count is the instrument before it is
the thing measured; and a sweep is only as good as its spread.* The second is
harder — nothing tells you what you did not cover.

---

## 4. Reproduce the result, cold

```bash
cd Code/Github/OpenHardware
git log --oneline -1                      # -> 0b841bd

python tools/build_core.py
#  -> build/lib: avr.dll 96256 · cortexm0.dll 222208 · i8086.dll 129024 · riscv32.dll 146432

python -m pytest -q                       # -> 1301 passed, 17 skipped (~6 min)
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_ticket_claims check_board_claims; do
  python -m tools.$c; done                # -> all exit 0

python -c "from webui.boards import catalogue; c=catalogue.catalogue(); \
print(len(c),'boards |',sum(1 for b in c if b.runnable),'runnable |', \
sum(1 for b in c if b.firmware_verified),'firmware-verified')"
#  -> 26 boards | 12 runnable | 10 firmware-verified
```

### The two reference trees the new tests want

Both are optional: the tests **skip** without them and never pass quietly.

```bash
# ESP-IDF, for the C5/C6 header cross-checks. See docs/esp-idf-reference.md.
git clone --filter=blob:none --no-checkout --depth 1 --branch v5.5 \
    https://github.com/espressif/esp-idf ../esp-idf-reference
cd ../esp-idf-reference && git sparse-checkout init --cone
git sparse-checkout set components/soc/esp32c3 components/soc/esp32c5 \
    components/soc/esp32c6 tools/cmake examples/get-started/blink
git checkout

# avr8js, the AVR oracle. third_party/ is gitignored.
npm install --prefix third_party/avr8js avr8js@0.21.0
node tools/gen_avr_corpus.mjs   # -> 552 cases from 184 encodings
```

### The two sweeps, run by hand

```bash
python -m tools.sweep_thumb2
#  wide encodings: 172032 swept: 58877 agreed, 61010 refused by both,
#                  51995 unnamed, 150 accounted, 0 wrong. ... names 53.2%.
#  IT blocks:      1260 swept: 1260 agreed, 0 refused by both, 0 unnamed,
#                  0 accounted, 0 wrong. ... names 100.0%.

python -m tools.sweep_thumb2 --unnamed 20   # what is still unnamed, and why
```

### The AVR baseline, which OH-58 moves

```bash
python -m pytest tests/avr/test_conformance.py -q     # -> 3 passed
python - <<'PY'
import sys; sys.path.insert(0, "tests")
from avr.test_conformance import verdicts
v = verdicts()
print(f"{sum(len(x) for x in v.values())} cases: {len(v['agreed'])} agreed, "
      f"{len(v['refused'])} refused, {len(v['wrong'])} wrong")
PY
#  -> 552 cases: 78 agreed, 474 refused, 0 wrong
```

### Driving the ESP32-C6 in the browser

**Kill every listener first** — §9.

```bash
netstat -ano | grep ":8088" | grep LISTENING | awk '{print $5}' | sort -u \
  | while read pid; do taskkill //PID $pid //F; done
netstat -ano | grep ":8088" | grep -c LISTENING     # -> 0
python webui/emulator_server.py
```

Pick `XIAO-ESP32-C6-DIP`, choose `tests/riscv32/c6blink/blink.bin`, base
`0x42000000`, Load, Run. Expect `pc 0x42000028`, 33 registers, `sp 4087FFE0`,
zero flags, and a listing whose widths interleave 4/2/2/2/2.

---

## 5. File inventory

### New this session

| File | Bytes | What |
|---|---|---|
| `webui/boards/esp32c6.py` | 12,874 | One flash window, one SRAM address, GPIO at 0x60091000 |
| `webui/boards/esp32c5.py` | 14,325 | `ISA` / `EXECUTES` / `ABSENT` — the part, the subset, the gap |
| `tests/riscv32/test_esp32c6_board.py` | 23,053 | 16 tests; **the evidence for ESP32-C6** |
| `tests/riscv32/test_esp32c5_board.py` | 22,287 | 16 tests; the 4,224-encoding Zc refusal sweep |
| `tests/riscv32/c6blink/blink.bin` | **52** | Committed; `-march=rv32imac` |
| `tools/sweep_thumb2.py` | 19,977 | Two sweeps against objdump; importable by its test |
| `tests/cortexm0/test_thumb2_disasm.py` | 18,583 | 14 tests; the decode evidence for OH-50 |
| `tests/cortexm0/m4/probe.bin` | **380** | A Cortex-M4 image that exists to be *read*, never run |
| `tools/gen_avr_corpus.mjs` | 15,686 | Captures avr8js, and the manual's H beside it |
| `tests/avr/test_conformance.py` | 10,120 | 3 tests; `STILL_MISSING` is OH-58's ledger |
| `tests/avr/corpus/isa.json` | 486,777 | 552 cases from 184 encodings, committed |
| `docs/esp-idf-reference.md` | 4,968 | How to get the tree, and which revision the citations mean |

### Modified

`core/cortexm0/disasm.py` (Profile, Thumb-2, `_ItBlock`, **two pre-existing bug
fixes**), `webui/firmware.py` (`EmptyImage`), `webui/api.py`,
`webui/boards/catalogue.py`, `.gitignore`, and six test files whose tripwires
fired.

### Not committed, and deliberately

`third_party/avr8js/` and `../esp-idf-reference/` are both outside the index —
`.gitignore` covers the first and the second is a sibling. The Arduino-shaped
RP2040 runtime spike (§6.5) lives only in the session scratchpad; it was a
feasibility probe, not a deliverable.

---

## 6. Open work, highest priority first

### 6.1 OH-58 — implement the AVR instruction set — *software-only, START HERE*

**The oracle and the ledger are both in place; no instruction has been written
yet.** This is the whole of the remaining work and it is now verifiable one
encoding at a time.

Start by reading `tests/avr/test_conformance.py`'s `STILL_MISSING` — 45
mnemonics — and `core/avr/exec.cc`, which is a flat if-chain of 14 decode
patterns and 320 lines. Add to that chain; delete the mnemonic from
`STILL_MISSING`; run:

```bash
python -m pytest tests/avr/test_conformance.py -q
```

`test_the_refused_set_is_exactly_what_is_recorded` fails in **both**
directions, so forgetting to update the ledger is as loud as breaking
something.

**Suggested order, and it is not arbitrary** — nothing runs until the first
group is done: `jmp`, `call`, `ret`, `reti`, `pop` (control flow and the stack),
then `mov`, `movw`, `add`, `adc`, `sub`, `sbc`, `and`, `or`, `com`, `dec`,
`cp`, `cpse`, then the immediates `subi`, `sbci`, `andi`, `ori`, then
`lds`/`sts` and the `ld`/`st` pointer forms, then `lpm`, `nop`, `cli`, `sei`,
`sbiw`, `sbis`, `muls`, `mulsu`.

**Four things already known and not to be rediscovered:**

**(a) The oracle's half-carry is wrong** — §3.6. `core/avr` is right. Compare H
against `case["manual"]["h"]`, never against avr8js. This is already wired up;
do not "simplify" it away.

**(b) The corpus is regenerated, not hand-edited.** Adding encodings means
editing `tools/gen_avr_corpus.mjs` and re-running `node tools/gen_avr_corpus.mjs`.
It needs `third_party/avr8js` — §4.

**(c) `jmp` and `call` are two words**, and `cpse`/`sbis`/`sbic` skip *over* a
following instruction whose width depends on what it is. avr8js has
`isTwoWordInstruction` for exactly this; the same rule is needed here or a skip
lands mid-instruction.

**(d) The 78-case floor in `test_nothing_the_core_executes_disagrees_with_the_oracle`
is a floor, not a pin.** Raise it as instructions land. It exists so a run with
nothing wrong and nothing executed cannot pass.

**Done when** a real Arduino sketch compiled against `framework-arduino-avr`
executes past its vector table and through `setup()`, and the remaining gap is
measured rather than assumed.

### 6.2 The ATmega328P peripherals — *software-only, blocked behind 6.1*

`webui/boards/atmega328p.py` calls `configure()` and maps **no** registers. An
AVR data space has no holes, so timer writes land in memory and read back as
whatever was written — which means `millis()` returns 0 forever and `delay()`
hangs rather than faults. **Even with a complete ISA an Arduino sketch will
hang here.** `TCCR0A`/`TCCR0B`/`TIMSK0`/`TCNT0` have to tick.

Not filed yet; file it once 6.1 lands, and note that `core/avr` has no
`map_counter` equivalent — `webui/boards/rp2040.py`'s TIMER is the shape to
copy.

### 6.3 OH-10 — the loading path — *software-only, partly done*

Its defect is fixed. Its headline is not: `tools/import_firmware.py` has 42
tests and finds artefacts in `.pio/build/`, arduino-cli and STM32CubeIDE trees,
and **nothing under `webui/` imports it**. A person still picks one file and
types a base address by hand. The base is only needed for a raw `.bin`; an ELF
or UF2 carries its own.

Wiring it up means the server reading directories on a caller's disk. The user's
compile-safety decision this session was **loopback + Origin, same posture as
today** (§6.5) — that answer probably extends here, but it was asked about
compiling, not about reading the filesystem. Ask.

### 6.4 OH-50 residual — a Cortex-M4 interpreter — *blocked on oracle*

The decoder is done and swept. Execution has no oracle: QEMU is absent, and
`docs/architectures.md` records that even where it exists it is a single source
for cortex-m4 with no independent second. `test_the_interpreter_refuses_every_thumb2_prefix`
is the list of things that must start working, and **it fails the day somebody
writes the interpreter**, which is intended.

`webui/boards/nrf52840.py` is deliberately absent — writing it would make two
boards report runnable while an image stops at its first wide instruction.

### 6.5 The IDE, and the decision already taken

The user asked for "an actual IDE where code is runnable in a main loop…
PlatformIO and Arduino style". Two options were measured and **the user chose to
finish the AVR core first** (OH-58) so that *vendor* Arduino sketches run.

The other option was spiked and **works today**: a thin Arduino-shaped runtime
over what `webui/boards/rp2040.py` already models — `pinMode`, `digitalWrite`,
`delay`, `Serial`. Measured output:

```
step       129  t=      1 us  HIGH      setup() ran
step    250141  t=   2001 us  LOW
step    500199  t=   4001 us  HIGH      loop() cycling
gaps: [2000, 2000, 2000, 2000, 2000] us   the sketch asked for 2000
serial output: 'booted\ntick\ntick\n'
```

It needs SIO GPIO, RESETS, the TIMER counter and the UART — all modelled. It
cannot run vendor libraries. The spike is **not in the repo**; it was in the
session scratchpad and is gone. Rebuilding it is a few hours.

**Compile safety, decided:** loopback + Origin check, same posture as the
emulator server. The request carries source and a board name; the **server**
picks compiler, flags and linker script from the board, never from the request.

### 6.6 Residuals

1. **`sh1add`/`bset` accounted in the RISC-V sweep** — unchanged from the
   previous handoff.
2. **`core/riscv32` has no `map_constant`/`map_stream`/`map_counter`** —
   unchanged, deliberate.
3. **`PYI034` on `__enter__` in all four cores** — known, ignored, `ruff` is
   not adopted here.
4. **The UI does not surface which of a board's ISA the core executes.** Both
   `esp32c5.py` and `esp32c6.py` state it and tests pin it; the wire has no
   field for it. Recorded in OH-57's close note.
5. **`tests/rv32/test_gating.py` has two pre-existing ruff findings** —
   unchanged.

---

## 7. Commits this session

```
0b841bd chore(tickets): record OH-10's widened claims
1e538b7 chore(tickets): OH-58 claims a corpus generator, not a lockstep
f721f35 test(avr): an oracle for the AVR core, and it found a bug in the oracle
5e7c6ae fix(firmware): a parser that loads nothing now says so, in all four
255d5d0 chore(tickets): close OH-50
ca38cb7 feat(cortexm0): Armv7E-M decode behind a profile, and where OH-50 stopped
fe1b223 chore(tickets): close OH-57
13d3148 feat(boards): the ESP32-C5 and C6, and a chip described without a claim
```

Tickets closed: **OH-57**, **OH-50** (on its second Done-when). Filed:
**OH-58**. Reopened in practice: **OH-10**, whose defect is fixed and whose
headline is not.

---

## 8. Visual output verification

Checked in a real browser via Playwright with the listener count verified as 1
first. **0 console messages at warning level or above.**

**Board picker.** 26 boards, **12 enabled** — Arduino Uno, three XIAO-ESP32-C3,
two XIAO-ESP32-C5, two XIAO-ESP32-C6, two XIAO-RP2040, two XIAO-SAMD21.

**XIAO-ESP32-C6-DIP**, `tests/riscv32/c6blink/blink.bin` at `0x42000000`:
`pc 0x42000028`, 33 registers with RISC-V ABI names, `sp` `4087FFE0`, **zero
flags** (correct — RV32 has no condition codes), memory pane reading back
`37 01 88 40` at `0x42000000` (`lui sp,0x40880`, little-endian), and the
listing below with widths interleaving 4/2/2/2/2:

```
> 42000028  fef6eae3  bltu a3,a5,0x4200001c     <- current
  4200002C  47b2      c.lwsp a5,12(sp)
  4200002E  0785      c.addi a5,1
  42000030  c63e      c.swsp a5,12(sp)
  42000032  bfd5      c.j 0x42000026
```

**XIAO-ESP32-C5-DIP**, four hand-written instructions: loads, steps, and
`GPIO_ENABLE`/`GPIO_OUT` both read back bit 8. With a `cm.push` halfword
appended it stops with

```
pc=0x42000008: encoding 0x0001b842 is illegal for extensions 0x7
```

— the address and encoding right, the word `illegal` **wrong but the only one
this core has**. See OH-57's close note; it is asserted, not tolerated.

---

## 9. Known limitations and traps

- **The stale-server trap.** `pkill -f` does not work in Git Bash here. Always
  count listeners before trusting the page, with the loop in §4.
- **Heredocs mangle backslash escapes in this shell.** Writing Python or JS
  containing `\n`, `\t` or `\x11` through a `<<'PY'` heredoc silently produced
  literal newlines and **NUL bytes** in two files this session, one of which
  needed deleting and rewriting. Use the Write or Edit tool for any file with
  escapes; heredocs are fine for prose.
- **`~` is not the home directory in Git Bash here.** `HOME=/c/SPB_Data`. Use
  `$USERPROFILE`. `~/.platformio` silently resolves to nothing.
- **Python cannot see Git Bash's `/tmp`.** A file written by `cat > /tmp/x` is
  not at `/tmp/x` for `python`. Use the session scratchpad.
- **The ticket guard is per-holder and it works.** Editing OH-10's ticket file
  while holding OH-58 was refused at commit time. Commit each ticket's file
  under its own hold.
- **`tools/tickets.py start` refuses a stale lock and offers `--steal`.** Locks
  live in `.omc/ticket-locks/` (gitignored) and are keyed to a pid that is
  usually dead. Several are stale from closed tickets; not worth a sweep.
- **objdump decodes a different target in both directions.** Wider: NEON, VFP,
  coprocessor, FPA — 32,112 of the encodings it names in the Thumb-2 space.
  Later: `0xE89F` is `clrm`, **Armv8.1-M**. Its naming an encoding is not
  evidence any part here has it.
- **objdump is lax about `hw2[6]` in the Thumb-2 register-offset loads.** This
  decoder refuses where the manual says should-be-zero; that costs ~1,900
  "unnamed" and is the safe direction.
- **avr8js does not refuse.** An encoding it does not know advances the PC and
  changes nothing, indistinguishable from a `nop` it does know. Never read "the
  oracle did nothing" as "illegal".
- **An ESP-IDF application will not run on any board here** — unchanged.
- **Do not add `@pytest.mark.parametrize`.** `tools/inventory.py` counts
  `def test_*` with `ast`. Loop inside one test.
