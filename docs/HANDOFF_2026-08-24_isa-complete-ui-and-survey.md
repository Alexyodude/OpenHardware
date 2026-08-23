# Handoff — the 8086 map completed, an emulator UI, and where to go next

| | |
|---|---|
| **Date** | 2026-08-24 |
| **Repo** | `Alexyodude/OpenHardware` — not a fork, MIT |
| **Branch / HEAD** | `master` @ `1a4ab66`, clean, pushed |
| **Layout** | `Code/Github/OpenHardware/` + sibling `Code/Github/picsimlab-reference/` @ `62e8b5ba` |
| **Toolchain** | MSVC 19.44 via `vcvarsall`; cmake+ninja from pip. CI: ubuntu-latest, g++ |
| **Corpus** | **308 opcode files** in git-ignored `third_party/sst8088/v2/`. `v2-pending/` is empty — everything fetched is implemented |
| **Tests** | **572 passed, 17 skipped** (323 s with the corpus present) |
| **Conformance** | **2,797,000 / 2,797,000 across 302 files, 0 failing.** 6 more files are `PARTIAL` — see OH-11 |
| **Opcodes** | **248 of 256.** The 8 unclaimed are all *prefixes*: `26 2E 36 3E F0 F1 F2 F3` |
| **PICSimLab** | Still source-only, still unbuilt — but see §3.6, the recorded blocker was false |

The previous handoff is `docs/HANDOFF_2026-08-23_i8086-core.md`. Where the two
disagree, this one is newer.

---

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| OH-4: shift/rotate, muldiv, string, rep, bcd, io | ACHIEVED | `8a80cfb`; ticket status `done` |
| OH-12: the rest of the 8086 instruction map | ACHIEVED | `c1970c6`; 248/256, the 8 gaps are prefixes |
| The core executes whole programs | ACHIEVED | `tests/i8086/test_programs.py`, 10 programs run to completion |
| OH-7: emulator UI | ACHIEVED | `8def58c`; `python webui/emulator_server.py` |
| Disassembler | ACHIEVED | `core/i8086/disasm.py`; ABI v7 carries immediates and REP |
| Multi-core build plumbing | ACHIEVED | `020a6fc`; `core/*/CMakeLists.txt` discovered, not listed |
| Architecture survey (ESP / STM32 / RPi) | ACHIEVED | `docs/architectures.md`, 642 lines |
| IMUL/DIV/IDIV microcode-exact flags | NOT STARTED | ticket OH-11, 6 `PARTIAL` corpus files |
| OH-5: interrupts as a ticket | NOT STARTED | but `RaiseInterrupt` already exists — see §6.4 |
| Any non-8086 core | NOT STARTED | survey done, no code written |
| OH-9: PICSimLab adapter | BLOCKED ON a PICSimLab install | **narrower than recorded — §3.6** |

---

## 2. What the emulator UI is, and how to see it

```bash
python tools/build_core.py          # once
python webui/emulator_server.py     # http://127.0.0.1:8088/
```

Registers, flags as named chips, a hex dump, disassembly with the current
instruction marked, step/run/stop/reset, and six sample programs served from
`/api/samples`.

**Verified in a real browser this session** (Playwright, screenshots since
deleted): loading the "Sum 1 to 10" sample and pressing Step twice showed
`CX=000A` after `mov cx, 10` and PF+ZF set after `xor ax, ax`, with IP and
FLAGS marked as changed. Running to completion showed status `halted`,
`AX=0037` (55), `37` at address `00200`, and `24 steps` — matching
`test_the_loop_really_iterated` exactly. Light and dark themes both render;
the layout stacks below 900 px.

Architecture: `webui/emulator.py` is the session and holds all behaviour with
no HTTP in it; `webui/emulator_server.py` is a thin JSON translation. **Every
test drives the session, not the transport.** The server binds loopback only
and checks `Origin`, for the reason `bridge.py` states at length.

---

## 3. Root-cause narratives

### 3.1 `PUSH SP` was wrong in all 10,000 of its cases, invisibly

**Symptom.** Fetching the full `50–5F` range for the first time:

