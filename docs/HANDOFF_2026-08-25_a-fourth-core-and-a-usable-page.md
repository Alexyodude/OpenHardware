# Handoff — a fourth core, and a page you can actually drive

| | |
|---|---|
| **Date** | 2026-08-25 (later than `HANDOFF_2026-08-25_a-board-that-runs.md`; where they disagree, this one is newer) |
| **Repo** | `Alexyodude/OpenHardware` — not a fork, MIT |
| **Branch / HEAD** | `master` @ `bb1e139` |
| **Working tree** | One file modified — `docs/tickets/OH-51-*.md`. **Not mine.** See §3.1 |
| **Toolchain** | MSVC 19.44; Python 3.13; **arm-none-eabi GCC 10.3** and **avr-gcc 7.3.0**, both under `~/.platformio/packages/`; PlatformIO 6.1.19 (not on PATH) |
| **Cores built** | `avr.dll` 96,256 · `cortexm0.dll` 222,208 · `i8086.dll` 129,024 · `riscv32.dll` 102,912 |
| **Gate** | 1,173 passed, 17 skipped; **all eight checkers exit 0** |
| **Boards** | 26 imported, 4 runnable, 4 firmware-verified |

**A second session is committing into this repository continuously.** Eight of
the last fourteen commits are theirs. Read §3.1 before you commit anything.

---

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| A runtime board contract | **ACHIEVED** | `webui/boards/contract.py`, 13 tests in `tests/webui/test_board_runtime_contract.py`; `1de0e81` |
| `VECTOR_TABLE_OFFSETS` moved out of `api.py` into the boards | **ACHIEVED** | `rp2040.py` `(0, 256)`, `samd21.py` `(0,)`; drift guard pins them against `api.py`'s copy |
| An Armv6-M disassembler | **ACHIEVED** | `core/cortexm0/disasm.py`; **56,551/56,551 encodings agree with objdump**; `e2d10cc` |
| Program/upload workflow in the Emulator tab | **ACHIEVED** | `05aaf80`; browser-verified, §8 |
| A loaded board shows its own registers + Thumb listing | **ACHIEVED** | `9b2f397`; `/api/board/state` carries `listing`; browser-verified |
| The disabled core selector is gone | **ACHIEVED** | `1d8ea1b`; `#board-pick` is the only machine selector |
| An AVR core | **ACHIEVED** | `core/avr/`; real avr-gcc blink, 19 transitions, period 1110; `bb1e139` |
| **Arduino Uno selectable in the UI** | **BLOCKED ON the board contract's entry model** | §6.1 — this is the top open item |
| **7 ESP32-C boards** | **BLOCKED ON a ticket claim** | OH-47; `core/riscv32/**` is OH-44's, a live programme |
| 8 Cortex-M33 boards | **NOT STARTED** | OH-36, blocked on oracle |
| 2 Cortex-M4 boards | **NOT STARTED** | OH-50; **no QEMU on this machine**, so no oracle at all |
| 3 ESP32-S3 boards | **REFUSED ON EVIDENCE** | OH-38; both Xtensa oracles are the same source |

---

## 2. What changed, in one paragraph each

**A contract exists for what a board must supply.** It was one line —
`hasattr(description, "install")` in `api.py` — while `api.py` separately held
`VECTOR_TABLE_OFFSETS`, a fact about a chip living in the module that speaks
HTTP. Both boards now declare their own.

**`core/cortexm0` can disassemble.** Checked against `arm-none-eabi-objdump`
over every encoding it claims, which found three bugs four real images could
not.

**The page is usable.** Loading and running an image moved out of the Targets
tab, a loaded board shows its own registers and a Thumb listing, and the
disabled core selector that named no MCU is gone.

**There is a fourth core.** `core/avr` runs a real compiled Arduino Uno blink.
It is the first non-Arm, non-x86 core here, and the first Harvard one.

**The remaining unlocks are ticketed with their real blockers** — OH-47, OH-48,
OH-49, OH-50.

---

## 3. Root-cause narratives

### 3.1 Another session is committing here — READ THIS FIRST

**Symptom.** `git log --oneline -14` shows eight commits I did not write:
`2d0341d`, `16dceeb`, `1a817d1` (ticket-guard work), `d354809`, `9a6e24f`,
`4868acb` (RISC-V Zba/Zbs), `64808c3`, `5b34bdf` (board UI + UART on the wire).

