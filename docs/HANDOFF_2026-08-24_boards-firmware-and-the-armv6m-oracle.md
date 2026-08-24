# Handoff — the board catalogue, a firmware reader, and an Armv6-M oracle

| | |
|---|---|
| **Date** | 2026-08-24 (second session that day) |
| **Repo** | `Alexyodude/OpenHardware` — not a fork, MIT |
| **Branch / HEAD** | `master` @ `ff9f12c`, clean |
| **Previous handoff** | `docs/HANDOFF_2026-08-24_isa-complete-ui-and-survey.md`. Where they disagree, this one is newer |
| **Toolchain** | MSVC 19.44; **no gcc/g++/clang/make**; Node 24.11.1; Python 3.13 |
| **New this session** | **arm-none-eabi GCC 12.3.1** and **PlatformIO Core 6.1.19** are on this machine — see §4 |
| **Network** | `st.com` is unreachable (connection-level, confirmed 3× independently). WebSearch budget was exhausted at 200/200 |
| **8086 core** | Unchanged: 248/256 opcodes, 2,797,000/2,797,000 hardware cases |

---

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| Board list generated, not hand-maintained | ACHIEVED | `d9896c5`; `collect_boards` in `tools/inventory.py`; 4 drift tests each proven to fail |
| Targets view inside the emulator UI | ACHIEVED | `2895351`; `http://127.0.0.1:8088/` → Targets tab; browser-verified, §3.4 |
| Survey corrections landed, tiered by evidence | ACHIEVED | `c4dffa6`; `docs/architectures.md` 51,536 bytes |
| Armv6-M corpus generator | ACHIEVED | `8afe281`; 150 cases generated, 50/50 ADCS independently re-derived |
| Firmware format layer (UF2/ELF/HEX/bin) | ACHIEVED | `7693013`; `webui/firmware.py`, 25 tests |
| Peripheral-layer research preserved | ACHIEVED | `ff9f12c`; `docs/research/peripheral-layer/`, 37 files |
| **A Cortex-M0+ core** | NOT STARTED | The corpus generator exists; nothing consumes it |
| **`tools/import_firmware.py`** | ACHIEVED (2026-08-24, later session) | `tools/import_firmware.py`; 42 tests in `tests/rules/test_import_firmware.py`; verified against a rebuilt three-env PlatformIO build |
| **`load_firmware` API op + UI view** | NOT STARTED | §6.2 |
| Peripheral design adopted into code | NOT STARTED | Deliberately. `docs/research/peripheral-layer/design.md` §6 is the scoping test |
| OH-9 PICSimLab adapter | BLOCKED ON a PICSimLab install | Unchanged from the previous handoff |

---

## 2. What changed, in one paragraph each

**The board list is now generated.** `tools/inventory.py` gained a fifth
collector with the same contract as the other four — it raises rather than
returning empty. `README.md` lists all 26 boards by name in two groups and
carries **no counts**, because a hand-typed total has no guard. Four tests
enforce it and each was verified to fail on real drift before being trusted.

**The chip list is a view in the emulator UI**, not a second page. One
`data-view` attribute on `<body>` drives both the panel swap and which toolbar
controls apply. The standalone page was deleted so two copies cannot drift.

**`docs/architectures.md` absorbed ~12 corrections**, each carrying its
evidence class. Five would have caused bugs if believed; one retraction was
*not* landed because the survey turned out to be right (§3.1).

**An Armv6-M corpus generator exists.** `tools/gen_armv6m_tests.mjs` drives
rp2040js and emits SST-shaped fixtures. It is the foundation a Cortex-M0+ core
needs, and Cortex-M0+ is worth **~22 boards** on the catalogue.

**`webui/firmware.py` reads what the toolchains emit** — UF2, ELF, Intel HEX,
raw binary — with no transport and no board. This is the format half of OH-10.

---

## 3. Root-cause narratives

### 3.1 A "correction" that would have made a C2 core trap a legal instruction

**Symptom.** An agent produced a tidy §4.2 table built from two machine-readable
sources — ESP-IDF's `components/soc/project_include.cmake` and Espressif LLVM's
`RISCVProcessors.td` — and issued corrections against `[V]`-marked datasheet
cells. Chief among them: *ESP32-C2 is `rv32imc`, the survey's `RV32IMAC` is
wrong.*