```
  53  100.00%
  54    0.00%   <-- push sp [0] (54): memory 0548E: expected 0E, got 10
  55  100.00%
```

Every sibling at 100%, opcode `54` at **zero**.

**Root cause.** `exec_core.cc` carried this comment and implemented it:

> PUSH SP stores the value SP held BEFORE its own decrement on this part.
> Later x86 changed that, and it is the classic way to tell an 8086 from a
> 286 in software — so the read happens first.

The AMD D8088 does the opposite. Raw JSON, three consecutive cases: `SS:SP =
F778:DD10` pushes `DD0E` — the **post**-decrement value. 10,000 of 10,000.
`FF /6`, the second encoding, agrees in 277 of 277.

**Why nothing caught it for two tickets.** SP is the only register for which
the order is observable, and no corpus file containing it had ever been
fetched. The sample was `50`, `51`, `52` — `PUSH AX`, `CX`, `DX` — where the
question does not arise. **A green family of three proved nothing about the
fourth.**

**Fix** (`0294f29`): decrement first, then read.

```cpp
cpu.regs().sp = static_cast<std::uint16_t>(cpu.regs().sp - 2);
cpu.WriteWordAt(cpu.regs().ss, cpu.regs().sp,
                ReadWordRegister(cpu.regs(), instruction.reg_in_opcode));
```

The mirror case has the **opposite** answer and is now pinned too: `FF /2`
(`CALL SP`) reads its target *before* pushing — 328 of 328.

**Generalization.** *Sampling a family is not enough when its members differ.*
The CI corpus list now carries `54` and `FF.6` with that sentence beside them.
Look for any other place where one member of a swept family can observe an
ordering the others cannot.

### 3.2 A pattern I wrote swallowed four opcodes I had already implemented

**Symptom.** After adding PUSH/POP of segment registers, the full corpus run
showed `27`, `2F`, `37`, `3F` at **0.00%** — DAA, DAS, AAA, AAS, which had
been at 100% an hour earlier. Failures showed wrong segment registers and a
moved SP: they were executing as something else entirely.

**Root cause.** The new `Lookup()` pattern was

```cpp
if (opcode < 0x40 && (opcode & 0x07) >= 0x06) { /* PUSH/POP sreg */ }
```

and `0x27 & 7 == 7`. Only the **first four** ALU groups put segment stack ops
in forms 6 and 7; the last four put the BCD adjusts there. The correct bound
is `< 0x20`.

The comment above `IsAluModRmForm` in the same file warns about exactly this:

> Forms 6 and 7 are not ALU operations and this function must not claim them
> … 27, 2F, 37 and 3F are DAA, DAS, AAA and AAS … would be shadowed if the
> pattern above were widened to cover them.

I wrote that warning earlier in the same session and then did the thing it
warns against.

**Bonus.** Fixing it also correctly *un*-claimed `26 2E 36 3E` — the segment
prefixes, which the too-wide pattern had been reporting as stack ops. That is
why the opcode count is 248, not 252.

**Generalization.** *A pattern that matches by arithmetic will silently
shadow anything it happens to cover.* When a family is regular in some forms
and not others, the bound is load-bearing and belongs in a test, not only a
comment.

### 3.3 DAA and DAS have an AF-dependent threshold no published algorithm has

**Symptom.** DAA and DAS sat at ~99.4% with the documented algorithm. 64 and
119 cases failed.

**How it was found.** Not by guessing. The correction hardware actually
applied was recovered from every case as `final AL − initial AL`, then
tabulated against AL's high nibble and AF:

```
DAA, CF-in = 0: correction by (AL high nibble, AF-in)
  hi | af=0            | af=1
   9 | 00x95 66x77     | 06x148
   A | 60x78 66x66     | 66x141
```

At a high nibble of 9 the two columns disagree and nowhere else does.

**Root cause.** The high correction's threshold is `0x99` — **except when AF
arrived set, where it is `0x9F`.** `AL=0x9E` with AF clear corrects by `0x66`
and becomes `0x04` with carry; the same AL with AF set corrects by `6` and
becomes `0xA4` with no carry. Every published version of this algorithm has
no AF term in that test.

