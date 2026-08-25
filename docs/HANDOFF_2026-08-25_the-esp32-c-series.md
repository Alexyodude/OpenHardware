# Handoff — the ESP32-C series, and a contract that stopped being Arm-shaped

| | |
|---|---|
| **Date** | 2026-08-25, later than `HANDOFF_2026-08-25_a-fourth-core-and-a-usable-page.md`. Where they disagree, **this one is newer** |
| **Repo** | `Alexyodude/OpenHardware` — not a fork, MIT |
| **Branch / HEAD** | `master` @ `7b623d5` |
| **Working tree** | **Clean.** Nothing uncommitted, nothing stashed |
| **Toolchain** | MSVC 19.44; Python 3.13; **arm-none-eabi GCC 10.3**, **avr-gcc 7.3.0**, **riscv32-esp-elf GCC 8.4.0**, all under `~/.platformio/packages/` |
| **Cores built** | `avr.dll` 96,256 · `cortexm0.dll` 222,208 · `i8086.dll` 129,024 · **`riscv32.dll` 146,432** (was 102,912) |
| **Gate** | **1,250 passed, 17 skipped**; all eight checkers exit 0 |
| **Boards** | 26 imported, **8 runnable, 8 firmware-verified** (was 4 and 4) |

**The second session that was committing here has gone quiet.** No commits but
mine since `a15b398`. Still stage by explicit path — see §9.

---

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| A board contract that admits a non-Arm machine | **ACHIEVED** | `core/<core>/machine.py` ×3; `42126c0` |
| Arduino Uno runnable and firmware-verified | **ACHIEVED** | `tests/avr/test_uno_board.py`, 14 tests; `42126c0` |
| The page stops calling itself an i8086 | **ACHIEVED** | `<title>OpenHardware</title>`; `e76b5fb` |
| RV32 compressed instructions | **ACHIEVED** | 49,152 encodings vs objdump; `d5f1ab9` |
| RV32 multiply and divide | **ACHIEVED** | 8 instructions + 6 defined edges; `99d5b1b` |
| MMIO for the RISC-V core | **ACHIEVED** | `map_register` + `map_alias`; `8695433` |
| **3 ESP32-C3 boards runnable** | **ACHIEVED** | `tests/riscv32/test_esp32c3_board.py`; `3ccfe87` |
| A RISC-V disassembler — the fourth pane | **ACHIEVED** | 3 sweeps, ~110k encodings; `bb4676f` |
| **4 ESP32-C5/C6 boards** | **NOT STARTED** | OH-57 — §6.1, the top open item |
| 8 Cortex-M33 boards | **NOT STARTED** | OH-36, held, blocked on oracle |
| 2 Cortex-M4 boards | **NOT STARTED** | OH-50; no QEMU here, so no oracle |
| 3 ESP32-S3 boards | **REFUSED ON EVIDENCE** | OH-38; confirmed again this session — see §9 |

### The eight runnable boards

```
Arduino Uno           ATmega328P  avr       tests/avr/test_uno_board.py
XIAO-ESP32-C3-DIP     ESP32-C3    riscv32   tests/riscv32/test_esp32c3_board.py
XIAO-ESP32-C3-DIP-SMD ESP32-C3    riscv32   tests/riscv32/test_esp32c3_board.py
XIAO-ESP32-C3-SMD     ESP32-C3    riscv32   tests/riscv32/test_esp32c3_board.py
XIAO-RP2040-DIP       RP2040      cortexm0  tests/cortexm0/test_blink.py
XIAO-RP2040-SMD       RP2040      cortexm0  tests/cortexm0/test_blink.py
XIAO-SAMD21-DIP       SAMD21      cortexm0  tests/cortexm0/test_samd21_blink.py
XIAO-SAMD21-SMD       SAMD21      cortexm0  tests/cortexm0/test_samd21_blink.py
```

---

## 2. What changed, in one paragraph each

**The board contract stopped being Arm-shaped.** It required
`VECTOR_TABLE_OFFSETS` of every board. Measured, that was 1 of 11 gaps: `api.py`'s
`Core` protocol was missing **ten of its twelve methods** on the AVR. Now
`core/<core>/machine.py` says how a machine powers on and what its registers are
called, and `contract.py` asks *the core* what a board owes.

