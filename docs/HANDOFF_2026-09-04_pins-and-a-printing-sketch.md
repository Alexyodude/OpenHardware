# Handoff 2026-09-04 (evening) — the pin map lands, and an ESP32 sketch can print

| | |
|---|---|
| Date | 2026-09-04, continuing the session that wrote `docs/HANDOFF_2026-09-04_six-tickets-and-two-products.md` |
| Repository | `C:\Users\Alexyodude\Desktop\AlexFolder\Code\Github\OpenHardware`, branch `master`, HEAD **`fb93597`**, 313 ahead of `origin/master`, **tree clean** |
| Session id | `d4fefe50-4831-4eaf-950d-b7fd61649b25` (`OH_SESSION_ID` for `tools/tickets.py`); **holds no ticket** |
| Ralph | `/ralph "complite tickets"` is ACTIVE. PRD at `.omc/state/sessions/d4fefe50-4831-4eaf-950d-b7fd61649b25/prd.json`: US-1, US-2, US-3 pass; US-4, US-5, US-6 open |
| Tests | 2,103 collected; `python tools/checkall.py` = all 12 checks, run clean |
| Toolchains | unchanged: GCC 8.4.0 (esp-2021r2) for RV32, MSVC for the cores, node for `wires.js`, Blender 4.5/5.1, **no QEMU** |
| Other sessions | `agent-oh36` still holds **OH-36**. Never take or edit it. |
| Build quirk | `build/lib/riscv32.dll.locked-by-pid44724` (151,552 bytes) is a stale copy left aside; see §9.1 |

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| OH-160: the resolved pin map reaches the board files and the modules | ACHIEVED | `10bc1e3`; `tools/import_pindefs.py --write-headers/--write-boards`; reviewer APPROVE after 12 findings |
| OH-161 step 1: UART TX on the three ESP32 boards | ACHIEVED | `fb93597`; a compiled sketch's 18 bytes arrive on all three; reviewer APPROVE after 13 findings |
| OH-161 steps 2-5 (timer, GPIO_IN, ADC, I2C) | NOT STARTED | deliberate; every hint but `Serial`'s still stands, ticket still `open` |
| OH-162 step 1: wire radius in the solver | NOT STARTED | before-number measured: `proud` = 0.16 (§6.1) |
| OH-162 step 2: wire-wire contact | NOT STARTED | — |
| OH-164: a picked board says "in use elsewhere" while nothing runs | NOT STARTED | filed this session; 22 pads on the Uno, 11 each on three XIAOs |
| OH-163: silkscreen text, default finishes | BLOCKED ON a stroke-font licence decision | its step 1 needs that decided before any glyph is drawn |
| OH-157 | BLOCKED ON a pico-sdk rp2350 register source | unchanged |
| OH-36, OH-38, OH-64, OH-9, OH-8, OH-11, OH-159 | BLOCKED ON hardware, oracles, binaries or another session | unchanged from the previous handoff |

## 2. What is open, top first

1. **US-4 = OH-162 step 1 — a jumper lead gets a thickness in the solver.** `software-only`. Cold start:
   ```bash
   cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware
   export OH_SESSION_ID=d4fefe50-4831-4eaf-950d-b7fd61649b25
   python tools/tickets.py start OH-162
   node "$USERPROFILE/AppData/Local/Temp/claude/C--Users-Alexyodude/d4fefe50-4831-4eaf-950d-b7fd61649b25/scratchpad/drape.mjs"
   #   {"solverKnowsRadius":false,...,"proud":0.16,"inside":0}  <- the failing boundary
   ```
   The design is settled and is §6.1. `webui/static/wires.js` gets `this.radius = 0` beside `this.floor` (plain data the caller supplies, exactly like `colliders`); `collide()` clamps to `floor + radius`; `outOfBox` expands the box by the radius on each axis; `outOfSphere` pushes to `r + radius`. `webui/static/board3d.js`'s `applyColliders` (~line 2102) sets `wire.rope.radius = WIRE_RADIUS`, because it already sets `colliders` and `floor` there. Done when the probe reads `proud` 0 and `inside` 0, with a clear-air fixture that must report nothing.