**Why it looked safe.** Two different repositories, two languages, two
maintainer groups, in exact agreement. That is normally strong evidence.

**How it was caught.** I refused to overwrite a `[V]` cell on toolchain
evidence and asked for it to be filed as a *conflict* rather than a
correction. The agent then fetched the datasheet itself. ESP8684 §CPU,
verbatim: *"base integer (I), multiplication/division (M), **atomic (A)** and
compressed (C)"*, **"RV32IMAC ISA"**. Control case in the same run: the C3
datasheet says **"RV32IMC"**, so the survey was right about both.

**Root cause.** IDF and LLVM are not independent — they answer *"what does the
compiler emit"*. The survey's cells answer *"what does the silicon implement"*.
Espressif simply chooses not to emit atomics for C2.

**Consequence had it landed.** A C2 emulator would have raised
illegal-instruction on `lr.w` — a legal instruction on that part, and precisely
the failure mode §4.3 warns about, inverted.

**Fix.** The rule is now in `docs/architectures.md` §4.2:

> **`-march` is compiler policy. The datasheet is silicon.** Emulator or
> decoder → datasheet. Fixture corpus covering only real firmware → `-march`.
> Where they disagree, record both and name the question being answered.

**Generalization.** *Two sources agreeing is not independence when they share a
premise.* §2.1c now records three instances of the same hazard in one session:
Unicorn and Renode both reduce to QEMU's TCG; QEMU-xtensa and binutils-xtensa
both come from the same Tensilica archive via `import_core.sh`, making "our
decoder agrees with `objdump`" a tautology; and IDF/LLVM here. **The check that
catches all three: before treating agreement as evidence, establish that the
two sources do not share an ancestor.**

### 3.2 The oracle I verified is wrong exactly where a corpus earns its keep

**Symptom.** None. The previous handoff's §6.1 said to confirm Hazard3's
`rvcpp` builds and that `RVCore` exposes the right shape. Both are true — I
built it with MSVC behind a 13-line shim and ran 15 hand-assembled instructions
with `add`, `clz`, `cpop`, `rev8`, `ctz` all correct.

**What nobody asked.** Whether it models what the hardware *refuses*.

**Root cause.** It does not. `rvcpp` has **no extension gating of any kind** —
94 opcodes live unconditionally — and its RVC decoder has **no XLEN gate**, so
`C_LD` (`rv_core.cpp:732`), `C_SD` (764), `C_LDSP` (981) and `C_SDSP` (1000)
are live in an `XLEN=32` build with zero floating-point support. Those four
encodings are RV32's Zcf/Zcd. On RP2350, which has no FPU, all four must raise
illegal-instruction.

**Measured, at `8af9929`:**

```
C.FLW   rd'=x12 EVEN  0x6010  ->  EXECUTES (a2 <- 00000033)
C.FLW   rd'=x13 ODD   0x6014  ->  illegal (cause 2)
C.FLWSP rd=x12  EVEN  0x6602  ->  EXECUTES
C.FLWSP rd=x13  ODD   0x6682  ->  illegal (cause 2)
```

The gate is a **spurious `rd[0] == 0` constraint in the generated opcode
masks**, so half the register space rejects by coincidence, not because the
model knows `F` is absent.

**The part that makes it dangerous.** With registers at their reset zeros the
even-register cases *still* trap — with cause 5 or 7 (access fault) instead of
2 (illegal instruction). So the defect presents as a correct rejection in
**three of the four** register-parity × base-validity quadrants, and is visible
only when a probe hits an even register *and* a valid base together.

**Fix.** `docs/architectures.md` §2.1b is qualified, not struck, and the §1
verdict row now reads "Cheapest oracle, not a sufficient one".

**Generalization.** *An acceptance criterion nobody wrote down is not a
criterion.* §6.1 asked "does it build and expose the right shape". The question
that mattered was **"does it model what the hardware refuses?"** — and that is
where this project's corpora earn their keep, since the 8086 work's value was
exactness at SETMO, the AF-dependent DAA threshold and `PUSH SP`'s ordering.