**The page is called OpenHardware.** It said "i8086 Emulator" while you loaded
an ATmega328P into it.

**`core/riscv32` grew the four things a board needs**: compressed instructions
(without which it could not execute the second instruction of a real image),
multiply and divide, memory-mapped IO, and a disassembler.

**Three ESP32-C3 boards run a real `riscv32-esp-elf-gcc` image** with all four
panes.

---

## 3. Root-cause narratives

### 3.1 The measurement that reframed OH-52 — read this before designing anything

**Symptom.** None. The previous handoff's §6.1 said the Arduino Uno was blocked
on "the board contract's entry model", and named three candidate fixes.

**Wrong hypothesis, and how it was ruled out.** All three candidates address
*entry*. Before picking one I compared `api.py`'s `Core` protocol against every
core's ABI:

```
Core protocol needs: clear_memory, clear_registers, clear_regions, write_block,
                     read_word, read_block, in_range, is_mapped, get_regs,
                     set_regs, step, close
cortexm0   missing 0
riscv32    missing 2
i8086      missing 5
avr        missing 10   -- everything but step and close
```

**Root cause.** `Core` was never "what a core provides". It was the
Armv6-M-shaped subset two flat-address 32-bit machines happen to share. The AVR
does not diverge on entry; it diverges on **what an address is** (two
overlapping spaces) and **what a register file is** —
`set_regs([0]*13 + [sp, 0, entry], apsr=0)` is the Armv6-M layout written out.

**Fix.** Split on divergence: `core/<core>/machine.py`, resolved the way
`listing_view` already resolved `core.<core>.disasm`.

**Generalization.** *A handoff names the symptom it could see; measure before
you adopt its framing.* Any of the three candidates would have produced a board
file that satisfied the contract and still could not be entered — the same
claim-you-cannot-keep failure, through a third door.

### 3.2 A browser found `pc 0x[object Object]` with zero console errors

**Symptom.** The run report read `XIAO-RP2040-DIP: 200,000 instructions.
pc 0x[object Object]`. **No console error.** Every test passed.

**Root cause.** The board wire changed from positional registers to
`[{name, value, width}]`. Two places indexed position 15; one was updated.
`emulator.js`'s `runLoadedBoard` still did `state.registers[15].toString(16)` —
and indexing an array of objects is perfectly legal JavaScript, so nothing threw.

**Fix.** Read `$("where")` back, which `renderBoardState` already set from the
machine's own `pc` register. Pinned by
`test_nothing_in_the_script_indexes_a_board_register_by_position`.

**Generalization.** *A wire-shape change breaks JavaScript silently, because
JavaScript has no shape.* The static tripwire is the only cheap defence; the
browser is the only thing that finds the first one.

### 3.3 `ACCOUNTED` was a tolerance, not an assertion — twice

**Symptom.** In OH-54, mutating the RVC decoder to make `c.fldsp` *decode* left
the 49,152-encoding sweep green. In OH-56, reversing the `fence` `pred`/`succ`
bit order left all three disassembler sweeps green.

**Root cause, both times.** The sweep asked only "did objdump decode something
this core refused". A core that **wrongly decodes** an accounted encoding agrees
with objdump perfectly. The allowance was doing a check's job.

The fence case is worse and worth remembering: every fence in the sweeps has
non-zero `rd`/`rs1`, objdump refuses to render those, and `ACCOUNTED_MINE`
excused the whole mnemonic — so its operands were **never compared at all**.

**Fix.** `test_the_encodings_this_part_has_no_hardware_for_are_actually_refused`
asserts the accounted classes positively, and two direct fence tests assert the
orderings — one against a transcribed table, one against objdump itself, so a
transcription cannot be wrong in the same direction twice.

**Generalization.** *An accounting entry that excuses a whole mnemonic excuses
its bugs with it.* Every tolerance list needs a matching assertion in the
opposite direction, or it is a hole shaped exactly like the thing it excuses.

### 3.4 8,192 failures that were one harness bug

**Symptom.** The RVC operand check reported 8,192 failures across `c.jal`,
`c.j`, `c.beqz` and `c.bnez` — all four pc-relative classes at once.