2. **US-5 = OH-162 step 2 — wire-wire contact.** `software-only`. Capsule-capsule between segments of different ropes, run last in the pass like the solids. The ticket asks for a measured step-time before and after, because it is the first O(n²) thing in the solver.
3. **US-6 = OH-164 — the panel's third sentence.** `software-only`, and it needs `tests/webui/test_board3d.py`, which **OH-162 claims** — so it comes after OH-162 is `done`, or its holder lands the panel change. Design is in the ticket: `pad_view` states whether any levels were read rather than the page inferring it from `unknown == pads.length`.
4. **OH-161 steps 2-5**, in the ticket's own order: the systimer (`map_counter` is the behaviour `core/riscv32` still lacks — `cpu.h:191-207` now says so), then GPIO_IN against the solved node voltage, then the ADC, then one I2C part.
5. Everything else is unchanged from the previous handoff's §2: OH-157 needs a fetch, QEMU needs the user's yes, and the rest need hardware or oracles.

## 3. Root-cause narratives

### 3.1 OH-160 — the field that could not hold the answer

Symptom: `python -c "from webui.boards import esp32c3; print(esp32c3.PIN_NAMES)"` → `AttributeError`, while `tools/import_pindefs.py` had resolved 321 of 550 XIAO pads since OH-26 and nothing consumed them. The ticket said to fill `pin` in the JSONs.

**Ruled out: filling `pin`.** `webui/pinmap.py:134` refuses anything outside 1..99, and the XIAO RP2040's `D6` **is GPIO0**. That field means the rcontrol index of a PICSimLab board, which no XIAO has; `tools/inventory.py`'s `wired` count and README's list are built on it. Writing a GPIO there would have been a second fact in a field that already has one, and it could not even hold the value.

Fix: the join landed beside it. Every pad of all 25 registered files now carries `chip_pin`, `chip_index` and a `why_null`, plus a `pindefs` block naming packages and revisions; four modules carry a generated `HEADER` between markers and derive `PIN_NAMES` from it. `pin` stays null everywhere and the `assumption` says why.

**The ticket's own words were wrong in one place**: "api.py needs no change". The C3's pads are silkscreened `D9/BOOT` and `D3/MTDI` while the packages define `D9` and `D3`, so `webui/api.py` gained `header_key`.

Generalisation: when a ticket says "put the answer in field X", check that X can hold it and that nothing else already means something by it.

### 3.2 OH-160 — a byte comparison against a generated artefact

Symptom, found by the reviewer before it ever ran: the CI fetch step I added clones each board-support package `--depth 1` at today's HEAD, but the committed tables embed the short revision they were read at. Any commit to any of the six repositories would have failed all four modules and all 25 board files at once.

Reproduced by holding the files identical and returning a different revision: pads identical, only `pindefs` differing.

**Ruled out: pinning the fetch to the recorded revisions.** That would verify the tables against the very commits that produced them, so a pin moving upstream could never fail — which is the only reason the step exists.

Fix: `_pins_only` and `_document_pins_only` in `tests/rules/test_import_pindefs.py` blank the revision in both places it appears (the block's citations, and each `on_board` pin's `sources`), and a separate no-fetch test holds the two artefacts to the same provenance.

Generalisation: a check that compares generated output byte for byte will fail on every volatile field it embeds. Normalise the provenance, or the check becomes noise and gets deleted.

### 3.3 OH-161 — a FIFO is not a register, and the core knew it would need this

Symptom: `webui/boards/esp32c3.py` maps GPIO only, and `webui/compile.py` refused `Serial` with a hint. Modelling the UART needs the FIFO to keep every byte; a `map_register` there holds the last one, so `hello` leaves an `o` behind — a plausible letter rather than a loud absence.

`core/riscv32/cpu.h` had said, in its own comment, that the other three mapping behaviours "arrive when an image here faults without them". `map_stream` is the first to arrive on that trigger, mirroring `core/cortexm0`'s, plus one rule that version lacks: a store not carrying byte 0 transmits nothing, because every one of these parts documents the data field as `[7:0]`.

Fix as a command: `python tools/build_core.py && python -m pytest tests/riscv32/test_mmio.py -q` → 31 passed.

### 3.4 OH-161 — the sentence the repository had already refuted

Symptom: my comment in all three modules said UART0 "is the one a XIAO's USB bridge is wired to and the one a `Serial.print` reaches".

