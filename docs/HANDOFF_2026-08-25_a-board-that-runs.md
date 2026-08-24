# Handoff — a board that actually runs

| | |
|---|---|
| **Date** | 2026-08-25 |
| **Repo** | `Alexyodude/OpenHardware` — not a fork, MIT |
| **Branch / HEAD** | `master` @ `37218f3`. **Working tree NOT clean — see §3.1 before you commit anything** |
| **Previous handoff** | `docs/HANDOFF_2026-08-24_boards-firmware-and-the-armv6m-oracle.md`. Where they disagree, this one is newer |
| **Toolchain** | MSVC 19.44; Node 24.11.1; Python 3.13; **arm-none-eabi GCC** under `~/.platformio/packages/toolchain-gccarmnoneeabi/`; PlatformIO 6.1.19 (not on PATH) |
| **Oracle** | rp2040js at `../rp2040js`, built (`dist/cjs/rp2040.js`). Clone+build recipe in §4 |
| **Cores built** | `build/lib/cortexm0.dll` 148,480 B · `build/lib/i8086.dll` 129,024 B |
| **Gate** | 789 passed, 17 skipped; all seven checkers exit 0 |

---

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| An emulated board runs a real compiled image | **ACHIEVED** | `tests/cortexm0/test_blink.py`, 8 tests; 45 LED transitions at a constant 453-instruction period |
| Full 16-bit Thumb (formats 1–19) | **ACHIEVED** | `core/cortexm0/exec.cc`; 100,000/100,000 instructions matched rp2040js on a real Arduino image |
| The core owns no chip addresses | **ACHIEVED** | `cpu.h` has none; `test_the_same_core_serves_a_board_with_a_different_memory_map` runs a SAMD21-shaped map |
| RESETS with atomic SET/CLR/XOR aliases | **ACHIEVED** | `webui/boards/rp2040.py`; 10 tests in `test_board_rp2040.py` |
| SIO GPIO, write-only semantics correct | **ACHIEVED** | `GPIO_OUT_SET` reads 0, bus aliases read through; 4 tests pin both sides |
| Per-board status, generated | **ACHIEVED** | `webui/boards/catalogue.py`; 26 boards, 2 runnable, backlog of 7 rows by core |
| Architect review | **APPROVED** | 3 rounds: REJECTED → REJECTED → APPROVED. 10 findings, all real, all repaired |
| **The Arduino/pico-sdk image runs** | **BLOCKED ON the RP2040 boot ROM** | Stops at instruction 225,759, PC 0x0. ROM is not MIT-redistributable — §3.4 |
| **24 of 26 boards** | **NOT STARTED** | Five instruction sets with no core. Ordered backlog in §6 |
| Working tree clean at handoff | **NO** | Another session's files are modified. §3.1 |

---

## 2. What changed, in one paragraph each

**The Cortex-M0+ core grew from arithmetic to a processor.** Formats 1–4 were
register-only ALU ops; formats 5–19 add loads, stores, branches, the stack, the
high registers, `BL`, `STM`/`LDM`, sign-extend/byte-reverse and the hint space.
That is the difference between passing a corpus and running a program.

**The memory map moved out of the core.** `cpu.h` held flash at `0x10000000`
and SRAM at `0x20000000` as `constexpr`. Memory now exists only because a board
called `add_region`, so a core with no board faults on its first fetch.

**A board layer exists.** `webui/boards/rp2040.py` holds every RP2040 address:
its two memory regions, a non-executable boot ROM stub, RESETS with the atomic
alias windows, and SIO's GPIO registers.

**A real compiled blink runs.** `tests/cortexm0/blink/blink.c`, built by
arm-none-eabi-gcc for cortex-m0plus, unresets IO_BANK0, waits on `RESET_DONE`,
enables an output and toggles GP25.

**`tools/lockstep_armv6m.mjs` runs real firmware against rp2040js**, comparing
all 16 registers and the flags after every instruction, and can profile which
peripherals an image touches.

**The Boards view reports all 26 boards**, computed, with a backlog ordered by
boards unlocked and costed by the oracle each missing core would need.