**Root cause.** objdump prints a branch target as an **absolute address inside
the swept blob**, not as a displacement. I read it as a displacement.

**Fix.** Carry each encoding's own address through and subtract.

**Generalization.** *Four independent classes failing together is the shape of a
harness bug, not four bugs.* A large round failure count should make you suspect
the measuring instrument first. This is now written into the header of
`tests/riscv32/test_rvc.py` so the next person suspects it too.

### 3.5 objdump re-syncs on halfwords, which breaks line-for-line comparison

**Symptom.** The 32-bit disassembler sweep reported divergences like
`objdump '0x9f0031009f', this module '0x31009f'` — both refusing, different hex.

**Root cause.** When objdump cannot decode a word it **re-syncs on halfwords**:

```
   0:	009f 0000 000f      	0xf0000009f      <- one six-byte blob
   6:	0000                	c.unimp
   8:	02311093          	slli	ra,sp,0x23
```

Three words become one line. Zipping two disassemblers' output therefore drifts
the moment either meets something it does not know — which is exactly the region
a sweep exists to cover.

**Fix.** `render()` returns a dict **keyed by address**, and an address objdump
emitted no line for is treated as a refusal.

**Generalization.** *Two linear disassemblers do not agree on stride.* Compare by
address, never by position.

### 3.6 The ESP32-C3 board never said which part it was

**Symptom.** `api.load_firmware('XIAO-ESP32-C3-DIP', blink, base=0x42000000)`
loaded, then stopped after **one** instruction:

```
pc=0x42000004: encoding 0x1141531c is illegal for extensions 0x0
```

**Root cause.** `install(cpu)` mapped memory and registers and never called
`set_extensions`. The core had none, so it refused the first compressed
instruction. Unit tests all passed — they configure the core themselves.

**Fix.** The board declares `ISA = "RV32IMC"` and the core translates via a new
`abi.Cpu.set_isa`. Letters are a datasheet fact and belong in the board; the
letters-to-bits map is an ABI fact and belongs in the core. `set_isa` **refuses**
a letter it cannot represent rather than dropping it.

**Generalization.** *A board description is not finished when it maps memory.*
Anything the core cannot guess is the board's to say — and an extension silently
dropped makes a part look like one it is not.

### 3.7 The image had no stack pointer, and then `_start` was not first

**Symptom.** After 3.6, the blink faulted on its first store.

**Root cause.** An Armv6-M part loads SP from its vector table. **An RV32 part
does not** — `crt0` sets it, and a `-nostartfiles` build has no crt0.

**Fix, and where it belongs.** In the *image*, not the board: `blink.c` gained a
`_start` doing the one thing the missing crt0 would have done. A board inventing
a stack pointer would hide an image that never set one up.

**Then a second defect the fix exposed.** Without a linker script, the linker
placed `main` first and `_start` after it, so the stack setup was **silently
skipped** — an image that links cleanly and runs the wrong instruction first.
`blink.ld` now `KEEP`s `.text.start` first, and
`test_the_image_begins_with_its_startup_and_not_with_main` asserts the first
instruction is a `LUI` into `sp`.

**Generalization.** *Section order is not guaranteed without a script*, and an
entry point that is merely *present* is not an entry point.

### 3.8 Implementing an instruction silently removes test coverage

**Symptom.** After OH-55 implemented M, `test_an_instruction_this_core_has_not_
written_stops_the_run_and_says_so` **passed** — with `agreed=4, stopped=None`.
An assertion about stopping, with nothing left to stop on.

**Root cause.** Two tests used `mul` as their stand-in for "an encoding this
core does not implement". Implementing it made them vacuous rather than red.

**Fix.** `test_a_refused_step_leaves_the_processor_completely_untouched` uses
`ecall`; the lockstep test uses a new `encode.fence_i()`. `encode.mul`'s
docstring no longer advertises itself as an encoding this core refuses.

**Generalization.** *Filling a gap removes coverage from every test that used
the gap as an example.* Those tests do not fail — they pass vacuously. Both were
caught here only because they asserted something specific about **stopping**.

### 3.9 A pytest autouse fixture wiped my fixture, silently

**Symptom.** 14 of 20 new MMIO tests failed, including
`assert cpu.is_mapped(GPIO_OUT)` returning False immediately after mapping it.