**This is not the `git add -A` accident** the previous handoff's §3.1 records —
nothing of theirs was swept into my commits this time, because every commit
below stages by explicit path. The point here is different: **their work landed
mid-session and changed what I was about to build.**

Concretely, I began designing "let the UI pick a board and run an image" and
found `64808c3` had already shipped it, and my own OH-43 was already closed by
them. I re-measured instead of building it twice.

**Fix, for the next session:** run `git log --oneline -10` and
`python tools/tickets.py list` *before* designing anything, not just before
committing. The tree moves.

**Generalization.** *In a repository with concurrent sessions, the design input
is the tree as it is now, not as the last handoff described it.* A handoff is a
snapshot; the ticket list is the live state.

### 3.2 Three disassembler bugs that four real images could not find

**Symptom.** None. `blink.bin`, `samd21/blink.bin`, `hello.bin` and
`delay.bin` — 162 instructions of real compiler output across two chips —
matched objdump at 159/162, and the three misses were all legitimately data.

**Root cause.** Those four images between them contain **no byte-reverse, no
`CPS`, no `SVC`, and no malformed `BX`**. So an exhaustive sweep was run:
every 16-bit encoding the disassembler *claims*, laid end to end into one
binary, compared against objdump in a single pass. 56,805 encodings, 479
disagreements, three of them real:

- the `rev`/`rev16`/`revsh` table was indexed with its gap in the wrong slot,
  so it printed `rev16` for 64 encodings Armv6-M leaves **undefined** and for
  none of the ones that mean it;
- `BX`/`BLX` accepted nonzero low bits, which are UNPREDICTABLE — 96 encodings
  named `blx`;
- `MOV r8, r8` is the canonical no-op and was printed as a move.

**Fix.** `core/cortexm0/disasm.py`, and the sweep is now
`test_every_encoding_it_claims_matches_objdump`. **56,551/56,551 agree.**

**Generalization.** *Real firmware is a biased sample of an instruction set.*
A compiler emits what it needs; the encodings it never emits are exactly the
ones a hand-written decoder gets wrong. Where the space is small enough to
enumerate, enumerate it.

### 3.3 A stale server made new code look broken

**Symptom.** After adding a board listing, the browser showed **Arm registers
beside an x86 disassembly**, with *zero* console errors.

**Wrong hypothesis, and how it was ruled out.** The obvious read is that
`renderBoardState` threw partway. Calling it directly in the page returned
`THREW: Cannot read properties of undefined (reading 'present')` — and the
fetched payload had `hasListing: false`. So the *server* was not sending it,
though `api.py` on disk plainly did.

**Root cause.** `netstat -ano | grep :8088` showed **three** processes
LISTENING. `pkill -f emulator_server.py` had silently failed on earlier rounds,
Windows let all three bind, and the oldest — predating the `listing` field —
was answering. HTML, CSS and JS are read from disk per request so they looked
fresh; only the Python needed a restart.

**Fix.**

```bash
for pid in $(netstat -ano | grep ":8088" | grep LISTENING | awk '{print $5}' | sort -u); do
  taskkill //PID $pid //F
done
```

**Generalization.** *When new code appears half-applied, check the process
table before the code.* `pkill -f` is unreliable in Git Bash on Windows; the
symptom points at whatever you changed last, and the cause is that nothing you
changed is running.

### 3.4 An AVR branch polarity that ran 60,000 instructions and lied

**Symptom.** The compiled blink ran its full budget with no fault, toggled
PB5, and alternated correctly — at a period of **10 instructions**. A `for`
loop counting to 100 cannot cost ten instructions.

**Root cause.** `BRBS` is `1111 00kk kkkk ksss` and `BRBC` is
`1111 01kk kkkk ksss`, so **bit 10 SET means branch-if-CLEAR** — the opposite
of how the bit reads. Inverted, the delay loop took its exit branch on the
first comparison every time.

**Fix.** `core/avr/exec.cc`: `branch_if_set = (encoding & 0x0400) == 0`.

**Generalization.** *A wrong flag polarity does not crash; it runs a different
program to completion.* Transition count, alternation and absence of faults all
passed. Only asserting the **period** caught it — which is why
`test_the_delay_loop_actually_delays` exists separately from the count.

### 3.5 A rule the fixture could not reach, found by mutation