---

## 3. Root-cause narratives

### 3.1 I committed another session's work — READ THIS FIRST

**Symptom.** At handoff time `git status` showed two modified files I never
touched: `tools/inventory.py` and `docs/tickets/OH-37-*.md`. Then sixteen
tickets, `OH-23` through `OH-37`, none of which I created.

**Wrong hypothesis, ruled out fast.** "A hook generated them" — no. `git log
-- docs/tickets/OH-37-*.md` names `d11c0ac`, one of *my* commits.

**Root cause.** I used `git add -A` while **another session was working in this
repository**. `python tools/tickets.py whoami` reports that session's pointer
as `OH-27`; mine were `OH-21` and `OH-22`. Its in-progress ticket files were
swept into two of my commits:

```
1ad249c  5 ticket files (OH-23..OH-27)   — commit message describes chip-name parsing
d11c0ac  9 ticket files (OH-28..OH-37)   — commit message describes write-only registers
```

**What I did NOT do.** I did not unpick it. Those tickets are legitimate work
and rewriting history to extract them risks destroying it. I also left the two
currently-modified files alone — they are that session's uncommitted work and
are **not** mine to commit.

**Fix, for the next session:** before committing, run `git status` and stage by
path. `git add -A` is unsafe in this repository *by design* —
`rules/ticket-claims.md` exists precisely because more than one session works
here at once.

```bash
python tools/tickets.py whoami     # who else is holding what
git add core/cortexm0 tests/cortexm0 webui/boards   # name paths, never -A
```

**Generalization.** *A repository with a coordination rule has that rule
because the failure it prevents is real.* This one has `tools/ticket_guard.py`,
`tools/check_ticket_claims.py` and a whole rules file about concurrent
sessions, and I still reached for the convenient command. The guard only covers
`Edit`/`Write`, not `git add`.

### 3.2 The core claimed to hold no chip addresses, and held four

**Symptom.** None. Every test passed. The PRD's evidence line said the core was
architecture-only.

**Root cause.** `cpu.h` held `kFlashBase`, `kFlashSize`, `kSramBase`,
`kSramSize` as `constexpr`, under a comment asserting *"every Armv6-M part this
project targets has them at the same addresses"*. That is false: **the SAMD21
shares this core and puts flash at `0x00000000`**, and the SAMD21 is the board
the catalogue names as proof one core serves several boards.

**How the verification failed.** I grepped for `RESETS|SIO|0x4000|0xd000` —
terms that cannot match `0x10000000` or `kSramBase`. My own evidence was scoped
to exclude the thing that would have falsified the claim.

**Fix.** `cpu.cc` `Cpu::Cpu() = default`; `regions_` is the only storage.
Proven by `test_the_same_core_serves_a_board_with_a_different_memory_map`,
which builds a SAMD21-shaped map and executes from flash at zero.

**Generalization.** *Verifying your own claim with a search you choose is not
verification.* Ask what evidence would falsify the claim, then look for that.

### 3.3 Zero-filled flash executed 5,000 instructions without a fault

**Symptom.** Measured by the reviewer, not by me:

```
jump into untouched flash -> 5,000 instructions, no fault
```

**Root cause.** Regions were zero-filled, and `0x0000` is a valid Thumb
encoding — `MOVS r0, r0`. So a program running past its own image executed
no-ops indefinitely and looked like progress. This is verbatim the accident the
file's own header says the design exists to prevent; the boot ROM's 16 KB was
defended while 2 MB of flash was open.

**Fix.** `add_region` takes a `fill` byte and flash uses `0xFF`.

```
jump into untouched flash -> no implementation for the encoding at 0x10100000
```

**The part worth keeping:** `0xFF` is what erased flash reads on a real part,
*and* `0xFFFF` is not a valid Thumb encoding. **The hardware-truthful answer and
the loud answer are the same answer** — no invented guard was needed.

**Generalization.** *When tempted to invent a safety value, check what the
hardware actually does first.* Also: `clear_memory` had to refill to
`region.fill` rather than zero, or the guard silently un-installs itself.