**Root cause.** `tests/riscv32/conftest.py` has
`@pytest.fixture(autouse=True) def _fresh_board(cpu)` which calls
`clear_regions()`. A module-level fixture **named `cpu`** is set up first and
then wiped before the test body runs.

**Fix.** Name it `gpio` and take `cpu` as a parameter, which orders it after the
reset.

**Generalization.** *Shadowing a conftest fixture that an autouse fixture
depends on inverts the setup order.* Depend on it, do not replace it.

### 3.10 Dead code found by mutation, in the honest direction

**Symptom.** Mutating `c.srli`/`c.srai` to stop refusing RV64 shift amounts left
every test green.

**Root cause.** Not a weak test. A shift amount of 32 or more puts a one into
`imm[5]`, which is `funct7`'s low bit, and the 32-bit shift already refuses any
nonzero funct7 for exactly that reason. **No input could tell the difference.**

**Fix.** Deleted the redundant checks; pinned the *behaviour* with
`test_a_compressed_shift_of_thirty_two_or_more_is_refused`; then verified the
pin by mutating the **32-bit** gate instead and watching it catch.

**Generalization.** *When a mutation survives, ask whether any input could tell
the difference before assuming the test is weak.* Here the answer was no, which
makes it dead code — but deleting the code must not delete the guarantee.

---

## 4. Reproduce the result, cold

```bash
cd Code/Github/OpenHardware
git log --oneline -1                      # -> 7b623d5

# 1. Build all four cores.
python tools/build_core.py
#    -> avr.dll 96256 · cortexm0.dll 222208 · i8086.dll 129024 · riscv32.dll 146432

# 2. The gate.
python -m pytest -q                       # -> 1250 passed, 17 skipped (~5 min)
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_ticket_claims check_board_claims; do
  python -m tools.$c; done                # -> all exit 0

# 3. The new work, individually.
python -m pytest tests/riscv32/ -q        # -> 126 passed
python -m pytest tests/avr/ -q            # -> 32 passed

# 4. The board catalogue.
python -c "from webui.boards import catalogue; c=catalogue.catalogue(); \
print(len(c),'boards |',sum(1 for b in c if b.runnable),'runnable')"
#    -> 26 boards | 8 runnable
```

### Driving the ESP32-C3 in the browser

**Kill every listener first** — §9. This trap fired twice more this session.

```bash
netstat -ano | grep ":8088" | grep LISTENING | awk '{print $5}' | sort -u \
  | while read pid; do taskkill //PID $pid //F; done
netstat -ano | grep ":8088" | grep -c LISTENING     # -> 0
python webui/emulator_server.py                     # -> OpenHardware on http://127.0.0.1:8088/
```

On the **Emulator** tab: pick `XIAO-ESP32-C3-DIP`, choose
`tests/riscv32/c3blink/blink.bin`, base `0x42000000`, Load, Run.

Expect `pc 0x42000028`, 33 registers with RISC-V ABI names, `sp` `3FCDFFE0`,
**zero flags** (correct — RV32 has no condition codes), and a listing whose
first lines after Load are the image's own `_start`:

```
42000000  3fce0137  lui sp,0x3fce0
42000004  1141      c.addi sp,-16
42000006  0040006f  jal zero,0x4200000a
```

### Rebuilding the ESP32-C3 blink

`blink.bin` is 52 bytes and committed.
`test_the_committed_binary_matches_its_source` rebuilds and compares it.
**The linker script is not optional** — see §3.7.

```bash
RV=~/.platformio/packages/toolchain-riscv32-esp/bin
"$RV/riscv32-esp-elf-gcc.exe" -march=rv32imc -mabi=ilp32 -Os -ffreestanding \
  -nostdlib -nostartfiles -T tests/riscv32/c3blink/blink.ld \
  -o /tmp/c3.elf tests/riscv32/c3blink/blink.c
"$RV/riscv32-esp-elf-objcopy.exe" -O binary /tmp/c3.elf tests/riscv32/c3blink/blink.bin
```

---

## 5. File inventory

### New this session

