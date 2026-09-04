# Handoff 2026-09-04 — six tickets closed or blocked, and four filed from two products

| | |
|---|---|
| Date | 2026-09-04 (session ran 2026-09-03 evening to 2026-09-04 early morning, Korea) |
| Repository | `C:\Users\Alexyodude\Desktop\AlexFolder\Code\Github\OpenHardware`, branch `master`, HEAD `a07c8da`, 310 ahead of `origin/master`, tree clean |
| Session id | `d4fefe50-4831-4eaf-950d-b7fd61649b25` (`OH_SESSION_ID` for `tools/tickets.py`); holds no ticket |
| Toolchains | PlatformIO packages: `toolchain-riscv32-esp` (GCC **8.4.0**, esp-2021r2), `toolchain-gccarmnoneeabi` (12.3.1), `toolchain-atmelavr`; Blender 4.5 and 5.1; node; no QEMU, no PICSimLab binary |
| Board support | `third_party/bsp/arduino-esp32` at `2787dab` (fetched, git-ignored); `third_party/bsp/arduino-pico/pico-sdk/` is an EMPTY submodule dir |
| Other sessions | `agent-oh36` still holds **OH-36**. Never take or edit it. |
| Ralph state | cleared by hand (the MCP state tools refuse this cwd as cross-repo); `.omc/state/sessions/<id>/ralph-state.json` removed, `prd.json` there records all 8 stories passing |
| Previous handoff | `docs/HANDOFF_2026-08-31_drawn-or-refused.md` — its open list is all closed; do not resume from it |

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| OH-127 row-spacing disagreement | ACHIEVED (resolved, not refused) | `afd0416`, `2642a11`; measured from `third_party/seeed-pcb/ESP32-C3.kicad_pcb` (§3.1) |
| OH-155 ceramic parts shaded as metal | ACHIEVED | `381c7ac`; `webui/static/models/XIAO-ESP32-C5-DIP.glb` and `XIAO-nRF54l15-DIP.glb` carry 12 tri of `#d9d3c0` at metalness 0.0 (§3.2) |
| OH-156 C5/C6 sketches build and run | ACHIEVED | `3ed645d`, `b2cbe5e`; `tests/webui/test_compile.py` 54 passed; buildable boards 10 of 26 (§3.3) |
| OH-132 penetration probe blind | ACHIEVED, after one review rejection | `eda7788`, `9e0e65a`, `776e5c0`; `tests/webui/test_wires.py::test_a_wire_resting_on_a_box_reports_the_contact_the_collider_resolved` (§3.4) |
| OH-157 RP2350 via Hazard3 | BLOCKED ON a register source | `7d378f3`; ticket status `blocked`, note names the fetch that unblocks it (§3.5) |
| OH-158 prebuilt binaries | ACHIEVED (answered, nothing installed) | `64c22ce`; `docs/architectures.md` §4.6, `catalogue.ORACLES` (§3.6) |
| Independent review of the run | ACHIEVED | architect reviewer: round 1 REJECT on OH-132 only, round 2 APPROVE; it re-ran the gate itself (2,021 passed) |
| Full gate green | ACHIEVED | `tools/checkall.py`: all 12 checks, **2,021 passed / 17 skipped**, run alone (§8) |
| "xplora3d" | ACHIEVED (identified) | user's URLs: `xplora.phinalabs.com/3d/` and `sim86.com` (§4) |
| Four improvement tickets | ACHIEVED (filed) | `a07c8da`: OH-160, OH-161, OH-162, OH-163 (§4) |
| QEMU install for OH-36/OH-64 | NOT STARTED — needs the user's yes | asked in chat; nothing downloaded or installed |

## 2. What is open, top first

1. **OH-160 (P1) — the resolved pin map reaches the board modules and files.** `software-only`. Cold start:
   ```bash
   cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware
   export OH_SESSION_ID=<this session's id, or a new one>
   python tools/tickets.py start OH-160
   python -c "from webui.boards import esp32c3; print(esp32c3.PIN_NAMES)"   # AttributeError today: that is the failing boundary
   python tools/import_pindefs.py XIAO-ESP32-C3-DIP                          # the report that already knows D10 -> GPIO10
   ```
   Step 1 of the ticket: make `tools/import_pindefs.py` EMIT a `HEADER` table (label → GPIO, source file + revision in the generated text) for `esp32c3`, `esp32c5`, `esp32c6`, `rp2040`; the modules derive `PIN_NAMES` from it the way `webui/boards/samd21.py:232` does; `webui/api.py`'s pad listing already reads `PIN_NAMES`. Then fill `pin` in the JSONs from the same generator and add the test that holds JSON == module. Read `docs/tickets/OH-26-*.md`'s 2026-08-25 note first: it names the 8 boards whose pins have no flat integer.
