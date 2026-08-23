# Handoff — OpenHardware (2026-08-12)

## Header

| | |
|---|---|
| Repo | `C:\Users\yejun\Desktop\AlexFolder\haas\repos\OpenHardware` (Windows) |
| What it is | Fork of [`lcgamboa/picsimlab`](https://github.com/lcgamboa/picsimlab), GPL-2-or-later |
| Branch | `design/feature-strategy` — **43 commits**, working tree clean |
| Base | `master` at tag `fork-point` = `cd92747b1a04cab56c17f4e9ac35a1406c9935f7` (2026-07-30) |
| HEAD | `44ff7a4b` |
| Remotes | **`upstream` only** (read-only, lcgamboa). There is no `origin`. Nothing has been pushed anywhere. |
| Tests | `172 passed` (`pytest tests/rules/ tests/webui/ -q`) |
| Checkers | 6 of 6 green |
| Upstream files modified | **exactly 1** — `src/lib/board.h`, logged in `docs/upstream-deltas.md` |
| Live simulator | PICSimLab 0.9.3 built and **running in WSL2** on `127.0.0.1:5000` |

### Environment gotchas that each cost a debugging round

- **The WSL user is `root`.** The build clone is `/root/oh`, not `/home/<user>`. `ls /home/` finds nothing.
- **Git Bash rewrites absolute Unix paths passed to `wsl.exe`.** `/home/` became `C:/Program Files/Git/home/`. Always `export MSYS_NO_PATHCONV=1` first. It also silently emptied a `$p` loop variable, producing eleven confident false "MISSING" package results.
- **Never run bare `pytest` from the repo root.** Upstream's `tests/python/` imports the out-of-tree module `PICSimLab_rcontrol` and errors at collection. Always name the suites.
- **Windows console is cp949**; set `PYTHONIOENCODING=utf-8` when output contains em dashes.

---

## TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| Rules machinery (5 rules, checkers, meta-guard) | ACHIEVED | `rules/*.md`, `tools/check_*.py`, commit `90fe15a7` |
| `feature-strategy` skill | ACHIEVED | `skills/feature-strategy/SKILL.md`, `05027e3e` |
| Repo inventory generator | ACHIEVED | `tools/inventory.py`, `f029e141` |
| Board-contract checker (no compiler needed) | ACHIEVED | `tools/check_board_contract.py` — 42/42 virtuals on upstream pair, `c76da89a` |
| 8086 ledger derived | ACHIEVED | `docs/features/i8086.md`, 43 cells, `def1fa04` |
| `ARCH_X86` + first upstream delta logged | ACHIEVED | `src/lib/board.h:40`, `docs/upstream-deltas.md`, `1cf16570` |
| Web UI ledger derived, slice reordered to #2 | ACHIEVED | `docs/features/webui.md`, `d317ef6c` |
| Browser→rcontrol bridge | ACHIEVED | `webui/{rcontrol,api,bridge}.py`, `ed93b6a4` |
| Simulator builds and runs | ACHIEVED | WSL2 Ubuntu 22.04, 1m27s, PICSimLab 0.9.3 |
| Bridge verified against live simulator | ACHIEVED | `tests/webui/test_live_oracle.py`, `52bc0d4a` |
| Peripheral wiring (schemas + API + checker) | ACHIEVED | `webui/parts/`, `6bd2c684` |
| **3D view** | **NOT STARTED** | Sub-project 2. Design decisions made (see §6), no spec, no code. |
| Spec §8.4 (NOGUI emits VCD headless) | BLOCKED ON toolchain | `docs/known-issues.md` 4a.6 — gcc 11.4 ICE in `lto1` |
| Signal-level verification (conduction) | BLOCKED ON upstream | `docs/known-issues.md` 4a.5 — `GetInputCount()` is 0 headlessly |
| 8086 core implementation | NOT STARTED | 43 cells, 42 `planned`, 1 `in-progress` |

---

## Root-cause narratives

### 1. Three parser bugs a stub could not catch

**Symptom.** First contact with a real simulator: 5 of 8 live tests failed instantly. `ApiError: unparseable pin line: '  pin[01] ( PC6/RST) < 0    pin[15] (PB1/~9  ) < 0 '`.

**Ruled out.** Not a connection problem — the banner matched byte-for-byte. Not a framing problem — `version` and `info` parsed fine.

**Root cause.** Three separate bugs, all invisible to the stub because **the stub encoded my reading of the source, so it agreed with my mistakes**:

1. `parse_pins` was written against `pins`, but the formatter at `rcontrol.cc:1095` serves **`pinsl`**. Two `snprintf` calls sat in the range I grepped and I read the wrong one. `pins` is a narrow two-column display.
2. `blist` returns **bare** comma-separated names; only `splist` quotes. The quoted parser returned `[]` — an empty board list, not an error.
3. `add_part` sent `spadd LED`. Real syntax is `spadd "Name" x y` (`rcontrol.cc:1266`), so every call was rejected.

**Fix.** `52bc0d4a`. Each now carries a stub regression test naming the live finding.

**Generalization.** A stub built from your own reading of a spec cannot disconfirm a misreading of that spec. It is a consistency check, not an oracle. Any protocol client needs at least one test against the real server before its parsers are trusted.

### 2. `spwrcfg` and `spadd` both require quotes; unquoted silently corrupts

**Symptom.** `spadd` returned ERROR for every name. Later, `write_part_config` was found sending `spwrcfg {index} {config}` unquoted.

**Root cause.** `rcontrol.cc:1307` — `sscanf(cmd + 8, "%d \"%511[^\"]\"", &pid, scfg)`. Without literal quotes the conversion never matches, so **`scfg` is left uninitialised** and handed to `ReadPreferences`. Same trap at `rcontrol.cc:1266` for `spadd`.

**Fix.** `9e60b0c6` collapsed the duplicate methods into delegates so each command has exactly one construction site.

**Generalization.** When a C server parses with `sscanf` and a literal-quote format, an unquoted argument fails *silently with garbage* rather than erroring. Grep for every construction site of a command, not just the one you are editing.

### 3. The server's arity guard is one-sided

**Symptom.** A docstring claimed the server rejects any arity mismatch, citing `rcontrol.cc:1310`.

**Measured live on 0.9.3:**
```
OVER-ARITY  (12 fields): ACCEPTED — extra field silently dropped
UNDER-ARITY  (3 fields): REJECTED
```

**Root cause.** `Part->ReadPreferences(scfg)` returns `sscanf`'s assignment count, which can never exceed the format's conversion count. Over-arity is undetectable server-side. The real over-arity guard is this client's own `_values()` check, and only on a later *read*.

**Fix.** `6bd2c684` rewrote the docstring to name the correct layer.

**Generalization.** A guard that returns a count derived from a fixed-size format can only detect *too few*, never *too many*. Verify both directions before documenting a guard.

### 4. `connect()` accepted out-of-range pins that wrapped silently

**Symptom.** `connect(index, schema, "B1", 300)` → accepted, read back **44**. `-1` → **255**.

**Root cause.** Config fields are `%hhu`; values wrap mod 256. `connect()` never read back, so a caller wiring pin 300 was told it succeeded.

**Fix.** `6bd2c684` added a `0..255` range check in `_set_field`, raising `SchemaError` naming the label.

**Generalization.** Miswiring-reported-as-success in the very API built to prevent it. Any write path whose wire format narrows the value needs a range check at the boundary.

### 5. I propagated a reviewer's claim without checking it

**Symptom.** I instructed a fix agent to write into the spec that "no bulk-delete command exists in the protocol."

**Root cause.** The final reviewer asserted it; I relayed it. **I had read the contradicting branch earlier in the same session.** `spdel all` is real at `rcontrol.cc:1276`, dispatching to `CSpareParts::DeleteParts()` (`spareparts.cc:89`).

**The fix agent refused to write it**, citing the project's own thesis that a claim exceeding its evidence is the second-worst defect. It was right.

**Generalization.** A reviewer's factual claim is evidence, not proof. Verify before propagating — especially when it contradicts something you already read.

---

## Reproduce-the-result runbook

From a cold start on this machine:

```bash
# 1. Verify repo state
cd /c/Users/yejun/Desktop/AlexFolder/haas/repos/OpenHardware
git log --oneline -1                      # expect 44ff7a4b
git diff --name-status cd92747 HEAD | grep -v '^A'   # expect exactly: M src/lib/board.h

# 2. Run the suites (NEVER bare pytest here)
export PYTHONIOENCODING=utf-8
python -m pytest tests/rules/ tests/webui/ -q         # expect 172 passed

# 3. Run all six checkers
for c in layering board_contract part_schemas licenses deltas banned_symbols; do
  python tools/check_$c.py; done                      # each prints "...: OK"

# 4. See what is in the repo (computed, never hand-maintained)
python tools/inventory.py

# 5. Start the simulator in WSL (required for live tests)
export MSYS_NO_PATHCONV=1
wsl -d Ubuntu-22.04 -- bash -lc 'cd /root/oh/src && DISPLAY=:0 setsid nohup ./picsimlab /root/oh/tests/blink/blink.pzw >/root/picsimlab.log 2>&1 </dev/null &'
sleep 8
wsl -d Ubuntu-22.04 -- pgrep picsimlab                # expect a pid

# 6. Enable spare parts, then run the live tests
python -c "from webui.rcontrol import RControlClient; c=RControlClient(port=5000,timeout=8); c.connect(); c.command('spshow 1'); c.close()"
OPENHARDWARE_LIVE=1 python -m pytest tests/webui/test_live_oracle.py -v   # expect 13 passed
```

**If a live test errors**, check the simulator is still alive before debugging anything else — it crashes under repeated part placement (`docs/known-issues.md` 4a.7). Restart with step 5.

**The `/root/oh/share/picsimlab -> /root/oh/share` symlink must exist**, or placing a part **segfaults** the simulator (4a.1, 4a.2). Verify: `wsl -d Ubuntu-22.04 -- ls -ld /root/oh/share/picsimlab`.

### Rebuilding the simulator from scratch (~1m30s)

```bash
wsl -d Ubuntu-22.04 -- bash -lc 'rm -rf ~/oh && git clone -q /mnt/c/Users/yejun/Desktop/AlexFolder/haas/repos/OpenHardware ~/oh && cd ~/oh && bash bscripts/install_deps.sh && bash bscripts/build_all_static.sh'
wsl -d Ubuntu-22.04 -- ln -sfn /root/oh/share /root/oh/share/picsimlab
```

---

## File inventory

### Tooling (`tools/`)

| File | Purpose |
|---|---|
| `rules_meta.py` | Parses `rules/*.md` frontmatter. Raises on malformed. |
| `check_layering.py` | `sim_backend/` may not include `parts/` or UI. |
| `check_board_contract.py` | A `bsim_*`/`board_*` pair covers all 42 pure virtuals. |
| `check_licenses.py` | No v2-only GPL headers; new `.py` carry headers. |
| `check_deltas.py` | Upstream edits must be logged, `## ` heading lines only. |
| `check_banned_symbols.py` | No `rand`/`time`/`clock` in new sim code, comment-aware. |
| `check_part_schemas.py` | Every schema cites a resolvable `file:line`. |
| `ledger.py` | Feature-ledger parser. Raises on malformed rows. |
| `inventory.py` | Computes tests/mechanisms/files/ledgers. `--markdown` for pasting. |

### Web UI (`webui/`)

| File | Purpose |
|---|---|
| `rcontrol.py` | Protocol client. Frames on `\r\n>`. Every failure raises. |
| `api.py` | Typed operations; every command cited to `rcontrol.cc`. |
| `bridge.py` | Websocket endpoint. Serialised, loopback-only, Origin-checked, allowlisted. |
| `parts/schema.py` | Part schema loader/validator. |
| `parts/schemas/*.json` | 3 schemas: Push Buttons (verified), LEDs, LED Matrix. |

### Docs

| File | Purpose |
|---|---|
| `docs/known-issues.md` | **Read this first.** §4a upstream defects, §4b schema blind spots, §4c weak tests. |
| `docs/upstream-deltas.md` | The one logged delta. |
| `docs/features/{i8086,webui}.md` | Ledgers. |
| `docs/superpowers/specs/` | 2 specs (feature-strategy, peripherals). |
| `docs/superpowers/plans/` | 4 plans. |

### WSL-side state (not in git)

| Path | What |
|---|---|
| `/root/oh` | Build clone, WX GUI build, `share/picsimlab` symlink applied |
| `/root/oh/src/picsimlab` | The working 27MB binary |
| `/root/ngtree` | NOGUI attempt tree — unlinkable, kept for diagnosis |

---

## Open work / next priorities

1. **Answer the pending integration question** *(software-only, needs the user)*.
   The user was asked and has not replied: merge `design/feature-strategy` into `master` locally, push and open a PR, or keep the branch as-is. **Option 2 requires them to create a GitHub fork first** — the only remote is read-only `upstream`. Re-ask in one line; do not merge without an answer.

2. **Start the 3D view sub-project** *(software-only)*.
   This was half the user's original request and has **not been started**. Run `Skill(skill="feature-strategy")` for the area, or brainstorm first. The decisions already made, which the spec must honour:
   - The user chose **true 3D models per component**, not pseudo-3D.
   - **PICSimLab has zero 3D geometry** — no OpenGL/WebGL/mesh/vertex/`.obj`/`.gltf` anywhere in `src/`. Every part is a 2D `part.svg`. This is a content pipeline before it is a renderer.
   - Part classification (52 real parts; `Common` is shared IC body art, not parts): **~6 need no geometry** (VCD Dump/Play, Signal Generator, Text Box, Transfer Function, Virtual Term), **~26 procedural** (LEDs, 7-seg, buttons, pots, keypad, LDR, NTC, TO-92 sensors, buzzer, DIP-8 memories, **Jumper Wires** — pure bezier tube and the part that makes wiring legible in 3D), **~16 KiCad candidates** (sensor breakouts, LCD modules, SD, HC-SR04), **~4 bespoke** (motors, gamepad).
   - **KiCad 3D models are CC-BY-SA 4.0.** The exception waives article 3 only for *electronic designs*, not for redistributing the library. **Resolution: fetch, don't vendor** — a `bscripts/get_3d_models.sh` like the existing engine fetches, so this repo redistributes nothing and `gpl-hygiene.md` §3 stays satisfied without forcing GPL-3.

3. **Upgrade `gpl-hygiene.md` §3 to SCRIPT-ENFORCED** *(software-only)*.
   The rule wrote its own trigger — "the moment a second or third dependency shows up" — and it has fired. There are now three (PyYAML, pytest, websockets). Recorded as `docs/known-issues.md` 3.4. Needs a dependency manifest plus `tools/check_dependencies.py`.

4. **Close spec §8.4** *(requires a different toolchain)*.
   NOGUI cannot be linked here: gcc 11.4 dies with `lto1: internal compiler error`. Removing `-flto=auto` does not help — the dependency archives from `build_all_static.sh` carry LTO IR. Needs the whole chain rebuilt without LTO, or a different compiler. `docs/known-issues.md` 4a.6.

5. **Slice 3: the 8086 core** *(software-only)*.
   43 cells in `docs/features/i8086.md`. `SingleStepTests/8088` (MIT, hardware-generated, 10k tests/opcode with per-cycle bus traces) is the oracle; strategy recommends targeting the **8088** because it is the only x86-16 part with a hardware oracle. `docs/superpowers/plans/2026-08-09-i8086-core.md`.

---

## Commits this session

43 commits, `cd92747..44ff7a4b`. Newest first (see `git log --oneline cd92747..HEAD` for the full list):

```
44ff7a4b docs: record which tests constrain less than their names suggest
8fe39fe0 docs: record that the simulator crashes under repeated live-test runs
e69d9385 docs: record what a wrong part schema can still do undetected
0c33fa91 docs(webui): cite exact source lines for the spdel all correction
6bd2c684 fix(webui): correct arity-guard claim, reject out-of-range pins, fix spec
fda5b14c fix(webui): narrow what push_buttons `verified` claims to prove
14e1e570 test(webui): verify Push Buttons wiring against a live simulator
f2ce58c3 feat(rules): require part schemas to cite a checkable line
9e60b0c6 fix(webui): collapse duplicate part-config wire-format methods
e36270cd feat(webui): add schema-aware wiring API
70afe367 feat(parts): add schemas for Push Buttons, LEDs, LED Matrix
722879d9 fix(test): strengthen pin_fields position test with interleaved fixture
78cc02ea feat(parts): add part schema loader
```

---

## Known limitations / do not waste time on these

- **A schema with the right fields in the wrong order is undetectable.** `connect()` writes and `read_wiring()` reads through the same positions, so any transposition round-trips clean. Only a human re-reading the cited `sprintf` catches it. This is why `verified` claims arity and storage, **not** layout. Full statement in `docs/known-issues.md` §4b.
- **Round-trip proves configuration, not conduction.** Nothing shows a wire carries signal; that needs `get part[N].in[M]`, which returns ERROR on a headlessly placed part.
- **`set pin[]` is accepted but not observable** on an Arduino Uno — `set pin[04] = 0` and `= 1` both leave `get pin[04]` reporting 16. Poking MCU pins is not a viable UI path. Pinned by `test_pin_writes_are_not_observable_via_get_pin`.
- **`get board.in[]`/`board.out[]` ERROR on Uno** — it has no on-board controls. Board-dependent; boards like PICGenios have them.
- **The browser WASM build is not reproducible** from this repo: no build script, no CI, `template.html` and `src/assets` both absent though linking requires them, and hardcoded sibling checkouts. It also links no QEMU, so **ESP32/STM32 cannot run in a browser** at all.
- **Several tests constrain less than their names suggest** — `docs/known-issues.md` §4c. Notably `test_no_shipped_schema_claims_verification_it_has_not_earned` only checks for the substring `round-trip`, so a hand-written value passes it.
- **CI has never run.** `.github/workflows/rules.yml` needs the `fork-point` tag pushed to a remote, which cannot happen until an `origin` exists. The workflow now fails with an actionable message rather than confusingly.