| File | Bytes | What |
|---|---|---|
| `core/cortexm0/machine.py` | 13,072 | Armv6-M power-on and register file, moved out of `api.py` |
| `core/avr/machine.py` | 13,747 | The same for a Harvard machine; **exists to prove the interface is not Arm-specific** |
| `core/riscv32/machine.py` | 9,762 | The third, and the one showing the interface was not shaped around the first two |
| `core/riscv32/disasm.py` | 17,841 | RV32I + M + C + Zba + Zbs as text |
| `webui/boards/atmega328p.py` | 7,115 | Two sized address spaces; the whole board |
| `webui/boards/esp32c3.py` | 11,007 | Regions, GPIO with W1TS/W1TC, and the ISA string |
| `tests/riscv32/test_rvc.py` | 25,313 | The 49,152-encoding sweep + the real blink |
| `tests/riscv32/test_disasm.py` | 19,487 | Three sweeps, ~110k encodings |
| `tests/riscv32/test_mmio.py` | 11,878 | 20 tests; sub-word access through executed `sb`/`lbu`/`sh` |
| `tests/riscv32/test_rv32m.py` | 7,437 | 14 tests; the six defined division edges |
| `tests/riscv32/test_esp32c3_board.py` | 14,116 | 13 tests; **the evidence for ESP32-C3** |
| `tests/avr/test_uno_board.py` | 15,858 | 14 tests; **the evidence for ATmega328P** |
| `tests/riscv32/c3blink/blink.c` | 2,822 | Bare-metal C3 blink with its own `_start` |
| `tests/riscv32/c3blink/blink.ld` | 1,078 | **Not optional** — see §3.7 |
| `tests/riscv32/c3blink/blink.bin` | **52** | Committed |

### Modified

`webui/api.py` (the `Core` protocol shrank from 12 methods to 2),
`webui/boards/contract.py`, `webui/boards/catalogue.py`,
`core/riscv32/{cpu.h,cpu.cc,exec.cc,abi.h,abi.cc,abi.py}` (**ABI v1 → v2**),
`webui/static/emulator.{html,js}`, `webui/emulator_server.py`,
and six test files whose tripwires fired.

---

## 6. Open work, highest priority first

### 6.1 OH-57 — ESP32-C5 and C6 board descriptions — *software-only, START HERE*

**The last four boards of the seven-board unlock**, and the only one of these
items that is not blocked on an oracle. `webui/boards/esp32c3.py` is the model
to copy.

**FIRST OBSTACLE, measured 2026-08-25: the vendor headers for these two parts
are not installed.** `framework-arduinoespressif32/tools/sdk/` holds exactly

```
esp32/  esp32c3/  esp32s2/  esp32s3/  versions.txt
```

— no `esp32c6`, no `esp32c5`. Every address in `webui/boards/esp32c3.py` is
cited to `soc.h` and `gpio_reg.h` line numbers in that tree, and this repository
does not accept remembered numbers. So step one is fetching a framework version
that carries them (`pio pkg install -g -t framework-arduinoespressif32@<ver>`,
the route the AVR and SAMD21 toolchains came in by), **or** finding another
citable source. Do not start by writing the board file.

Whether Arduino's framework ships an ESP32-C5 tree at all is unknown and worth
checking early — it is a newer part, and if it does not, the C5 half of this
ticket is blocked on a source rather than on effort.

**Three things are already known and must not be rediscovered:**

**(a) Describing the C6 kills a test's only example, and another board name will
not fix it.** `tests/webui/test_board_run.py`'s
`test_each_refusal_arrives_as_itself` needs a board that is *core-built and
undescribed* to produce `409 chip-not-described`. It used the C3 until OH-48,
and now uses `XIAO-ESP32-C6-DIP` with a comment saying so. After OH-57 there is
**no such board left** — every remaining chip needs a core that is not built, so
they all give `core-not-built` instead. The fix is the synthetic-directory
treatment `test_a_built_core_without_a_board_description_is_not_runnable`
already uses (`tmp_path` with a hand-written board JSON), not a third board name.

**(b) The C5's firmware claim must be withheld on evidence.**
`catalogue.CHIPS` records:

```
ESP32-C3  RV32IMC
ESP32-C6  RV32IMAC
ESP32-C5  RV32IMAC + Zcb/Zcmp/Zcmt
```