### 3.3 A checker that passed because it was not looking

**Symptom.** `check_licenses` exited 0 immediately after `webui/static/targets.html`
was created. It exited 1 on the very next run.

**Wrong hypothesis, ruled out fast.** "Something in the later edit broke it" —
no; the only intervening change was to `docs/architectures.md`.

**Root cause.** `check_licenses` reads `git ls-files`. The file was **untracked**
when I ran it, so it was never examined. The header had been in the wrong place
the whole time: the checker stops scanning at the first line that is not blank,
a shebang, a doctype or a comment, and the SPDX block sat after `<html>`,
`<head>` and `<title>`.

**Fix** (`3f258ff`): move the comment to directly after `<!doctype html>`, as
`emulator.html` does. The reason is recorded in a comment beside the header.

**Generalization.** *Running a checker before `git add` proves nothing about a
new file.* Any green result on freshly-created files is hollow until they are
tracked.

### 3.4 A helper that returned boot2 as a stack pointer

**Symptom.** `cortex_m_reset_vector` returned `(0x4b32b500, 0x60582021)` for a
real Pico image and reported success.

**Root cause.** It read the first word of the lowest segment. That *is* the
vector table on STM32, where flash begins with it. On RP2040 the first 256
bytes are `boot2`, the flash-XIP setup blob — so it was returning two
instructions as a stack pointer.

**Fix.** Renamed to `read_vector_table(image, address)` with **no default**,
same reasoning as `parse_bin`'s required `base`: a default correct for one
family and quietly wrong for another is worse than none. Verified after:
STM32 `@0x08000000` → `0x20002000 / 0x080028f5`; RP2040 `@0x10000100` →
`0x20040000 / 0x100001e3`.

**Generalization.** *Testing against a second instance of the same category is
what exposes an assumption baked into the first.* One family passed silently.

### 3.5 Two of my own claims, corrected by agents

Recorded because the pattern matters more than the facts.

- **I invented a UF2 family table.** I wrote a lookup dict *from memory* inside
  a verification script and reported its output as a finding: `0xE48BFF57` is
  **RP2XXX_ABSOLUTE**, not "RP2350 ARM-S" (that is `0xE48BFF59`). The
  authoritative `uf2families.json` was in the agent's own directory and I did
  not open it. The parsing was real; the label was fabricated, and the rigour
  around it made it look sourced.
- **I over-corrected a right claim into a wrong one.** I said all four rvcpp
  encodings execute, then "corrected" myself to two after an incomplete test —
  I had picked `x1`, an odd register, for the SP-relative pair. The original
  claim was right. I treated a measurement as decisive *because* it was a
  measurement.

**Generalization.** Six wrong claims this session, every one caught by an agent
rather than by me. Four were relay compressions that dropped a hedge; one was
memory standing in for a source inside something presented as verification; one
was over-correction. **If you are relaying an agent's finding, carry its
qualifiers verbatim or do not carry the finding.**

---

## 4. Reproduce the result, cold

```bash
cd Code/Github/OpenHardware
git log --oneline -1          # -> ff9f12c

# 1. The suite and the checkers.
python -m pytest -q           # -> 605 passed, 17 skipped  (~4-5 min with the corpus)
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_ticket_claims; do
  python -m tools.$c; done    # -> all OK

# 2. The UI, both views.
python webui/emulator_server.py         # http://127.0.0.1:8088/  -> Targets tab

# 3. The board inventory (computed, never written down).
python tools/inventory.py | sed -n '/^BOARDS/,+3p'
#    -> BOARDS - 26 definitions; 1 wired to the simulator, 25 outline only

# 4. The firmware reader, with no toolchain needed.
python -m pytest tests/webui/test_firmware.py -q    # -> 25 passed
```

### Rebuilding the firmware fixtures — **they are gone**

Every artefact this session measured lived in a session-scoped scratchpad that
no longer exists. PlatformIO is installed but **not on PATH**:

**Corrected 2026-08-24 (later session): the sketch below did not compile.**
All three environments failed with `'pinMode' was not declared in this scope`,
because PlatformIO only auto-injects `<Arduino.h>` for `.ino` files, not for
`src/main.cpp`. The ESP environment then failed a second time on `'LED_BUILTIN'
was not declared` — the XIAO ESP32-C3 has no user LED, so its variant defines
none. The version here is the one that builds; it was run to completion and
every figure in the table below reproduced from it.