**Symptom.** Mutating `cpc` to assign `Z` from its own result — instead of only
ever clearing it — left **all sixteen AVR tests passing**.

**Root cause.** Not a bad test; a blind fixture. The blink branches on `C`
after its `cpc` and never on `Z`, so the rule is unobservable in that image.
But it is correct AVR and load-bearing: `cpi` on the low byte then `cpc` on the
high leaves `Z` set only if **both** were equal.

**Fix.** Not deletion — `test_a_sixteen_bit_compare_reports_inequality`, using
256 against 100, where the low bytes differ and the high-byte subtraction lands
on zero. Only the carried-in `Z` distinguishes the two answers.

**Generalization.** *Mutation testing distinguishes "dead code" from "correct
code with no witness".* Earlier this session the same technique deleted two
genuinely dead things (`& byte_mask` on set/clear/xor; `writable=false` on a
counter). Here it demanded a test instead. The question to ask is "could any
input tell the difference?", not "did anything fail?".

### 3.6 A mutation round that proved nothing

**Symptom.** Three of five disassembler mutations "survived".

**Root cause.** The `sed` patterns never matched, so the file was never
changed. Verified by re-searching for the fragments afterwards: 0 hits.

**Fix.** Re-run by line anchor rather than by pattern. All five then failed
correctly.

**Generalization.** *A mutation that does not change the file proves nothing
about the test.* Reporting that round as "the tests are weak" would have been
exactly backwards. Always confirm the mutation applied before reading its
result.

---

## 4. Reproduce the result, cold

```bash
cd Code/Github/OpenHardware
git log --oneline -1                      # -> bb1e139

# 1. Build all four cores.
python tools/build_core.py
#    -> build/lib/avr.dll       (96256)
#    -> build/lib/cortexm0.dll  (222208)
#    -> build/lib/i8086.dll     (129024)
#    -> build/lib/riscv32.dll   (102912)

# 2. The gate.
python -m pytest -q                       # -> 1173 passed, 17 skipped (~4 min)
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_ticket_claims check_board_claims; do
  python -m tools.$c; done                # -> all exit 0

# 3. The new core.
python -m pytest tests/avr/ -q            # -> 18 passed

# 4. The disassembler's exhaustive check (needs arm-none-eabi-objdump).
python -m pytest tests/cortexm0/test_disasm.py -q   # -> 16 passed
```

### Driving a board in the browser

**Start exactly one server** — see §3.3.

```bash
netstat -ano | grep ":8088" | grep -c LISTENING     # -> expect 0 first
python webui/emulator_server.py                     # http://127.0.0.1:8088/
```

On the **Emulator** tab: pick `XIAO-RP2040-DIP`, choose
`tests/cortexm0/uart/hello.bin`, set base `0x10000100`, Load, Run.
Expect `hello, world` in the console, `pc 0x10000142` in the report, and a
Thumb listing in the Disassembly pane.

### Rebuilding the AVR blink

`blink.bin` is 46 bytes and committed;
`test_the_committed_binary_matches_its_source` rebuilds and compares it
wherever a compiler exists.

```bash
AVR=~/.platformio/packages/toolchain-atmelavr/bin
"$AVR/avr-gcc.exe" -mmcu=atmega328p -Os -ffreestanding -nostdlib -nostartfiles \
  -o /tmp/blink.elf tests/avr/blink/blink.c
"$AVR/avr-objcopy.exe" -O binary /tmp/blink.elf tests/avr/blink/blink.bin
```

---

## 5. File inventory

### New this session

| File | Bytes | What |
|---|---|---|
| `core/avr/exec.cc` | 14,050 | 15 AVR instructions, read off the blink's disassembly |
| `core/avr/cpu.h` | 6,656 | Two address spaces, registers-as-data-memory, SP at RAMEND |
| `core/avr/cpu.cc` | ~2,300 | The spaces, and the 0xFFFF erased fill |
| `core/avr/abi.py` | 10,810 | ctypes binding, ABI v1 |
| `core/avr/abi.h` / `.cc` | ~2,800 / ~3,900 | The C surface; every accessor names its space |
| `core/cortexm0/disasm.py` | 17,598 | Thumb-16 + the BL pair, as text |
| `webui/boards/contract.py` | 6,976 | What a board must supply, with each requirement's caller named |
| `tests/cortexm0/test_disasm.py` | 14,706 | 16 tests, incl. the 56,551-encoding sweep |
| `tests/avr/test_blink.py` | 13,180 | 18 tests |
| `tests/avr/blink/blink.c` / `.bin` | 1,081 / **46** | Bare-metal Uno blink, committed |
| `tests/webui/test_emulator_session.py` | 9,272 | 9 tests: which half of the page operates a machine |
| `tests/webui/test_board_runtime_contract.py` | ~7,800 | 13 tests, incl. the api.py drift guard |