The C6 adds **A**, which `core/riscv32/cpu.h` classifies and *refuses*. The C5
adds A plus **Zcb, Zcmp and Zcmt**, none of which this core implements:
`tests/rv32/conftest.py`'s `MODELLED` is `{"M", "A", "C", "Zba", "Zbs"}` and
does not mention Zcmt at all, and its `TARGETS` table has **no ESP32-C5 entry**.
So:

- The **C6** is reachable. Verified this session: `set_isa("RV32IMAC")` is
  accepted and yields `abi.ESP32_C6`. The core answers `Unimplemented` on any
  atomic, and a blink contains none — so a C6 blink should run and earn its
  claim.
- The **C5** must be *described* and its `FIRMWARE_VERIFIED` entry **withheld**
  until Zcb/Zcmp/Zcmt exist. `set_isa` will also **raise** on its ISA string,
  by design: it refuses a letter it cannot represent rather than dropping it,
  so the board cannot quietly be configured as something it is not. Describing
  a board is not claiming it runs firmware; `rules/board-claims.md` governs the
  second, and `test_only_the_board_a_real_image_ran_on_claims_to_have_run_one`
  pins the set to `{"RP2040", "SAMD21", "ATmega328P", "ESP32-C3"}` — edit it
  deliberately.

**(c) `TARGETS` and `MODELLED` in `tests/rv32/conftest.py` are two spellings of
one fact**, and `test_the_extension_letters_match_the_abi_bitmasks` fails if one
moves without the other. Adding a C5 row means touching both. Read the failure
rather than working around it — it prints both values.

Done when the C6 and C5 report runnable, each states which of its ISA this core
executes, and any firmware claim names a test that watched a real image.

### 6.2 OH-50 — a Cortex-M4 core — *software-only, no oracle here*

Two nRF52840 boards. Armv7E-M is a superset of the working Armv6-M, so it starts
from code that works. **QEMU is not installed**, so the interpreter cannot be
lockstepped. The *decode* can be swept against objdump the way §3.5 describes.

### 6.3 OH-36 — a Cortex-M33 core — *blocked on oracle*

Eight boards, the biggest single unlock, worst evidence situation. Held by
another session (`agent-oh36`).

### 6.4 OH-38 — do not build Xtensa — *decided, and re-confirmed*

Three ESP32-S3 boards. Both apparent oracles derive from the same Tensilica
archive, so agreement between them is a tautology. Re-raised and re-refused this
session; see §9.

### 6.5 Residuals

1. **`sh1add`/`bset` are rendered by `disasm.py` but objdump's default `rv32`
   refuses them** — Zba and Zbs are absent from its target. Accounted in
   `ACCOUNTED_MINE`. If a future objdump knows them, those entries become dead.
2. **`core/riscv32` has no `map_constant`, `map_stream` or `map_counter`** —
   deliberately. They arrive when an image faults without them, which is the
   growth rule `webui/boards/rp2040.py` states.
3. **`PYI034` on `__enter__` in all four cores.** Known, recorded, ignored.
   `ruff` is not adopted here.
4. **`tests/rv32/test_gating.py` has two pre-existing ruff findings** (`I001`,
   `F401` on `SANDBOX`). Confirmed pre-existing by stashing; not mine to fix.

---

## 7. Commits this session

```
7b623d5 chore(tickets): close OH-56
bb4676f feat(riscv32): a disassembler, so an ESP32 board gets its fourth pane
c6bc8c3 chore(tickets): close OH-48
3ccfe87 feat(boards): an ESP32-C3 that runs a real image, unlocking three boards
4e4c5e2 chore(tickets): close OH-47
8695433 feat(riscv32): memory-mapped registers, and a machine module so a board can load
d1c155a chore(tickets): close OH-55
99d5b1b feat(riscv32): multiply and divide, and the six answers RISC-V defines
ec8b2ac chore(tickets): close OH-54
d5f1ab9 feat(riscv32): compressed instructions, and a real ESP32-C3 image that runs
25f477f docs(tickets): the ESP32-C series programme, and what actually blocks it
705be28 chore(tickets): close OH-52 and OH-53
e76b5fb fix(webui): the page is called OpenHardware, because it is not an i8086
42126c0 feat(boards): ask the core how a machine powers on, and the Arduino Uno runs
```