**It is false, and this repository recorded the opposite twice before I wrote it.** `docs/research/peripheral-layer/esp32c3/uart-contract.json` (verified 2026-08-24): the XIAO ESP32-C3 has no UART-to-USB bridge and Arduino's `Serial` lands on USB_SERIAL_JTAG at 0x60043000. `third_party/seeed-xiao/document/SeeedStudio_XIAO_ESP32C3/XIAO_ESP32C3_Pin_Multiplexing.md:112-126`: USB serial is the default, and using UART0 means wiring `D6`/`D7` to a USB-serial adapter with USB CDC On Boot disabled.

Fix: the modelling choice survives on the reasons that research file actually gives — UART0 is the ROM console and the target of `esp_rom_printf`, and non-XIAO C3 devkits do bridge it — and all three modules plus `serial.cpp` now say that, quote both sources, and state that a sketch printing here models the vendor's documented alternative wiring.

Generalisation: **search the repository for the fact before asserting it in a comment.** A `grep` for `USB_SERIAL_JTAG` would have found the refutation in one command.

### 3.5 OH-161 — a fix that deleted the fault's address

Symptom, and this one is mine twice over. The reviewer found that the stream's gate lookup read the gate's stored word directly, ignoring `Mapped::target`, so a gate mapped as a readable alias answered its own zero: the peripheral read correctly and transmitted nothing. I fixed it by reading through `mmio_read` — and deleted the `note_fault(address, false)` on the assumption `mmio_read` had already recorded it.

**It has not, and cannot.** `core/riscv32/cpu.cc:302-305`: its `mmio_.find` miss returns false WITHOUT noting, because every other caller falls through to the region lookup afterwards. Measured through executed code:

```
before the fix: pc=0x42000008: access at 0x00000000 refused (unmapped)
after:          pc=0x42000008: access at 0x60000000 refused (unmapped)
```

**Why no test saw it**: `test_a_stream_whose_gate_was_never_mapped_faults_rather_than_capturing` goes through `write_word`, and `core/riscv32/abi.py:374` formats the address the CALLER passed, not `fault_address_`. Only `step()` reads the recorded one.

Fix: the explicit `note_fault` is restored with a comment saying why it cannot be delegated, and `test_an_executed_store_through_an_unmapped_gate_names_the_fifo` drives the path through `step()`. Removing the line again and rebuilding: the old test PASSES, the new one FAILS.

Generalisation: when a fix replaces a direct call with a shared helper, check what the direct call was doing *besides* the obvious thing. And a test that formats its own input can never see what the system recorded.

## 4. Reproduce-the-result runbook

```bash
cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware
git log --oneline -3                      # fb93597, 10bc1e3, ee3b7cc
python tools/build_core.py                # four dlls; riscv32.dll ~198,144 bytes
python tools/checkall.py                  # ~7-9 min ALONE: "all 12 checks pass"
python -m pytest tests/riscv32/ -q -p no:cacheprovider          # 196 passed
python -m pytest tests/webui/test_compile.py -q -p no:cacheprovider   # 61 passed
python tools/import_pindefs.py --write-headers   # 4 unchanged
python tools/import_pindefs.py --write-boards    # 25 unchanged
python -c "from webui import compile as c, api; from webui.boards import esp32c3; \
b=c.build('XIAO-ESP32-C3-DIP','void setup(){Serial.println(\"hi\");}\nvoid loop(){}'); \
s=api.load_firmware('XIAO-ESP32-C3-DIP', b.image, base=c.recipe_for('XIAO-ESP32-C3-DIP').base); \
[s.step() for _ in range(60000)]; print(s.state()['uart']['text']); s.close()"   # hi
```

**Do not run the gate while anything else builds.** Three of this session's four gate runs were green over a tree that was still changing under them, which proves less than it looks; only the fourth was clean. And a killed gate leaves an `openhardware-build-*` directory in `%TEMP%` that fails `test_a_failed_build_leaves_nothing_behind` — delete it.

## 5. File inventory

**Committed in `10bc1e3` (OH-160)** — `tools/import_pindefs.py` (+`--emit-header`, `--write-headers`, `--write-boards`), `webui/api.py` (`header_key`), `webui/boards/{esp32c3,esp32c5,esp32c6,rp2040}.py` (generated `HEADER`, `PIN_NAMES`, `pin_states`), all 25 `webui/boards/*.json`, `tools/inventory.py`, `tools/import_board.py`, `README.md`, `.github/workflows/rules.yml` (the package fetch), `tests/rules/test_import_pindefs.py`, `tests/webui/test_pin_view.py`, `tests/riscv32/test_esp32c3_board.py`, and `docs/tickets/OH-164-*.md` (new).