```bash
PIO="/c/Users/Alexyodude/.platformio/penv/Scripts/pio.exe"
mkdir -p /tmp/fw/src && cd /tmp/fw
cat > src/main.cpp <<'CPP'
#include <Arduino.h>
#ifndef LED_BUILTIN          // XIAO ESP32-C3 has no user LED
#define LED_BUILTIN 10
#endif
void setup() { pinMode(LED_BUILTIN, OUTPUT); }
void loop() {
  digitalWrite(LED_BUILTIN, 1); delay(500);
  digitalWrite(LED_BUILTIN, 0); delay(500);
}
CPP
cat > platformio.ini <<'INI'
[env:nucleo_g031k8]
platform = ststm32
board = nucleo_g031k8
framework = arduino

[env:pico]
platform = raspberrypi
board = pico
framework = arduino

[env:seeed_xiao_esp32c3]
platform = espressif32
board = seeed_xiao_esp32c3
framework = arduino
board_build.flash_mode = dio
board_build.f_flash = 40000000L
INI
"$PIO" run                    # first run downloads toolchains; ~3-6 min
```

Expected, and each figure was measured this session:

| Artefact | Fact to expect |
|---|---|
| `.pio/build/nucleo_g031k8/firmware.elf` | 13,912 loadable bytes, entry `0x080028F5`, `.data` LMA `0x080035C0` vs VMA `0x20000000` |
| `.pio/build/nucleo_g031k8/firmware.bin` | first 8 bytes = MSP `0x20002000`, reset `0x080028F5` |
| `.pio/build/pico/firmware.uf2` | 149,504 B = 292 blocks, single family RP2040, vectors at **+0x100** → SP `0x20040000`, PC `0x100001E3` |
| `.pio/build/seeed_xiao_esp32c3/firmware.bin` | 5 segments; DROM→`0x3C030020`, IRAM→`0x40380000`, IROM→`0x42000020` |

**`board_build.f_flash = 40000000L` is not optional** for the ESP env: at the
80 MHz default, QEMU asserts `do_core_init` at `startup.c:328`.

The official dual-family UF2 (1029 RP2040 + 1019 RP2XXX_ABSOLUTE blocks, md5
`9f9e91d0e0c0f142d06f95077e6f3d06`) is at
`https://datasheets.raspberrypi.com/soft/blink.uf2`.

### Regenerating the Armv6-M corpus

```bash
git clone https://github.com/wokwi/rp2040js ../rp2040js
(cd ../rp2040js && npm install && npm run build)      # needs dist/cjs/rp2040.js
node tools/gen_armv6m_tests.mjs --count 1000
#    -> 27 families into third_party/armv6m/v1/, git-ignored
```

Without it the generator **exits 3 and says SKIPPED**, like the rule checkers —
it never emits an empty corpus and reports success.

---

## 5. File inventory

### New

| File | Bytes | What |
|---|---|---|
| `webui/firmware.py` | 20,654 | UF2/ELF/HEX/bin → `Image`. No transport, no board, pure stdlib |
| `tests/webui/test_firmware.py` | 12,880 | 25 tests; every fixture built in the file, none read from disk |
| `tools/gen_armv6m_tests.mjs` | 10,296 | Armv6-M corpus generator driven by rp2040js |
| `docs/research/peripheral-layer/` | 352 KB, 37 files | Nine agents' design + ESP32-C3/RP2040/STM32C031 JSON. **Unadopted** |

### Changed

| File | Bytes | What |
|---|---|---|
| `docs/architectures.md` | 51,536 | ~12 corrections, tiered by evidence class |
| `webui/static/emulator.html` | 17,645 | Targets view + toolbar tabs |
| `webui/static/emulator.css` | 15,053 | Targets styles on the existing three-colour palette |
| `webui/static/emulator.js` | 11,344 | `showView`, keyboard guard |
| `tools/inventory.py` | 16,205 | Fifth collector, `collect_boards` |
| `tests/rules/test_inventory.py` | 10,921 | 8 new tests incl. 4 drift guards |
| `README.md` | 5,560 | `## Boards` section, names only, no counts |