### 3.4 The Arduino image stops at a boot ROM, and the oracle pretends it does not

**Symptom.** `.pio/build/pico/firmware.uf2` runs 225,759 instructions
standalone and then faults fetching at `0x00000000`.

**Root cause.** RP2040 firmware calls `rom_func_lookup`, reading a function
table from the boot ROM. This project ships a zero-filled stub, so the lookup
returns 0 and the firmware calls it. The real ROM contains `mufplib`, licensed
for use *"solely on a Raspberry Pi RP2040 device"* or GPL-2 — an emulator is
not that device, so the image is not MIT-redistributable.

**The measurement that matters.** rp2040js reaches **the same PC at the same
step**:

```
LEFT MEMORY at step 225759, PC 0x0 -- everything the oracle reports after this is fiction
```

and then warns and executes ~174,000 further instructions of unmapped memory,
because **rp2040js does not model faults**. The two models agree exactly; only
one says so.

**Fix.** None available in software. The stub is non-executable so the jump is
loud rather than silent, and `tests/cortexm0/blink/blink.c` is bare metal so it
never calls the ROM.

**Generalization.** *An oracle that cannot fail is not an oracle past the point
where it should have.* Compare against it only while it is still modelling.

### 3.5 A vacuous test hid a real bug

**Symptom.** `test_the_bootrom_fault_names_the_address_rather_than_the_region`
asserted `"0x00000000" in message`. `BOOTROM` is 0, and the message carries
*two* addresses — the faulting one and the instruction's — so the assertion was
satisfied by the wrong half.

**Root cause of the hidden bug.** Rewriting the test to probe `BOOTROM + 0x200`
and check both halves separately failed immediately: a non-executable fetch
recorded **no** fault address, because only a *failed read* sets one and an NX
fetch's read succeeds. Every jump into the stub reported whatever had faulted
last — zero, on a fresh board.

**Fix.** `note_fetch_fault(address)` takes the address. Added
`cortexm0_in_range` so the three fetch failures read differently:

```
fetch at 0x00000200 is in a region that is not executable (instruction at 0x00000200)
fetch at 0x40008000 is outside the modelled memory (instruction at 0x40008000)
```

**Generalization.** *A vacuous test does not merely fail to catch bugs — it
hides them.* Fixing this one found a live defect within minutes.

### 3.6 A write-only register is not an alias window

**Symptom.** `read_word(SIO + GPIO_OUT_SET)` returned `GPIO_OUT`. Hardware
reads 0.

**Why it was subtle.** Both are "an address whose write modifies another
register", so they write identically. They differ only on read, and the code
had one mechanism for both.

**Evidence.** rp2040js's SIO `readUint32` switch has no case for these offsets
(returns 0), while its bus path masks an aliased address back to the base
offset and returns the register. So both behaviours are confirmed against the
oracle, and they genuinely differ.

**Fix.** `map_alias(..., readable=False)`. Four tests pin both sides: removing
`readable=False` fails two, making *every* alias unreadable fails two others.

**Generalization.** *This was the only residual that answered wrongly rather
than loudly*, which is the class this project treats as worst. A missing
feature that faults costs an hour; a wrong value a driver acts on costs a day.

### 3.7 A chip that merely starts with another chip's name

**Symptom.** `chip_for("XIAO-ESP32-C61-DIP")` returned `ESP32-C6`. The ESP32-C61
is a real Espressif part.

**Root cause.** `rest.lower().startswith(chip.lower())` with no delimiter
check. Same failure class as the earlier `ESP32-C3-DIP` bug the rule had been
rewritten to fix — and the docstring claimed *"matching against CHIPS cannot do
that"*. It could.

**Fix.** The chip must end at a `-` or at the end of the name. Four tests: three
near-misses that must raise, one covering the four awkward real shapes that must
keep working.

### 3.8 The route the whole view depends on had no test

**Symptom.** The Boards panel rendered empty with
`ERR_EMPTY_RESPONSE @ /api/boards`, while **340 tests passed**.