**Also measured**: DAS's carry is *which correction ran*, not a borrow —
`CF = high_invalid` is exact over 20,000 cases; the manual's wording is wrong
on 60. And **AAA/AAS run the ALU even with nothing to correct**, with an
operand of zero, so their "undefined" SF/ZF/PF/OF are that operation's, taken
*before* AL is masked to one digit. Treating the correction as conditional
rather than as sometimes-zero scores **6%**.

**Generalization.** *When a family is stuck just short of 100%, recover the
operation the hardware performed from the state delta and tabulate it against
every input.* Guessing rules and re-running is slower and converges on local
optima.

### 3.4 A comment of mine claimed evidence it did not have

**Symptom.** None — caught while writing a test.

`bcd.cc` asserted that the corpus proves the part performs a single ADD of
`0x66` rather than two of `6` and `0x60`, citing "97.52% versus 100.00%".
Searching for a case that discriminates the two models returned **zero** — over
all 512 (AL, AF) pairs they produce identical results.

**Root cause.** The measurement was real but taken with the wrong threshold
(§3.3), so it was detecting the AF term, not the number of additions.

**Fix.** The comment now says the corpus cannot tell the two apart and that
the single-correction form is chosen because it is simpler. Kept rather than
deleted, because a comment citing a number is exactly the kind that gets
believed.

**Generalization.** *A measurement taken under a wrong model measures the
wrong thing convincingly.* Re-derive the claim after fixing the model.

### 3.5 Two bugs only a running program could expose

`kUnimplemented` returned from inside group 5 and LES/LDS **without restoring
IP**, breaking the promise `abi.h` makes that a refused instruction leaves the
processor untouched. No single-instruction test noticed, because none of them
looked at IP after a refusal.

And my own first draft of `test_programs.py` loaded programs at `0x0000` — on
top of the interrupt vector table — so the test that installs a handler wrote
vector 0 over its own first instruction. The fix was `0x0100`, "where DOS
loads a `.COM`", which is **also inside the table** (vectors `0x40`–`0xFF` live
at `0x0100`–`0x03FF`). DOS gets away with it because that offset sits in a
segment based far above the table, and here every segment starts at zero.
Programs now load at `0x0500`, clear of the table and the BIOS data area.

**Generalization.** *A single-instruction test never has both a program and a
vector table in memory at once.* Whole-program tests are a different oracle,
not a redundant one.

### 3.6 `known-issues.md` 4a.6 asserted something upstream's CI disproves

**Symptom.** OH-9 recorded as blocked because "the NOGUI build cannot be
linked with GCC 11.4 on Ubuntu 22.04".

**Root cause.** The evidence against it was inside our own reference clone.
`../picsimlab-reference/.github/workflows/linux-release.yml` runs a
`[ubuntu-22.04, ubuntu-24.04]` matrix, gates the AppImage step to **22.04**,
and that step runs `bscripts/build_appimage.sh` — whose line 68 is the NOGUI
link — on every master push.

Verified this session:

```
$ sed -n '/strategy/,/steps/p' .../linux-release.yml
                os: [ubuntu-22.04, ubuntu-24.04]
$ curl -sI -L ".../latestbuild/PICSimLab_NOGUI-0.9.3_260822_Ubuntu_22.04.5_LTS_x86_64.AppImage"
HTTP/1.1 200 OK
Content-Length: 16435704
```

That artefact was built from commit `62e8b5b` — **the exact commit our clone
sits on.** So the local ICE is environmental (stale LTO IR in `build_all/`,
WSL memory pressure during parallel LTRANS, or ccache staleness), not a
property of this source and this compiler.

Two further consequences: nothing in OH-9 needs NOGUI, and 4a.6 itself
records the WX GUI build working here — so the ticket was never as blocked as
written. And `build_appimage.sh` copies `lib/qemu` into the AppDir, so the
prebuilt AppImage **already bundles `libqemu-riscv32`, `libqemu-xtensa` and
the ESP ROM images**.

**Generalization.** *A blocker recorded once is a claim like any other and
decays.* Before building on "X is impossible", check whether the upstream
project does X routinely.

### 3.7 A JavaScript file that did not parse, past 572 green Python tests