### Modified

`webui/boards/rp2040.py` and `samd21.py` (own `VECTOR_TABLE_OFFSETS`),
`webui/api.py` (`listing_view`), `webui/static/emulator.{html,css,js}`,
`tests/webui/test_targets.py` (core list tripwire, third firing).

### Toolchains fetched this session

`toolchain-atmelavr@3.70300.220127`, `framework-arduino-avr` — both via
`pio pkg install -g -t <name>`, the same route `framework-arduino-samd` came in
by. Neither is in the repo.

---

## 6. Open work, highest priority first

### 6.1 The board contract has no entry model for a machine without a vector table — *software-only, START HERE*

**This is a design decision, not typing, and it is what blocks the Arduino Uno
from being selectable.**

`core/avr` works. `tests/avr/test_blink.py` watches a real compiled image
toggle PB5. What does not exist is `webui/boards/atmega328p.py`, and it was
left out **deliberately**:

- `webui/boards/contract.py` requires `VECTOR_TABLE_OFFSETS`, because
  `webui/api.py`'s `_place()` needs it.
- `_place()` reads an **initial stack pointer** and a **reset handler** out of
  the first two words of the image. That is an Arm arrangement.
- An AVR simply begins executing at address zero. It has no such table.

So a board file *could* satisfy the contract literally with
`VECTOR_TABLE_OFFSETS = (0,)` — and then `catalogue.py` would report Arduino Uno
`runnable`, while `api.load_firmware` could not actually enter it. That is the
claim-you-cannot-keep failure `rules/board-claims.md` exists to prevent,
arriving through a different door.

**What to decide:** what "how does this board enter an image" means when the
answer is not "read two words". Candidates, none yet chosen:

1. A board declares an `entry(image)` callable instead of an offsets tuple —
   Arm boards implement it by reading the vector table, AVR returns 0.
2. `VECTOR_TABLE_OFFSETS` stays and gains a sibling the contract accepts as an
   alternative, so Arm boards are unchanged.
3. `api.load_firmware` grows a per-core entry strategy, keyed the way
   `description_module()` already keys chip → module.

Whichever is chosen, `tests/cortexm0/test_blink.py` and
`test_samd21_blink.py` must pass **unchanged** — that was OH-31's own condition
for the contract being right rather than merely present.

Then: `webui/boards/atmega328p.py`, `ATmega328P` in `FIRMWARE_VERIFIED`, and
`test_only_the_board_a_real_image_ran_on_claims_to_have_run_one` updated
deliberately (it pins the set to `{"RP2040", "SAMD21"}`).

File a ticket for the contract change; OH-49 is claimed and its note records
this in full.

### 6.2 OH-47 — MMIO for the RISC-V core — *software-only, BLOCKED ON A CLAIM*

The 7-board unlock and the largest. `core/riscv32` has **no MMIO at all** — no
`map_register`, no `map_alias`. Port the five behaviours `core/cortexm0` grew,
in the order they were forced there.

**Blocked on a claim rather than on the work.** `core/riscv32/**` belongs to
OH-44, which is a *live* programme — its body sequences Zbb, then Zbkb, then
the Zc* group. Coordinate before touching it. OH-47 claims a placeholder path
so it can exist without colliding.

### 6.3 OH-48 — an ESP32-C3 board description — *software-only, depends on 6.2*

Three boards. `toolchain-riscv32-esp` is already present so a bare-metal image
can be compiled. Two facts already measured and in the ticket: the XIAO
ESP32-C3 has **no user LED**, so the fixture must watch a GPIO register; and
apps cannot run without the mask ROM, so the image must be bare metal.

### 6.4 OH-50 — a Cortex-M4 core — *software-only, no oracle here*

Two boards. Armv7E-M is a **superset** of the working Armv6-M, so it starts
from code that works. But **QEMU is not installed** — verified 2026-08-25 —
so the interpreter cannot be lockstepped against anything. The *decode* can be
checked exhaustively against objdump the way §3.2 did.