Tickets filed: OH-52 … OH-57. Closed: OH-44, OH-47, OH-48, OH-49, OH-52 … OH-56.
**OH-49 was closed as *superseded*, not as done** — its Done-when was never met,
and its note says so.

---

## 8. Visual output verification

Checked in a real browser via Playwright, with the listener count verified as 1
first. **0 console messages at warning level or above on every check.**

**Page identity.** Title `OpenHardware`, brand `OpenHardware — cores and
boards`, favicon `OH`, `Server: OpenHardware`.

**Board picker.** 26 boards, **8 enabled**: Arduino Uno, three XIAO-ESP32-C3,
two XIAO-RP2040, two XIAO-SAMD21.

**Arduino Uno**, `tests/avr/blink/blink.bin` at base 0: `pc 0x000D`,
**34 registers** (r0–r31 two hex digits, `sp`/`pc` four), **8 SREG flags** with H
set, hexdump of the **data** space showing `00010  00 00 20 00 00 00 00 00 11 00
00 00 FB 08 00 00` — r18=0x20, r24=0x11, Y=0x08FB, which are exactly the
registers the blink uses. Listing pane says `core.avr.disasm does not exist`.

**XIAO-ESP32-C3-DIP**, `tests/riscv32/c3blink/blink.bin` at `0x42000000`:
`pc 0x42000028`, **33 registers** with ABI names, `sp 3FCDFFE0`, **zero flags**,
and the listing below. Widths interleave 4, 2, 4 — the property §3.7's linker
script protects.

```
> 42000028  fef6eae3  bltu a3,a5,0x4200001c     <- current
  4200002C  47b2      c.lwsp a5,12(sp)
  4200002E  0785      c.addi a5,1
  42000030  c63e      c.swsp a5,12(sp)
  42000032  bfd5      c.j 0x42000026
```

That is the `for (volatile unsigned int i = 0; i < 100; i++)` delay loop,
disassembled out of a running board.

**XIAO-RP2040-DIP** re-checked as a regression: `pc 0x1000012E` and the same
four `busy_wait_us` listing lines as the previous handoff's §8, byte for byte.

---

## 9. Known limitations and traps

- **`pkill -f` does not work in Git Bash here, and the stale-server trap fired
  twice more this session.** Once it answered `Server: OpenHardware-i8086` from
  *before* the rename, which reads exactly like the rename not working. **Always
  count listeners before trusting the page**, with the loop in §4.
- **An in-review ticket owns its paths exactly as an open one does.** OH-44 was
  `in-review` with its work committed and no live holder, and held
  `core/riscv32/**`; it was closed with a note before this session's work began.
- **objdump decodes a *different* architecture, in both directions.** Wider: F,
  D, Q. **Narrower: Zba and Zbs**, which its default `rv32` does not know at all.
  The previous handoff recorded only the wider direction.
- **objdump re-syncs on halfwords.** §3.5. Compare by address.
- **objdump appends `# 0x...`** when a base register is `zero`. 522 lines of the
  field sweep differed by only that.
- **A mutation that does not change the file proves nothing.** The driver in
  `tests/` style used here asserts the file changed before running.
- **An ESP-IDF application will not run on any board here.** The ESP32-C3 resets
  into 384 KB of Espressif mask ROM that is not redistributable. Bare-metal
  images run. `docs/architectures.md` records that PICSimLab's own ESP route
  runs the vendor's QEMU rather than modelling the ISA.
- **`GPIO_IN` on the C3 and `PINB` on the Uno are not modelled.** The C3's is
  *unmapped so a read faults*; the AVR's cannot be, because a data space has no
  holes, so it returns a wrong zero and is pinned as a limitation by
  `test_reading_the_input_register_is_not_yet_modelled`.
- **SRAM's instruction-bus alias at `0x4037C000` is not mapped**, because
  `add_region` cannot express an alias and two arrays that must agree will not.
- **`described_chips()` counted `contract.py` as a board** until this session and
  returned a phantom chip `CONTRACT`. Both lists of non-board modules are now
  pinned together by `test_the_two_lists_of_non_boards_agree`.
- **Do not add `@pytest.mark.parametrize`.** `tools/inventory.py` counts
  `def test_*` with `ast`. Loop inside one test.