2. **OH-161 (P1) — ESP32 peripherals**: UART TX first (ESP-IDF `uart_reg.h`, same header tree `esp32c6.py` cites), then systimer, GPIO_IN via the solved node voltage, ADC, one I2C part. `software-only`. Claims only `webui/arduino/**`, `webui/compile.py`, `tests/webui/test_compile.py` today; add the board modules to its `touches` when OH-160 has landed, not before (they would collide).
3. **OH-162 (P2) — wire thickness, wire–wire contact, one photograph.** `software-only` for steps 1–3; step 4 `requires hardware` (a phone and a board).
4. **OH-163 (P2) — silkscreen text, default-finish colours, absent-part classes.** `software-only`; step 1 needs a stroke-font licence decision before any glyph is drawn.
5. **OH-157** — `requires a fetch`: pico-sdk's `src/rp2350/hardware_regs/include/hardware/regs/` (initialise the submodule already declared under `third_party/bsp/arduino-pico`, or add a package to `import_pindefs.py`'s registry), plus a decision on how `catalogue.CHIPS` names a two-core part. Do not write `rp2350.py` from memory.
6. **QEMU** — `requires the user's decision`. If yes: `https://qemu.weilnetz.de/w64/qemu-w64-setup-20260811.exe` (sha512 published beside it), then OH-158 step 2: run one cortexm0 image under it and diff. Not before they say so.
7. OH-159, OH-38, OH-64 `require hardware`; OH-9 a PICSimLab binary (prebuilt exists, §3.6); OH-8 and OH-11 traces/microcode that do not exist here. Unchanged.

## 3. Root-cause narratives