A patch turned `join("\n")` into a string containing a literal newline.
`emulator.js` became a syntax error, the page rendered nothing, and **every
Python test still passed** — Python cannot execute the front end.

Found by opening the page in a browser and reading the console. Now guarded:
`tests/webui/test_emulator.py::test_the_browser_scripts_parse` runs
`node --check` over every script in `webui/static/`, skipping loudly where
node is absent.

**Generalization.** *A test suite in one language is blind to a second
language in the same repo.* The cheapest guard is that language's own syntax
checker, run from the suite that does exist.

---

## 4. Reproduce the result, cold

```bash
cd Code/Github/OpenHardware

# 1. Build. ~10 s; first run captures the MSVC environment.
python tools/build_core.py
#    -> .../build/lib/i8086.dll   129,024 bytes   [Linux: libi8086.so]

# 2. The suite.
python -m pytest -q
#    -> 572 passed, 17 skipped in ~325 s  (with the corpus present)
#    -> fewer, with more skips, on a fresh clone with no corpus

# 3. Every checker.
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_ticket_claims; do
  python -m tools.$c
done
#    -> all "OK". check_licenses says 105 files.

# 4. The hardware check, in full.
python - <<'PY'
import sys, pathlib
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
from i8086 import conformance, test_conformance
from tools import sst8088
d = pathlib.Path('third_party/sst8088/v2')
files = sst8088.opcode_files(d)
exact = [p for p in files if conformance.opcode_name(p) not in test_conformance.PARTIAL]
reports = [conformance.run_file(p, conformance.core_step) for p in exact]
ok = sum(r.passed for r in reports); tot = sum(r.total for r in reports)
print(f"{ok}/{tot} ({ok/tot:.4%}) across {len(reports)} files")
PY
#    -> 2797000/2797000 (100.0000%) across 302 files

# 5. The UI.
python webui/emulator_server.py     # http://127.0.0.1:8088/
```

**If the corpus is absent** (git-ignored, **697 MB** at 308 files), fetch what
you need:

```bash
bash tools/get_8088_tests.sh --opcodes 00 09 54 83 B8 D0.4 27 A4 F6.4 FF.2
```

**Group opcodes are named `<OP>.<reg>`** — `D0.0` … `D3.7`, `F6.0` … `F7.7`,
`80.0` … `83.7`, `FE.0`, `FF.0` … `FF.6`. Plain `D0` and `F6` **do not exist**
and the fetch script will say so.

---

## 5. File inventory

### New this session — the core

| File | Bytes | What |
|---|---|---|
| `core/i8086/shift.h` / `.cc` | 3746 / 5796 | the D0–D3 group; `/6` is SETMO, which Intel does not document |
| `core/i8086/bcd.h` / `.cc` | 2283 / 8049 | DAA, DAS, AAA, AAS, AAM, AAD and the AF-dependent threshold |
| `core/i8086/muldiv.h` / `.cc` | 1956 / 5547 | MUL, IMUL, DIV, IDIV; divide-error reported, not raised |
| `core/i8086/disasm.py` | 13600 | renders `Cpu.decode` as text; does **not** decode |

### New this session — the UI

| File | Bytes | What |
|---|---|---|
| `webui/emulator.py` | 13333 | the session: load, step, run, state. No HTTP. Holds `SAMPLES` |
| `webui/emulator_server.py` | 11348 | loopback JSON server; explicit route table |
| `webui/static/emulator.html` | 2875 | the page; favicon inlined as a data URI |
| `webui/static/emulator.css` | 8951 | three semantic colours, deliberately distinct |
| `webui/static/emulator.js` | 10362 | rendering only; memory pane built as DOM nodes, never markup |

### New this session — tests and docs

| File | Bytes | What |
|---|---|---|
| `tests/i8086/test_isa_full.py` | ~30 KB | 891 lines; every measured fact from OH-4/OH-12 pinned by name |
| `tests/i8086/test_programs.py` | 12051 | **10 whole programs**, checked on their answers |
| `tests/webui/test_emulator.py` | 15605 | session, samples, server; `node --check` over the browser scripts |
| `docs/architectures.md` | 33451 | the survey — every ESP/STM32/RPi part with a per-chip checklist |

### Changed