**Root cause.** `missing_cores` changed from a dict to a list; the server kept
calling `.items()`. Nothing between the catalogue and the browser was tested.

**Fix.** Three route tests: it answers, it is `json.dumps`-able, and it carries
every field `emulator.js` reads by name.

**Generalization.** *The seam between a generator and its consumer is where
untested code lives.* The catalogue had 25 tests; the route serving it had none.
This is the second time this repo has needed a browser to find what a green
suite hid.

---

## 4. Reproduce the result, cold

```bash
cd Code/Github/OpenHardware
git log --oneline -1                      # -> 37218f3

# 1. Build both cores.
python tools/build_core.py
#    -> build/lib/cortexm0.dll  (148480 bytes)
#    -> build/lib/i8086.dll     (129024 bytes)

# 2. The gate.
python -m pytest -q                       # -> 789 passed, 17 skipped (~4-5 min)
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_ticket_claims; do
  python -m tools.$c; done                # -> all OK

# 3. The board that runs.
python -m pytest tests/cortexm0/test_blink.py -q   # -> 8 passed

# 4. The UI. Boards tab shows 26 rows, 2 reading RUNS FIRMWARE.
python webui/emulator_server.py           # http://127.0.0.1:8088/
```

### Rebuilding the blink image

Only needed if `blink.c` changes; `blink.bin` (76 B) is committed so the suite
runs without a toolchain, and `test_the_committed_binary_matches_its_source`
rebuilds and byte-compares wherever a compiler exists.

```bash
GCC=~/.platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi-gcc.exe
"$GCC" -mcpu=cortex-m0plus -mthumb -Os -ffreestanding -nostdlib \
  -T tests/cortexm0/blink/blink.ld -o /tmp/blink.elf tests/cortexm0/blink/blink.c
"${GCC%gcc.exe}objcopy.exe" -O binary /tmp/blink.elf tests/cortexm0/blink/blink.bin
```

### The oracle, and running real firmware against it

```bash
git clone https://github.com/wokwi/rp2040js ../rp2040js
(cd ../rp2040js && npm install && npm run build)     # needs dist/cjs/rp2040.js

node tools/gen_armv6m_tests.mjs --count 500          # 13,500 corpus cases
node tools/lockstep_armv6m.mjs --image <fw.uf2> --profile-peripherals
node tools/lockstep_armv6m.mjs --image <fw.uf2> --limit 400000
#    -> LEFT MEMORY at step 225759, PC 0x0
```

Without rp2040js both tools **exit 3 and say SKIPPED**; they never emit an empty
corpus and report success.

### Rebuilding the PlatformIO fixtures

Recipe is in the previous handoff §4, **as corrected there** — the original
did not compile (`src/main.cpp` needs `#include <Arduino.h>`, and the XIAO
ESP32-C3 defines no `LED_BUILTIN`).

---

## 5. File inventory

### New this session

| File | Bytes | What |
|---|---|---|
| `core/cortexm0/exec.cc` | 29,962 | Thumb formats 1–19 |
| `core/cortexm0/cpu.h` | 15,610 | Registers, flags, regions, MMIO. **No chip addresses** |
| `core/cortexm0/cpu.cc` | 10,827 | Regions, aliases, mirrors, fault recording |
| `core/cortexm0/abi.py` | 15,305 | ctypes binding, ABI v10 |
| `core/cortexm0/abi.h` / `.cc` | 7,203 / 4,780 | The C surface |
| `core/cortexm0/shift.cc` / `.h` | 3,855 / 2,600 | Shift carry rules and `add_with_carry` |
| `webui/boards/rp2040.py` | 10,373 | The RP2040: regions, boot ROM stub, RESETS, SIO |
| `webui/boards/catalogue.py` | 13,352 | Per-board status, computed |
| `tools/lockstep_armv6m.mjs` | 11,334 | Real firmware vs rp2040js; peripheral profiler |
| `tools/import_firmware.py` | 21,038 | Build-artefact discovery (from the earlier §6.1 item) |
| `tests/cortexm0/test_blink.py` | 7,348 | **The board that runs.** 8 tests |
| `tests/cortexm0/test_board_rp2040.py` | 12,816 | 30 tests on the board's registers |
| `tests/cortexm0/blink/blink.c` | 1,583 | Bare-metal blink source |
| `tests/cortexm0/blink/blink.bin` | 76 | Committed image, rebuilt-and-compared by a test |