### 6.5 OH-36 — a Cortex-M33 core — *blocked on oracle*

Eight boards, the biggest single unlock, worst evidence situation. Held by
another session.

### 6.6 OH-38 — do not build Xtensa — *decided*

Three boards. Both apparent oracles derive from the same Tensilica archive.

### 6.7 Residuals

1. **`webui/api.py` still holds its own `VECTOR_TABLE_OFFSETS`**, because
   OH-32 owned that file when OH-31 landed. It is now unclaimed, so the copy
   can be deleted — `test_the_offsets_api_uses_agree_with_the_boards_that_declare_them`
   is what makes that safe.
2. **MMIO is word-only on `core/riscv32`** — the cortexm0 sub-word fix did not
   carry across.
3. **`PYI034` on `__enter__`** in all four cores. Known, recorded, ignored.

---

## 7. Commits this session

```
bb1e139 feat(avr): a core that runs a real compiled Arduino Uno blink
c1987f0 docs(tickets): the four remaining MCU unlocks, each with its real blocker
1d8ea1b fix(webui): remove the core selector that named no MCU and disabled itself
9b2f397 feat(webui): a loaded board shows its own registers and Thumb listing
05aaf80 feat(webui): program a board from the Emulator tab, not the Targets tab
e2d10cc feat(cortexm0): an Armv6-M disassembler, checked against objdump
1de0e81 feat(boards): state what a board must supply, and move one fact to where it belongs
```

Interleaved with these, **another session committed** `2d0341d`, `16dceeb`,
`1a817d1`, `d354809`, `9a6e24f`, `4868acb`, `64808c3`, `5b34bdf`. Every commit
above staged by explicit path; none of theirs was swept in.

---

## 8. Visual output verification

Checked in a real browser via Playwright, not inferred.

**Emulator tab.** Board panel, file input, Load, Run and the UART console all
visible; Disassembly, Registers and Memory visible; the progress tables hidden.
`#board-pick` offers **26 boards, 4 enabled**, the other 22 disabled carrying
their reason.

**Targets tab.** Every control hidden. "Runnable now" shows `cortexm0 BUILT`
with its full not-drivable reason, `i8086 DRIVABLE`, `riscv32 BUILT`; strip
reads 1 drivable / 3 cores built / 0 unbuilt; Boards table 26 rows.

**A real run, through the UI.** `XIAO-RP2040-DIP` +
`tests/cortexm0/timer/delay.bin` at base `0x10000100`. After Load, PC is
`0x10000108` and the listing opens `movs r2, #144`. After Run, PC is
`0x1000012E` and the listing reads:

```
1000012E  680b  ldr   r3, [r1, #0]
10000130  1b1b  subs  r3, r3, r4
10000132  2bc7  cmp   r3, #199
10000134  d9fb  bls.n 0x1000012e
```

That is `busy_wait_us(200)` counting down — the timer loop, disassembled out of
a running board. The hexdump shows the vector table: `00 20 04 20`, then
`09 01 00 10`.

**Console: 0 messages at warning level or above**, on every check.

---

## 9. Known limitations and traps

- **A second session commits here constantly.** Stage by explicit path; never
  `git add -A`. Re-read `git log` and `tickets list` before *designing*, not
  just before committing. §3.1.
- **`pkill -f` does not work in Git Bash here.** Servers accumulate on 8088 and
  the oldest answers. §3.3.
- **An in-review ticket owns its paths exactly as an open one does.** This cost
  three separate collisions this session (OH-39, OH-33, OH-45/46 vs OH-43/OH-31).
  Close tickets when their work lands.
- **objdump decodes a wider architecture than it is told.** Given `-m armv6-m`
  it still renders Thumb-2 (`and.w`) and Armv8-M (`bxns`). Divergences at
  literal-pool addresses are that, not bugs.
- **A mutation that does not change the file proves nothing.** §3.6.
- **AVR has no hardware-captured oracle**, and neither simavr nor avr-gdb is
  installed. `core/avr` meets the RP2040/SAMD21 standard — a real image,
  watched — and must not claim more.
- **Do not add `@pytest.mark.parametrize`.** `tools/inventory.py` counts
  `def test_*` with `ast`. Loop inside one test.
- **`ruff` is not adopted here.** One `PYI034` per core is expected.