`core/i8086/{decode,exec_core,abi}.*` (ABI **version 7**), `tools/build_core.py`
(cores discovered, not listed), `tests/i8086/conformance.py` (`opcode_name`),
`.github/workflows/rules.yml` (CI corpus slice 10 → 42 files),
`docs/known-issues.md` (4a.6 corrected), `CLAUDE.md` (how to run the emulator).

---

## 6. Open work

### 6.1 Verify the Hazard3 golden model — *software-only, ~30 minutes, START HERE*

The entire from-scratch plan rests on a claim from one agent that has not been
executed. **Check it before building anything on it.**

```bash
git clone https://github.com/Wren6991/Hazard3 /tmp/hazard3
ls /tmp/hazard3/test/sim/rvcpp/
cd /tmp/hazard3/test/sim/rvcpp && make          # or: g++ -std=c++17 *.cpp
grep -n "struct RVCore" -A 30 *.h
```

The claim: `test/sim/rvcpp/` is a ~1080-line C++17 ISA simulator by the same
author as the RP2350 silicon, Apache-2.0, **no dependencies and no
cross-compiler**, whose `RVCore` exposes `regs[32]`, `pc`, `csr` and `step()`
as plain public members — already the shape a SingleStepTests-style fixture
generator needs, at roughly 150 lines of new code.

**What to confirm:** it builds with the local g++; `RVCore` really is that
shape; the licence in the LICENSE file (not just the README — a sibling agent
found a repo where those disagree); and which extensions it covers versus the
RP2350 datasheet's `rv32ima_zicsr_zifencei_zba_zbb_zbs_zbkb_zca_zcb_zcmp`.

**If it holds**, this is the cheapest oracle in the entire survey and RISC-V
becomes the obvious first non-8086 core. **If it does not**, the STM32
Cortex-M0+ path in §6.3 becomes the front-runner and `docs/architectures.md`
§1 needs its verdict table revised.

### 6.2 Download the prebuilt PICSimLab — *software-only, one command*

Unblocks OH-9, spec §8.4 and the whole ESP evaluation at once, with the QEMU
libraries and ESP ROMs included. **Verified to exist: 16,435,704 bytes,
HTTP 200.**

```bash
wsl -d Ubuntu-22.04
wget https://github.com/lcgamboa/picsimlab/releases/download/latestbuild/PICSimLab_NOGUI-0.9.3_260822_Ubuntu_22.04.5_LTS_x86_64.AppImage
chmod +x PICSimLab_NOGUI-*.AppImage
./PICSimLab_NOGUI-*.AppImage --appimage-extract    # WSL usually lacks FUSE
ls squashfs-root/usr/share/picsimlab               # what install_root() wants
ls squashfs-root/usr/lib/picsimlab/qemu            # libqemu-*, ESP ROMs
export PICSIMLAB_ROOT=$PWD/squashfs-root/usr
```

`latestbuild` is a moving tag — **record the versioned filename and its md5**
when adopting it. Note the AppImage is unpatched upstream, which is fine today
since `patches/0001` only adds an enum nothing yet uses.

### 6.3 The Cortex-M0+ corpus spike — *requires hardware (~£12 Nucleo-C031C6)*

The survey's §8 recommendation. Before any core is written, answer the one
open question with a ~200-line pyOCD script: **how many cases per second?**

Halt, write all 17 core registers and a test program to RAM, `step(disable_interrupts=True)`,
read everything back, loop, measure. Estimates span 20–50/sec realistic to
single digits pessimistic — a 10× spread that decides whether a corpus takes
an afternoon or two days. Nobody has published the number.

Two things to design **before** writing it, not after: Armv6-M collapses every
fault into one **HardFault** vector, so "this case faulted" must be a designed
outcome class; and out-of-sandbox operands must be filtered at generation time.

### 6.4 OH-5 — interrupts *(software-only)*

Mostly done already. `RaiseInterrupt` in `core/i8086/exec_core.cc` pushes
FLAGS, clears IF and TF, pushes CS and IP, and jumps through the table at
`0000:0000`. `INT n`, `INT3`, `INTO`, `IRET` and the divide-error trap all use
it and are at 100%. **The ticket's remaining work is the trap flag
(single-step) and lifting the function into `core/i8086/interrupt.*`** — do not
write a second one.