### Deleted

`webui/static/targets.html` — folded into `emulator.html` so two copies cannot
drift.

---

## 6. Open work, highest priority first

### 6.1 `tools/import_firmware.py` — artefact discovery — **DONE 2026-08-24**

**Landed.** `find_artefacts` covers all three layouts, the CLI reports what
`load_image` found, and a bare `.bin` is refused without `--base` — including
the refusal of one `--base` for a whole directory, since an ESP environment's
three images go to 0x0, 0x8000 and 0x10000.

Three things in the specification below were **deliberately not done**, each
for a reason worth keeping:

- **`boot_app0.bin`** is not searched for. It is not a build output — it is a
  framework constant, identical for every project, living under
  `~/.platformio/packages/framework-arduinoespressif32/tools/partitions/`.
  Discovering it would tie discovery to a global install path. It is flashed
  at 0xE000 and the module docstring says where it is.
- **An esp-idf image parser.** `identify_esp_image` walks the container's own
  structure — that walk *is* the identity check, since 0xE9 is also x86 `jmp
  rel32` — and reports where the five segments load. It builds no `Image`;
  that belongs in `webui/firmware.py` with its own tests, and is the natural
  first half of §6.2.
- **`docs/features/firmware.md`.** A ledger comes from the `feature-strategy`
  skill. `CLAUDE.md` says not to write one by hand and that still holds.

Everything below is the original specification, kept for its reasoning.

`webui/firmware.py` parses bytes. Nothing yet finds those bytes. This is the
piece that makes "open my PlatformIO project" work, and it is fully specified
by three agents' verified builds.

**Write `find_artefacts(project: pathlib.Path) -> list[pathlib.Path]`** covering:

- **PlatformIO**: `.pio/build/<env>/firmware.{uf2,elf,hex,bin}`, plus for ESP
  the sibling `bootloader.bin` and `partitions.bin`, and `boot_app0.bin` from
  the framework package.
- **Arduino CLI** (`--export-binaries`): `build/<fqbn>/<sketch>.ino.{bin,elf,hex}`,
  and **prefer `*.merged.bin` when present** — it is the full 4 MB flash image
  and the ideal loader input.
- **STM32CubeIDE**: `Debug/*.elf`.

Then a CLI that prints what `load_image` found. **Refuse a bare `.bin` without
an explicit `--base`** — `parse_bin` already has no default, for the reason in
its docstring.

Verify against rebuilt fixtures (§4). The three loader rules that must not be
re-derived are in `webui/firmware.py`'s module docstring.

### 6.2 `load_firmware` op and a Firmware view — *software-only*

`webui/api.py` already has a `SimulatorApi.load_firmware` sending
`loadhex <path>` (`webui/api.py:215`). For the emulator server the honest
first slice is **parse-and-inspect**: a third UI view showing segments, entry,
vector table and notes. `Image.notes` exists precisely so the UI can say "this
file also contained an RP2350 image, which was skipped".

### 6.3 A Cortex-M0+ core — *software-only, large*

Worth ~22 boards. The corpus generator (§4) exists and nothing consumes it.
`tools/build_core.py` already discovers any `core/*/` with a `CMakeLists.txt`,
so `core/cortexm0/` is picked up automatically — the plumbing was generalised
in `020a6fc`.

Start with the families the generator already covers: formats 1–4 of the
16-bit Thumb map, `0x0000`–`0x43FF`, register-only and all flag-setting.
**Do not trust rvcpp at the illegal-instruction boundary** — §3.2.

### 6.4 Decide on the peripheral design — *needs a human*

`docs/research/peripheral-layer/design.md` §6 is the scoping test: kinds and
detector are three-architecture-backed, multi-source `follows` is two,
`atomic_aliases` is one and already inverted once on new evidence.

### 6.5 Four questions only you can answer — *not agent-solvable*

1. **Arm FVP licence.** Downloads unauthenticated, runs here, models both M0
   and M0+. Its supplementary terms *prevail* over the EULA and scope "Software
   Models" to Arm architecture licensees. An Armv6-M core here is one.
   **Default: build nothing on it.**