### Not mine — another session's, swept into my commits

`docs/tickets/OH-23-*.md` … `OH-37-*.md` (16 files). See §3.1.

---

## 6. Open work, highest priority first

### 6.1 A SAMD21 board description — *software-only, START HERE*

**The cheapest real win: it needs a description, not a core.** SAMD21 already
reports `core_built=True` in the catalogue, because it shares `cortexm0` with
the RP2040. It reads `NO BOARD DESCRIPTION` only because
`webui/boards/samd21.py` does not exist.

Write it as `webui/boards/samd21.py`, mirroring `rp2040.py`:

- `install_memory` — **flash at `0x00000000`** (256 KB on a SAMD21G18A), SRAM
  at `0x20000000` (32 KB). Fill flash `0xFF`. This is the map
  `test_the_same_core_serves_a_board_with_a_different_memory_map` already
  proves the core can take.
- `install_*` for the peripherals a blink needs: **PORT** (`0x41004400`) with
  `DIRSET`/`OUTSET`/`OUTCLR`/`OUTTGL` — note these are *write-only* registers
  like SIO's, so use `map_alias(..., readable=False)`.
- **PM/GCLK** only if a blink actually touches them — find out by measuring,
  not by guessing: write a bare-metal SAMD21 blink, run it, and add whatever
  the fault address names.

Then add `"SAMD21": "tests/cortexm0/test_samd21_blink.py"` to
`FIRMWARE_VERIFIED` **and** update
`test_only_the_board_a_real_image_ran_on_claims_to_have_run_one`, which pins
the set to `{"RP2040"}` on purpose — the two are coupled and the comment in
`catalogue.py` says so.

**Do not add an empty `samd21.py`.** It would flip two boards to
`CORE + BOARD, UNPROVEN` on the strength of a filename.

### 6.2 Adopt the peripheral layer, or decide against it — *needs a human*

`docs/research/peripheral-layer/` has verified regmaps for RP2040 (RESETS,
XOSC, PLL, CLOCKS, IO_BANK0, PADS_BANK0), ESP32-C3 and STM32C031, still marked
unadopted. `rp2040.py` adopted a hand-written slice of it. The question is
whether the schema-driven approach in `design.md` §6 earns its keep now that a
concrete board exists to compare against. **The other session appears to be
working this area (OH-33) — coordinate before starting.**

### 6.3 An RV32IMC core — *software-only, large*

Seven boards (ESP32-C3 ×3, C6 ×2, and C5 with Zc extensions). Oracle: Hazard3's
`rvcpp`, Apache-2.0, builds here with MSVC behind a 13-line shim — but it has
**no extension gating at all**, so it is right on the legal instruction space
and wrong at the illegal-instruction edge. The corpus generator would need to
avoid claiming anything about what the hardware refuses.

### 6.4 A Cortex-M33 core — *software-only, largest*

Eight boards (MG24 ×2, RP2350 ×2, nRF54 ×4) — the biggest single unlock and the
worst oracle situation: nothing free models Armv8-M security extensions, and
the RP2350's Hazard3 half needs a RISC-V core anyway.

### 6.5 Do not build an Xtensa core on current evidence — *decided*

Three boards (ESP32-S3). **No free independent oracle exists**: QEMU-xtensa and
binutils-xtensa both derive from the same Tensilica archive via
`import_core.sh`, so their agreement is a tautology
(`docs/architectures.md` §2.1c). Three boards is not worth a core nothing can
check.

### 6.6 Residual defects, both loud rather than silent

1. **MMIO is word-only.** `LDRB` from a mapped register faults. Fine until a
   UART needs byte access to its data register.
2. **`FIRMWARE_VERIFIED` is coupled to a test that pins its contents.** Both
   places say so; they must be edited together.