**Committed in `fb93597` (OH-161 step 1)** — `core/riscv32/{cpu.h,cpu.cc,abi.h,abi.cc,abi.py}` (`map_stream`/`stream`), `core/cortexm0/abi.py` (the twin of a false docstring), `webui/boards/{esp32c3,esp32c5,esp32c6}.py` (UART0), `webui/arduino/cores/openhardware/{Arduino.h,serial.cpp}` (`OhSerial`), the three `webui/arduino/variants/*/oh_board.h`, `webui/compile.py` (the `Serial` hint retired, `serial.cpp` added to `core_sources`), and five test files.

**Scratchpad, session-temp and possibly gone** — `…/scratchpad/{drape,proud_before}.mjs` (the OH-162 before-measurement), `oh161_note.txt`, `oh161_commit.txt`, `audit_citations.py`, `us1_mutate.py`, `us2_mutate.py`, `us3_mutate.py`, `probe13.py`.

**Not in git, and left deliberately** — `build/lib/riscv32.dll.locked-by-pid44724`: see §9.1.

## 6. Measurements this session

### 6.1 The OH-162 before-number

`node …/scratchpad/drape.mjs` on a settled 28-unit wire over a 12 × 3.5 × 6 box:

```json
{"solverKnowsRadius": false, "nodesOverTheBox": 8, "restingCentreY": 2.0381,
 "boxTopY": 3.5, "proud": 0.16, "inside": 0}
```

`proud` = 0.16 is the whole tube radius, meaning at least one node CENTRE lies exactly on a face. After US-4 it must read 0 with `inside` still 0.

### 6.2 The printing sketch, traced byte by byte

18 bytes (`hello\r\nn=-42\r\nx7\r\n`), first arriving at step 39, last at 189, largest gap between two bytes 29 steps. `STALL_STEPS = 20_000` and `PRINT_BUDGET = 200_000` are justified by those numbers, not by the guess ("22 bytes", "a few hundred instructions") that stood there first.

### 6.3 The counts that moved

| what | before | after |
|---|---|---|
| board files carrying a `chip_pin` | 0 | 25 |
| catalogue entries whose chip can report UART output | 3 | 10 |
| board files whose module has `pin_states` | 3 | 12 |
| tests collected | 2,021 | 2,103 |

## 7. Commits this session

```
fb93597 feat(webui): a sketch on an ESP32 board can print, and the bytes reach the pane (OH-161 step 1)
10bc1e3 feat(webui): the resolved pin map reaches the board files and the modules (OH-160)
```

## 8. Review discipline, because it is what found most of this

Two independent architect reviews, 25 findings between them, every one fixed. **Two were code defects** (§3.2, §3.5) and the rest were false or unsourced claims in comments — misattributed line numbers, a miscounted behaviour list, a document section for the wrong architecture, a board count already wrong before I touched it, and three numbers I stated instead of measured.

Mutation testing caught the rest: 24 mutations on OH-161 alone, each failing the test named for it, and **three that proved nothing and had to be replaced** — one dereferenced an end iterator so the process crashed instead of failing, one cleared a bit the next line set again, and one was an arithmetically equivalent rewrite. A mutation that survives is either a test gap or a bad mutation, and telling those apart is the work.

## 9. Known quirks

### 9.1 The stale RISC-V library

`webui/emulator_server.py` (pid 44724, started 2026-08-31) is the user's own long-running process and holds `build/lib/riscv32.dll` open. Windows refuses to overwrite an in-use DLL but allows renaming one, so the old file was moved to `build/lib/riscv32.dll.locked-by-pid44724` and the build wrote a fresh one. **That process was not killed** — it may be serving a browser. The stale file is inside git-ignored `build/` and can be deleted whenever that server stops.

### 9.2 The rest

- `ruff check` reports 4 pre-existing findings across the repo (PYI034, three PLW1510). None are new.
- The gate log truncates pytest's summary line (`... 1 more line(s)`), so read the totals from a separate `pytest -q` run.
- Ralph's stop hook re-invokes on every turn end; `/oh-my-claudecode:cancel` is what ends it, and it should NOT be run until the PRD's remaining stories are done or explicitly abandoned.
- The worktree is CRLF (`core.autocrlf=true`) while blobs are LF. Any script that matches multi-line anchors must normalise newlines, and must treat "anchor not found" as a failure — a mutation script here once reported success while six of its checks had silently not run.