### 6.5 OH-11 — microcode-exact IMUL, DIV, IDIV *(software-only)*

The 6 `PARTIAL` corpus files. Results and CF/OF are exact; the undefined flags
are shift-and-add microcode intermediates. A single internal byte *does*
explain SF/ZF/PF jointly in all 10,000 IMUL cases, so the value exists — it is
just not the product's high half (ZF 96%, SF 98%, PF 69%). Separately, 33 of
569 non-trapping IDIV cases want the quotient's sign inverted, and no
combination of operand signs explains which.

### 6.6 The immediate-forms follow-up is **done**

The previous handoff listed `04 05 0C 0D … 3C 3D` as deliberately
unimplemented. They landed in `c1970c6`. Nothing to do.

### 6.7 OH-10, OH-8 — *unchanged, see the tickets*

---

## 7. Commits this session

```
1a4ab66 docs: correct a false blocker, and the oracle answer that follows from it
63f6073 docs: what it would take to emulate each architecture on the board list
4a51d1d docs(tickets): what the ESP route actually needs from OH-9
020a6fc refactor(build): discover cores under core/ instead of naming one
8def58c feat(webui): the i8086 emulator UI -- registers, flags, memory, disassembly
c1970c6 feat(i8086): the rest of the 8086 -- and the core runs programs now
0294f29 fix(i8086): PUSH SP was wrong in every case, and nobody could see it
eea0821 ci: fetch a corpus slice that actually covers the families that exist
8a80cfb feat(i8086): string ops, REP, and the F6/F7 group -- OH-4 complete
60bd1a7 feat(i8086): the decimal and ASCII adjusts -- 60,000/60,000
949feab feat(i8086): port I/O and the flag instructions -- 87,000/87,000
940ce64 feat(i8086): the shift and rotate group -- 240,000/240,000 against silicon
```

---

## 8. Known limitations and things not worth your time

- **The I/O score is not worth what it looks like.** The machine SST8088 was
  captured on had nothing on its I/O bus: all 40,000 `IN` cases read `0xFF`
  and all 40,000 `OUT` cases change nothing but IP. A core modelling ports and
  one returning a constant are indistinguishable. `kOpenBus` in
  `exec_core.cc` says so.
- **`POP CS` (`0F`) has no oracle.** SST8088 has no file for it. Implemented
  by symmetry and labelled as such in both the code and `test_abi.py`. Same
  for `HLT` (`F4`) — it cannot be single-stepped on a capture rig.
- **The corpus is 697 MB at 308 files.** CI fetches 42. A green CI is real
  hardware verification but not exhaustive; run the full local set before
  claiming a family is done.
- **Do not add `@pytest.mark.parametrize`.** `tools/inventory.py` counts
  `def test_*` with `ast` and `test_ast_count_matches_pytest_collection` fails
  on the divergence. Use a loop inside one test.
- **Heredocs mangle escapes.** Two bugs this session came from `\n` surviving
  a `python - <<'PY'` heredoc as a literal newline. Prefer the Write/Edit
  tools for anything containing escapes; verify with `node --check` or a
  re-read afterwards.
- **`docs/architectures.md` records two unresolved contradictions** rather
  than averaging them: whether "ESP32-S31" exists at all, and whether Armv6-M
  has 6 or 7 32-bit encodings (DDI0419C says 6; an agent reading DDI0419E
  counted 7 including a `UDF` T2 form). Do not silently pick one.
- **`espressif/xtensa-isa-doc` cannot enter this tree.** Its README says
  CC-BY-SA; its LICENSE file says **NonCommercial**. And `pico-bootrom`'s
  `mufplib.S` is not BSD like the rest of that repo — "solely on a Raspberry
  Pi RP2040 device", or GPLv2. rp2040js vendors it into an MIT repo anyway;
  that is not a precedent to copy without deciding.
- **Unicorn Engine's core is QEMU's TCG.** "Our core agrees with Unicorn" is
  near-worthless as cross-validation against QEMU. Any simulator oracle needs
  to be genuinely independent.