2. **The Nucleo-C031C6's ST-LINK revision.** Decides ~245 vs ~2,000 cases/sec.
   On the board's silkscreen; `st.com` is unreachable from here.
3. **UDB Docker image** `ghcr.io/riscv/udb-toolchain:bf47acadf4bd5b66` — denies
   anonymous pull, needs `read:packages`.
4. **The `mufplib` question.** A compiled RP2040 boot ROM contains it, and it
   is licensed "solely on a Raspberry Pi RP2040 device" or GPLv2 — so the ROM
   image is not MIT-redistributable and an emulator is not that device.
   rp2040js vendors it into a plain-MIT repo anyway. Recommended:
   fetch-don't-vendor at setup.

### 6.6 Unchanged

OH-5 (trap flag, lifting `RaiseInterrupt` into `interrupt.*`), OH-11
(microcode-exact IMUL/DIV/IDIV), OH-8, OH-9.

---

## 7. Commits this session

```
ff9f12c docs: preserve the peripheral-layer research before the scratchpad is lost
7693013 feat(webui): read what PlatformIO, Arduino and picotool emit
8afe281 feat(tools): generate an Armv6-M conformance corpus from rp2040js
2895351 feat(webui): fold the targets list into the emulator UI as a second view
c4dffa6 docs: land the survey corrections, tiered by evidence class
3f258ff fix(webui): put targets.html's licence header where the checker looks
9ae89d8 feat(webui): a page for every chip on the board list, and its oracle
d9896c5 feat(tools): generate the board list instead of maintaining it
```

---

## 8. Visual output verification

The Targets view was checked in a real browser via Playwright, not inferred —
this repo has already shipped a page that was a syntax error past 572 green
Python tests.

**Emulator view:** three panels visible, 14 register cells rendered, `#targets`
`display: none`, Step enabled.

**Targets view:** all three emulator panels and the emulator-only toolbar
controls hidden; `#targets` visible with **6 panels and 17 chip rows**; the
grid computes to `grid-template-areas: "targets"` and the container measures
1017 px inside a 1049 px main, i.e. full span; `documentElement.scrollWidth`
does not exceed `clientWidth`, so no horizontal overflow.

**Dark theme, targets view:** body background `rgb(18,22,26)`, text
`rgb(222,229,236)`, stop-pill and tree-root `rgb(240,120,138)`, table headers
`rgb(13,17,21)` — every new token resolves.

**Console:** 0 messages at warning level or above.

---

## 9. Known limitations and traps

- **The scratchpad is gone.** Everything nine agents built lived under a
  session UUID. The design and the JSON were rescued into
  `docs/research/peripheral-layer/`; the firmware fixtures were not, because
  they are large and rebuildable (§4).
- **The corpus is a simulator oracle, not silicon.** A case means "agrees with
  rp2040js". It was silicon-diffed once via gdbdiff, not continuously, and
  **it does not model faults at all** — so the corpus says nothing about what
  hardware refuses.
- **QEMU cannot model Cortex-M0+ at all.** `arm_v7m_cpus[]` has m0, m3, m4, m7,
  m33, m55 and no m0plus. Two architectural deltas matter: M0 has **no VTOR**
  and **no `CONTROL.nPRIV`**. Capture on M0+; an M0 corpus is a strict subset
  derivable from it, never the reverse, and the format must record which.
- **"SST-shaped" does not mean hardware-captured.** Only the x86 family claims
  it; ARM7TDMI came from NanoBoyAdvance, m68000 from MAME.
- **Do not add `@pytest.mark.parametrize`.** `tools/inventory.py` counts
  `def test_*` with `ast`, and `test_ast_count_matches_pytest_collection` fails
  on the divergence. Loop inside one test.
- **`XIAO-XIAO STM32C5-SMD`** — the doubled prefix is faithful to Seeed's own
  footprint name, and their KiCad library really does contain
  `XIAO-STM32C5-SMD.kicad_mod`. But "STM32C5" is not an ST family anyone could
  place, and no product page was found. Confirm before it goes anywhere public.
- **WebSearch was exhausted at 200/200.** `WebFetch` still worked. `st.com`
  times out at the connection level regardless.