### 6.7 Unchanged from the previous handoff

OH-5 (trap flag), OH-11 (microcode-exact IMUL/DIV/IDIV), OH-8, OH-9, and the
four human-only questions in its §6.5 (Arm FVP licence, Nucleo ST-LINK
revision, UDB Docker pull, the `mufplib` question — now load-bearing, see §3.4).

---

## 7. Commits this session

```
37218f3 chore: close OH-21 and OH-22
f9113b0 refactor: the deslop pass, which found one real inefficiency
d11c0ac fix(boards): a write-only register is not an alias window
1ad249c fix(boards): a chip that merely starts with another chip's name is not it
aa4449d docs: record review round two
c522ba6 fix(boards): stop the badge claiming what only a test can earn
d16f1b8 docs(cortexm0): delete the comment that outlived the thing it described
8177274 docs: record the review that rejected the first attempt, and why it was right
cd9f8c8 fix(cortexm0): take the memory map out of the core, where it never belonged
1613ba9 fix(cortexm0): never answer zero, and stop saying SRAM when memory is meant
7de117c feat(boards): an emulated RP2040 that runs a real compiled blink
a722092 feat(cortexm0): a Cortex-M0+ core that runs real firmware
1722bca docs: record what landed, and fix a fixture recipe that did not compile
f892a50 feat(webui): select a target, and say which ones are actually runnable
7817732 feat(tools): find the firmware a project has already built
```

`1ad249c` and `d11c0ac` also contain another session's ticket files — §3.1.

---

## 8. Visual output verification

The Boards view was checked in a real browser via Playwright, not inferred.

**Boards panel:** 26 rows. Status counts: `RUNS FIRMWARE` 2 (both RP2040),
`NO BOARD DESCRIPTION` 2 (both SAMD21 — the case proving "built core" and
"runnable board" are different claims), `NO CORE` 22. Strip reads
`2 watched running firmware / 2 core and board exist / 24 not yet /
26 boards imported`.

**Backlog table:** 7 rows, ordered 8, 7, 3, 2, 2, 1, 1 — `cortexm33`,
`riscv32`, `xtensa`, `cortexm0`, `cortexm4`, `avr`, `unknown`. The `cortexm0`
row reads **BOARD DESCRIPTION** rather than **A CORE**, which is the distinction
between "write an instruction set" and "write a memory map".

**Layout:** `documentElement.scrollWidth` does not exceed `clientWidth` — no
horizontal overflow. **Console: 0 messages at warning level or above.**

An earlier check of this same panel found it rendering **empty** with one
console error — see §3.8. The console count above is what makes this section
worth writing.

---

## 9. Known limitations and traps

- **`git add -A` is unsafe in this repository.** Another session works here.
  §3.1.
- **A green suite is not a working page.** Twice now, browser checks have found
  what 340+ passing tests did not.
- **rp2040js does not model faults.** It warns and continues. Its instruction
  counts past the first bad fetch are fiction; `--profile-peripherals` reports
  where that point is.
- **The peripheral profiler must patch the *core's* bus methods, not the
  machine's.** Patching `rp2040.readUint32` caught 1 access in 200,000
  instructions and made busy firmware look idle.
- **SRAM is zero-filled and executable, deliberately.** Contents are undefined
  at power-on, the oracle answers zero, and a real Cortex-M0+ executes from
  RAM — so non-executable would be the worse lie. Reasoning is in
  `install_memory`'s docstring; do not "fix" it.
- **Regions refuse to overlap.** `rp2040.install()` needs `clear_regions()`
  first if anything else installed memory — the test fixture does exactly that.
- **Do not add `@pytest.mark.parametrize`.** `tools/inventory.py` counts
  `def test_*` with `ast` and `test_ast_count_matches_pytest_collection` fails
  on the divergence. Loop inside one test.
- **`ruff` is not adopted here.** One advisory remains on both cores'
  `__enter__` (`PYI034`); `core/i8086/abi.py` has the identical one.
- **The corpus and `third_party/` are git-ignored.** Regenerate per §4.