### 3.1 OH-127 — the 1.27 mm was two features of one pin
Symptom: Seeed's DIP `.kicad_mod` put the rows 15.240 apart, the PCB "16.510". Ruled out: a vendor error (both files are Seeed's and internally consistent). Cause, measured with a balanced-paren parser over `third_party/seeed-pcb/ESP32-C3.kicad_pcb`: footprint `H7-HALF-HOLE-2.54` drills each pin twice — pads 1–7 (1.5 mm, drill 0.85) at local x 0 → rows 15.240 apart; pads 13–19 (1.27 mm, drill 0.7) at local x −1.27 → rows 17.780 apart, which is exactly the Edge.Cuts height; pad 1/13 share net 27 `D0` … 7/19 share `TX_D6`. The DIP footprint's through-holes ARE the header holes; the SMD-side 16.910/16.165 are host-board lands; 16.510 = 17.780 − 1.270 is the castellations' inner-edge spacing (the reviewer's derivation). No pin position changed. Generalisation: when two vendor numbers "disagree", check they describe the same feature before adjudicating.

### 3.2 OH-155 — a FINISHES key is never local
Symptom: two ceramic slabs borrowed `#c6c4a0`, the TS42 steel cover, metalness 1.0. The ticket offered a "narrow fix" (redeclare that hex at metalness 0). Ruled out by tallying the shipped `.glb` files (`glb_colour_report.py`-style walk over materials by name): `#c6c4a0` is on 13 of 17 boards, both C3s at 604 triangles with no switch and no ceramic — vendor passives use it. Fix: `CERAMIC = "#d9d3c0"` in `tools/import_3d_model.py`, the second labelled judgement beside `BOARD_MASK` (datasheets searched: three Murata LFD PDFs, no colour stated); `FINISHES[CERAMIC] = Finish(0.0, 0.60)`, roughness labelled a judgement. Parts rebuilt in Blender, four boards recomposed, glbs re-read. Generalisation: before touching a keyed table, tally who else uses the key.

### 3.3 OH-156 — three things measured, one sentence deleted
Facts: this GCC 8.4.0 rejects `-march=…_zicsr_zifencei` ("unsupported ISA substring") and knows no Zc; both parts build with `rv32imac`. Delay: 24,043 steps rise-to-rise on C5, C6 AND C3 today (the C3 header's 24,031 is dated 08-31, now annotated). A draft comment blamed `-march` for the 12 steps; building the C5 with `rv32imc` also gave 24,043, so the sentence was deleted — a causal claim in a comment is a claim. Pins: PlatformIO's `framework-arduinoespressif32` 3.20017.241212 ships XIAO_ESP32C3 and S3 only; the C5/C6 tables were already in `third_party/bsp/arduino-esp32` (2787dab, byte-identical to upstream modulo CRLF); `Recipe.bsp_includes` resolves under `BOARD_SUPPORT` with a refusal naming `import_pindefs.py --fetch`. The C6 table `#include "soc/soc_caps.h"` and uses nothing from it → empty shim `webui/arduino/variants/xiao_esp32c6/soc/soc_caps.h`. Mutation trap: the two variants share every basename; a backup keyed by basename restored the C5 header from the C6's copy, caught by the sha check — back up by full path.

### 3.4 OH-132 — the probe was blind, and so was my mutation set
Symptom: `penetration()` read 0.0000 on a wire flush in a box face. Cause: `outOfBox` snaps the node centre exactly onto the face and `collide` runs last, so a strict inside test never sees a resolved contact. Fix: `Rope.contact(radius)` in `wires.js` → `{inside, proud, pinned}`; `penetration()` is one line through it and excludes pinned ends by statement. The 0.289 mm "residual" is a pinned head inside the box (1.75 units = 0.3104 mm at the Uno's 5.638 scale); the radius is 0.0284 mm, so the old "contact tolerance" reading was arithmetically impossible. **Review rejection**: the first `proudOfBox` took the max of near- and far-face terms, so any node over the box reported the full radius at any height (36.5 units of clear air → 0.16). Every fixture I had used TOUCHED the box; the reviewer's did not. Fixed to `radius − near-face gap`; test gained `above` (all zeros) and `near` (0.06 at 0.1 off). Generalisation: include a fixture that should report nothing.

### 3.5 OH-157 — not citable, and three ticket errors
No RP2350 register header, datasheet, SVD or research JSON anywhere (searched `$USERPROFILE/.platformio`, the tree, `docs/research/peripheral-layer/`). Also: `catalogue.CHIPS` maps RP2350 → `cortexm33` (unbuilt), so `rp2350.py` alone cannot flip `runnable`, and moving the row breaks `tests/webui/test_board_catalogue.py:176` and `:510`; GCC 8.4.0 cannot emit Zbb/Zbkb under any flag, so the ticket's "cheap experiment" is unfalsifiable; `tests/riscv32` is flat (`test_<chip>_board.py` + `<x>blink/`), not per-chip directories.

### 3.6 OH-158 — both prebuilts exist; nothing installed
QEMU: `qemu.weilnetz.de/w64/` (the build qemu.org links) lists `qemu-w64-setup-20260811.exe` (QEMU 11.1.0) with a `.sha512`. PICSimLab: GitHub `v0.9.2` win64 setup/zip and a rolling `latestbuild` (0.9.3, 2026-08-30) with win64 and the NOGUI AppImage; no checksum assets. The Android SDK's `qemu-system-armel.exe` on this machine is Google's fork (rejects `-machine`, no Cortex-M) — not an oracle. OH-36's blocker (b) "arm-none-eabi-gcc absent" is stale (12.3.1 is installed and builds the SAMD21 recipe); recorded in §4.6 and OH-158, not in OH-36. The catalogue's comment claiming the C5 was "deliberately absent" from `FIRMWARE_VERIFIED` (three lines above its entry) was corrected in the same commit.

## 4. The two products, and the four tickets
`xplora.phinalabs.com/3d/` — Xplora3D, Phinalabs: an education breadboard for young learners with a physical kit; generic breadboard, snap-to-pin wires, sim with scope/logic analyser, GLB/PNG export, an Environment panel (light/temperature/humidity), a generic "programmable MCU with GPIO", a large generic part library. Engine loads after login (demo credentials are printed on the page); not inspected.
`sim86.com` — Simulator86: professional, instruction-accurate execution of unmodified vendor binaries on named boards (XIAO RP2040/ESP32-C3/nRF52840, Nucleo-F767ZI, STM32F405, Pico 2), per-board pin tables and per-peripheral support tables (its ESP32-C3: UART, I2C validated on hardware, packet-level Wi-Fi, systimer, 31 interrupt sources), parts SSD1306/LCD1602/MPU-6050/BMP280/MCP9808/servo/buzzer, stochastic timing, SDK/MCP/CI, no 3D, no physics. `docs.sim86.com/components/xiao-esp32c3/` is the page worth reading for OH-160/161.
Filed with measured numbers: **OH-160** pins (28 of 582 pads carry a pin; OH-26's report resolves 321 that nothing consumes), **OH-161** peripherals (ESP32 boards map GPIO only; Arduino surface is pinMode/digitalWrite/delay), **OH-162** wires (no thickness in the solver, no wire–wire contact, no photograph), **OH-163** 3D (no silkscreen text on any board, 6–10 default-finish colour groups per board, test points double-reported).

## 5. Reproduce-the-result runbook
```bash
cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware
git log --oneline -12                       # a07c8da at the top, afd0416 twelfth
python tools/checkall.py                    # ~10 min ALONE: "all 12 checks pass", 2,021 passed / 17 skipped
python -m pytest tests/webui/test_compile.py -q -p no:cacheprovider    # 54 passed (~80 s)
python -m pytest tests/webui/test_wires.py tests/webui/test_board3d.py -q -p no:cacheprovider   # 103 passed
python tools/compose_board_3d.py --check    # exit 0, 11 boards; C5 shows "finish #d9d3c0 12 tri metal 0.0 rough 0.60"
python -c "from webui import compile as c; from webui.boards import catalogue; b=catalogue.catalogue(); r=[x for x in b if x.runnable]; print(len(b), len(r), len([x for x in r if x.chip in c.RECIPES]))"   # 26 12 10
OH_SESSION_ID=<id> python tools/tickets.py list   # OH-160/161 P1 open, OH-157 blocked, OH-36 held by agent-oh36
```
**Do not run the gate while anything else builds.** Two server-timing tests (`test_an_upload_from_another_origin_is_refused`, `test_a_state_poll_answers_while_a_build_runs`) failed once under my own concurrent builds and pass alone; the 08-31 handoff's §9.1 diagnosis (load-dependent) stands.

## 6. File inventory
Changed this session (all committed): `tools/import_3d_model.py`, `tools/model_from_datasheet.py`, `webui/compile.py` (`Recipe.bsp_includes`, `_openhardware()` factory), `webui/arduino/variants/xiao_esp32c5/{oh_board.h,link.ld}`, `webui/arduino/variants/xiao_esp32c6/{oh_board.h,link.ld,soc/soc_caps.h}`, `webui/arduino/variants/xiao_esp32c3/oh_board.h` (re-measure note), `webui/static/wires.js` (`Rope.contact`, `depthInBox`, `depthInSphere`, `proudOfBox`), `webui/static/board3d.js` (`penetration`, `contact`), `webui/boards/catalogue.py` (ORACLES, C5 comment), `docs/architectures.md` (§4.6), tests: `tests/rules/test_import_3d_model.py`, `tests/rules/test_compose_board_3d.py`, `tests/webui/test_compile.py`, `tests/webui/test_wires.py`, `tests/webui/test_board3d.py`; tickets OH-127/132/155/156/157/158 (notes) and OH-160..163 (new).
Generated, git-ignored, rebuilt this session: `third_party/modelled/{CAF-50P160X80-6N,ANT2P-5.2x2x1.1MM}.{obj,mtl,json}`; `webui/static/models/XIAO-ESP32-C5-{DIP,SMD}.glb`, `XIAO-nRF54l15-{DIP,SMD}.glb`.
Scratchpad (session-temp, may be gone): `…/scratchpad/oh1{55,56,32}_*.py` mutation and edit scripts, `scout1{32,56,57}/` probes, `proud_probe.mjs`, `t_{pins,periph,wires,3d}.txt` ticket bodies.

## 7. Commits this session, newest first
```
a07c8da docs: four tickets from a look at Xplora3D and Simulator86 -- pins, peripherals, wires, 3D (OH-160..163)
b2cbe5e chore(tests): the C3 build helper is the general one applied to the C3 (OH-156)
776e5c0 docs: two numbers in the OH-132 note corrected after review
2642a11 docs: the 16.510 mm the ticket opened with is the castellations' inner-edge spacing (OH-127)
9e0e65a fix(webui): proud-by-radius measures the near face only (OH-132 review)
64c22ce docs: the prebuilt-binary question is answered either way and recorded (OH-158)
7d378f3 docs: the RP2350's RISC-V route is blocked on a register source, and says why (OH-157)
eda7788 fix(webui): penetration() sees the contact the collider resolved (OH-132)
3ed645d feat(webui): a sketch builds for the ESP32-C5 and C6 and drives their own pins (OH-156)
381c7ac fix(tools): the two ceramic parts are dielectrics in their own colour (OH-155)
afd0416 docs: the 1.27 mm row-spacing disagreement was two features of one pin (OH-127)
```

## 8. Known limitations and quirks not worth chasing now
- The OMC `state_*` MCP tools refuse this repo as "cross-repository" because the CLI session's cwd is `C:\Users\Alexyodude`; use the bash fallback (delete the session-scoped state files) as done here.
- `ruff check` on a `.js` file dumps thousands of syntax "errors"; it is a Python linter. Harmless, noisy.
- Subagents that finish do not always deliver their report; the four scouts here went idle silently and answered only when messaged. One scout ran for three hours until `TaskStop`.
- The gate takes ~10–12 minutes here (it was ~7); still all green when run alone.
- The delay-scaling test cannot see a wrong `OH_DELAY_LOOPS_PER_MS` value (it asserts scaling only); the value is the labelled judgement, and the test docstring says so.
- `test_ast_count_matches_pytest_collection` passed with the new parametrised tests in `tests/webui`; it compares only `tests/rules/`.
