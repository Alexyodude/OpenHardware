# The peripheral layer — architecture-independent design

**Author: the `stm-soc` agent.** Recorded here verbatim in substance because it
previously existed only inside prompt text, which meant the agents told to
"build on it" had nothing to read. Not yet adopted into the repository: this is
research output, and adopting it needs a ticket. Do not cite it as settled
repo policy.

*Fidelity-checked by stm-soc 2026-08-24. Four engine-facing clarifications
from the follow-up spec sent to stm-soc-2 were folded in: the `when` argument
on `ready-follows`, the hidden-latch rule for `self-clearing`, the `counter`
argument names, and the whole-peripheral granularity of `hw`.*

*Revised 2026-08-24 after esp-soc's ESP-IDF verification: ESP32 TIMG START
reclassified `rw` (software-bracketed on C3), the hidden-latch rule re-homed to
nRF `TASKS_*`/`EVENTS_*`, the spin detector amended to per-address counters
that survive interleaved reads and reset on value change, and the write clause
of the data-vs-code rule made explicit with WDT as the canonical case.*

*Extended 2026-08-24 (second round, convergent findings routed by team-lead):
multi-source `follows` adopted (forced independently by ESP32-C3 TIMG RDY and
RP2040 PLL LOCK); write-modifies-sibling and FIFO-derived fields ruled coded,
not schema growth; per-vendor drafting sources corrected (Espressif: IDF
headers electing MIT, not the SVD); contract files for coded peripherals and
chip-file `verified:` adopted; board layer housed in the existing
`webui/boards/` format via a per-pad `gpio` field.*

*Third round 2026-08-24: `atomic_aliases` scoping adopted (`applies_to` bus
list plus required per-peripheral `bus` when declared — rpi-soc-2's mechanism,
tightened with checker enforcement); FC0 ruled `coded:` (write-triggered
status plus computed RESULT); rpi-soc-2's negative sweep of RP2040 boot spins
recorded against the detector.*

*Fourth round 2026-08-24: per-column drafting confidence added after
stm-soc-2 caught `STM32C031.svd` declaring a reset value two independent ST
sources contradict — offsets/bits from SVD, reset values corroborated via RM
prose and CMSIS, `verified:` strings naming both; RM0490's one-heading PDF
extraction lag recorded; esp-soc-2's finding that C3's clock path contains no
polled spin appended to §4.*

*Fifth round 2026-08-24: the bus-allowlist alias scoping was disproven by
rpi-soc-2 from datasheet §2.1.2 (SIO is the only exclusion; SSI has
interposer-backed aliases outside APB) and inverted — default-aliased with
per-peripheral `"atomic_aliases": false` opt-out, `bus` demoted to
documentary, checker requirement moved to citing the datasheet's exclusion
list; UART interposer +2-cycle cost recorded as a fidelity gap.*

*Sixth round 2026-08-24, validation: kind 5 confirmed on both remaining ST
examples (SVD field text for STRT and ADCAL, plus the no-software-clear
absence argument), so the kind no longer rests on the example TIMG's demotion
removed; the per-column reset policy has its reference implementation —
`stm32c0/rcc.json` ships `CR.reset 0x1500` against the SVD's `0x500`, with a
`reset_note` and a `verified:` string carrying separate corroboration chains
for offsets and resets; C0 confirmed PLL-free with a three-loop no-crystal
boot path (HSIRDY, ACR.LATENCY, SWS==SW), against the doc's G0-sourced four;
and the evidence bases of the two newest features are recorded as narrow —
`atomic_aliases` scoping is driven by RP2040 alone, multi-source `follows` by
ESP32-C3 and RP2040, and neither arises anywhere in the C0 minimum set.*

*Seventh round 2026-08-24, at team-lead's request: the evidence ladder (with
the absence argument named and both producing instances), the
content-not-presence requirement on `verified:` (precedent verified at
README.md:128-129), and the adoption tally written in as §6.*

*Eighth round 2026-08-24: three framings from the session lead's
`verification-vocabulary.md` (now superseded, per its own header) folded in —
strength-not-cost on the ladder, the negative-results bound on the detector's
tally row, and the empirical sharpening of the alias-scoping caution.*

*Ninth round 2026-08-24: the Espressif drafting reasons ranked with the
licence asymmetry decisive (esp-soc); the CSR spin-risk requirement — the
C3's delay-based boot trading MMIO spin risk for cycle-counter spin risk —
added to §3 as the RISC-V instance of the in-core time-source rule, CSR
number marked unverified, requirement not.*

Grounded against: `core/i8086/abi.h` (flat `i8086_*` ABI, opaque handle, POD
out-params), `core/i8086/exec_core.cc:150-165` (the `kOpenBus` comment already
names OH-9's board model as "the seam it replaces"), `webui/parts/schemas/*.json`
plus `tools/check_part_schemas.py` (JSON schemas with checkable `source:`
citations and dated `verified:` fields), `tools/draft_part_schemas.py`
(mechanical drafting precedent).

Evidence base for the taxonomy: four verified STM32 HAL loops, pico-sdk
`resets.c` / `xosc.c` / `pll.c` / `clocks.c`, and the ESP32 `TIMG_RTCCALICFG`
calibration poll.

---

## 1. Eight field kinds, plus one bus-level decorator

1. **`rw` — storage.** Config registers (MODER, CTRL). Serves read-modify-write
   and the HAL's dummy-readback-after-clock-enable. Mis-modelled as reads-zero,
   RMW silently wipes earlier config — *not* a hang, and worse than one:
   firmware runs with wrong config and the LED is simply dark. STM32's
   `FLASH_ACR` latency wait is this kind; the poll only needs the written field
   to read back.

2. **`ready-follows` — wait-for-SET, causal.** A status bit hardware sets
   *because of* an earlier enable write: PLLRDY←PLLON, HSIRDY←HSION, RP2040
   `XOSC.STATUS.STABLE`←ENABLE, `PLL.CS.LOCK`, `RESETS.RESET_DONE[n]`←(RESET[n]
   cleared — note the source polarity is **inverted** there), nRF
   `EVENTS_HFCLKSTARTED`←`TASKS_HFCLKSTART`. Reads-as-zero means an infinite
   spin before `main`. Model: the read derives from the named source field.
   Hardwiring 1 also boots, but lies to firmware that checks not-ready-before-
   enable; deriving costs nothing. In the JSON this is `follows: "REG.FIELD"` with
   optional `when: "set" | "clear"` (default `set`); RP2040 RESETS is the
   `clear` case.

   **Multi-source `follows` (adopted 2026-08-24).** Two vendors independently
   forced it, which is the closed-vocabulary bar: ESP32-C3 TIMG RDY's true
   source is `START` **OR** `START_CYCLING` (which resets to 1), and RP2040
   `PLL.CS.LOCK` follows `PWR.PD==0` **AND** `PWR.VCOPD==0` (PWR resets 0x2d,
   fully powered down, so `pll_init` must clear both). Grammar: `follows` is a
   string or a list; `op: "and" | "or"` is required exactly when it is a list;
   `when` applies uniformly to every source. So:
   `{"follows": ["CFG.START", "CFG.START_CYCLING"], "op": "or", "when": "set"}`
   and
   `{"follows": ["PWR.PD", "PWR.VCOPD"], "op": "and", "when": "clear"}`.
   The boundary stays hard: no nesting, no per-source polarity, one operator.
   A condition needing more routes to `coded:`; mixed polarity waits for a
   chip to force it. `RESET_DONE = NOT RESET` is not a third case — single
   source with `when: "clear"` already says it.

3. **`mirrors` — wait-for-MATCH.** A read field reflecting a value written
   elsewhere, possibly transformed. `RCC.CFGR.SWS` ← `SW` is identity. RP2040
   `CLK_SYS.SELECTED` ← `CTRL.SRC` is **one-hot**: SELECTED = 1<<SRC, and an
   identity mirror hangs the pico-sdk loop
   `while (!(clocks_hw->clk[i].selected & (1u << src)))`. Transform vocabulary
   stays closed: `identity | onehot`. Grow it only when a chip forces a third.

4. **`clears-instantly` — wait-for-CLEAR.** Busy/sync flags firmware polls to
   zero: SAMD21 `SYNCBUSY` (pervasive — every GCLK write), STM32 `FLASH.SR.BSY`,
   I2C busy. Correct model: read 0 always.

   **This is the polarity trap.** A "return 0xFFFFFFFF for unknown status"
   default fixes kind 2 and hangs kind 4; "return 0" fixes 4 and hangs 2. No
   constant read satisfies both polarities — that is the whole reason per-field
   kinds must exist, and why Renode resorts to alternating reads for unmodelled
   space.

5. **`self-clearing` — command bits.** Write 1 starts an action; the correct
   model reads back 0 (instant completion): STM32 `ADC.CR.ADCAL` (firmware polls
   *the same bit* for clear), flash erase `STRT`, and nRF `TASKS_*` trigger
   registers (write-only, read as zero). **Not** ESP32 `TIMG_RTCCALICFG.START`:
   on ESP32-C3, `rtc_time.c` brackets every one-shot calibration
   CLEAR→SET→poll→CLEAR — software manages the bit explicitly, so START is
   kind 1 `rw` there and `RDY` is kind 2 with `when: set` (esp-soc, verified
   against ESP-IDF master). Reads-as-written hangs the ADCAL poll — this is
   the kind that breaks the otherwise-safe default in §4. Engine rule: a
   self-clearing write sets a *hidden stored latch* while the visible read
   stays 0, and `ready-follows` references the stored latch, not the visible
   value. The motivating case is nRF: `TASKS_HFCLKSTART` always reads zero, so
   `EVENTS_HFCLKSTARTED` (kind 2) must follow the latch or it would read 0
   forever and hang. (Both ST examples subsequently confirmed by stm-soc-2 from
   SVD field descriptions — a source immune to the RM extraction hazard — and
   STRT additionally by absence: `stm32c0xx_hal_flash_ex.c` sets it in two
   places and clears it nowhere, and if software never clears it, hardware
   must.)

6. **`w1c` / `rc_w0` — event flags with explicit clear polarity.** STM32 EXTI
   `PR` clears on write-1; STM32 TIM `SR` clears on write-*0*. Mis-modelled as
   `rw`, the ISR's clear does not take, the flag re-reads set, and the handler
   livelocks — a hang wearing an interrupt-storm costume, distinct from a boot
   spin and nastier to diagnose.

7. **`counter` — time-advancing reads.** TIM CNT, RTC, cycle counters. Derived
   on read from virtual cycles (`value = (cycles / divisor) mod 2^width`,
   direction up/down), never stored per-tick, never host time
   (`rules/determinism.md`). A frozen counter is the *generalised* STM32
   double-trap: every HAL timeout escape hatch is tick arithmetic, so freezing
   converts all recoverable timeouts into hangs, and busy `delayMicroseconds`
   loops poll these at full speed. (JSON args: `divisor`, `width`,
   `direction: "up" | "down"`.)

8. **`hw` — the code escape hatch.** Anything whose reads are impure or that
   touches the observable world: GPIO ODR/IDR/BSRR (pin events out, button
   state in), UART data and FIFO flags (TXE waits are data-flow, not
   enable-flow; an RX read pops a FIFO), read-to-clear status. Granularity is
   whole-peripheral — `coded:` in the chip file; field-level `hw` inside a
   regmap is deliberately deferred until a peripheral that is 90% data with one
   impure register makes it hurt.

**The rule that decides data vs code:** *if every read is a pure function of
stored state plus virtual time, and every write only stores, it is data;
otherwise it is code.* Read-impurity also matters for tracing — a logger must
never double-pop a FIFO by "peeking".

The **write clause** earns its keep on watchdogs, which every chip will pose: a
fed watchdog passes the read side but fails "every write only stores" three
ways — FEED stores nothing, write-protect registers gate the writability of
*sibling* registers, and expiry is a time-triggered global side effect attached
to no access at all. WDTs route to `coded:` with no schema growth. Likewise
ESP32 `RTCCALICFG1.VALUE` — arithmetic over two fields and chip constants — is
pure-on-read but expressible by no kind; it goes to `coded:`, not into a grown
transform vocabulary. That is the closed-vocabulary guard working as intended.

Two rulings on patterns flagged `kind_uncertain` (rpi-soc-2), recorded so they
are not re-litigated per chip. **Write-modifies-sibling registers** — RP2040
SIO `GPIO_OUT_SET/_CLR/_XOR` are real registers whose write ORs/ANDs/XORs a
sibling, and all eight kinds are read-described. No ninth kind and no modifier
yet: every instance seen so far (SIO GPIO, STM32 BSRR, nRF OUTSET/OUTCLR) sits
on a world-observable GPIO block that is `coded:` regardless, so the schema
never meets the pattern. If it ever appears on a pure-data peripheral, extend
with a write-effect *modifier* on a field — kinds stay read-described — and
not before. **FIFO-occupancy-derived fields** — PL011 `UARTFR.TXFF/RXFE/BUSY`
derive from queue state, not from another field. Already answered by
whole-peripheral granularity: the UART is `coded:`; in the coded model TX
drains instantly so TXFF reads 0 and `printf` never blocks, while RXFE
reflects genuinely injected input (blocking on an empty RX queue is correct
behaviour, not a bug). `UARTFR` being pure-on-read does not pull the
peripheral into data — the unit of routing is the peripheral, and its data
register pops. **A third ruling (rpi-soc-2): RP2040 FC0** — `RUNNING`/`DONE`
are triggered by a *write to a different register* (`FC0_SRC`), an event, not
a stored level, which is outside what `follows` derives from; and `FC0_RESULT`
must read a plausible computed frequency, the same arithmetic shape as ESP32
`RTCCALICFG1.VALUE`. Both clauses route FC0 to `coded:` — the second alone
would suffice. Tier-2, not on blink's path.

**Bus-level decorator: atomic alias regions.** RP2040 mirrors every peripheral
at +0x1000/+0x2000/+0x3000 as XOR/SET/CLR views, and pico-sdk uses
`hw_set_bits`/`hw_clear_bits` constantly. This is an address-decode property
declared once per chip, not a register kind; without it, writes land nowhere and
firmware silently runs unconfigured. STM32's BSRR is the same idea as a
dedicated register (kind 8). The decorator is chip-wide with named
exclusions, not bus-scoped: on RP2040 only SIO lacks it, expressed as a
per-peripheral opt-out (see the corrected scoping rule in §2).

---

## 2. How a peripheral is described

Assessment of the three candidate forms:

- **Renode `.repl`** solves *platform assembly* — instances at addresses, IRQ
  wiring, inheritance. Register *semantics* still live in C# classes. Adopt the
  idea, not the format.
- **Plain code for everything** fails the repetition test: RCC / RESETS /
  CLKCTRL / SYSCTRL blocks are dozens of near-identical "field, kind,
  source-field" declarations across chips, and per-register citations become
  uncheckable prose in comments.
- **Data for everything** fails at GPIO and UART: a schema grown until it can
  express a FIFO with read side-effects is a bad programming language.

**Proposal: both, split by the read-purity rule — and in JSON**, following the
convention this repo already enforces. Not TOML or YAML:
`webui/parts/schemas/*.json` plus `check_part_schemas.py` already established
the house pattern of JSON with a checkable `source` citation and a dated
`verified` field, and the *why* lives in first-class `why` fields that a checker
can require — better than comments, which no tool can demand.

### Chip file (the `.repl` role) — `chips/stm32c031.json`

```json
{
  "chip": "STM32C031C6",
  "cpu": "cortex-m0plus",
  "source": "RM0490 rev 3 §2.2 memory map",
  "memory": [
    {"name": "flash", "base": "0x08000000", "size": "0x8000", "alias": "0x00000000",
     "why": "BOOT0=0 aliases main flash at zero; the core fetches SP/PC from the alias"},
    {"name": "sram",  "base": "0x20000000", "size": "0x3000"}
  ],
  "atomic_aliases": null,
  "peripherals": [
    {"name": "RCC",    "base": "0x40021000", "model": "regmap:stm32c0/rcc.json"},
    {"name": "FLASH",  "base": "0x40022000", "model": "regmap:stm32c0/flash.json"},
    {"name": "PWR",    "base": "0x40007000", "model": "stub"},
    {"name": "GPIOA",  "base": "0x50000000", "model": "coded:stm32_gpio", "args": {"port": "A"}},
    {"name": "USART2", "base": "0x40004400", "model": "coded:stm32_usart", "irq": 28}
  ]
}
```

`"model": "stub"` is a name-only declaration; it earns its keep in §4. On RP2040
this file carries
`"atomic_aliases": {"xor": "0x1000", "set": "0x2000", "clr": "0x3000"}`.

**Scoping (corrected 2026-08-24 — the first mechanism was disproven).** The
first adopted mechanism scoped aliases by bus (`applies_to: ["apb"]` plus a
checker-required per-peripheral `bus`). rpi-soc-2 disproved it from the
datasheet: RP2040 §2.1.2 names SIO as the *only* block without atomic access
at the bus level, while SSI — at 0x18000000, nowhere near APB — explicitly
*has* aliases via a bus interposer, and pico-sdk's `hw_set_bits` performs no
bus check and is used routinely on DMA (0x50000000) and PIO (0x50200000). Bus
membership does not decide alias presence; SIO's out-of-APB base was a
coincidence of one peripheral, not the rule. **Mechanism now: the chip-level
declaration applies to every peripheral by default, and an excluded block
carries `"atomic_aliases": false`** — on RP2040, SIO alone. `bus` may be kept
as documentary metadata but gates nothing, and the checker no longer requires
it. The failure modes favour this direction too: forgetting SIO's opt-out is
latent, because firmware never addresses aliases the SDK knows do not exist,
whereas the allowlist's forgotten opt-in actively misrouted `hw_set_bits` on
DMA/PIO/SSI into latch space. What the checker requires instead: an
`atomic_aliases` declaration must be covered by the chip file's
`source`/`verified` naming the datasheet section that defines the aliases
*and its exclusion list* — the exclusion set is a datasheet fact no
file-local check can derive. Fidelity note, not correctness: on hardware the
interposer peripherals (I2C, UART, SPI, SSI) pay +2 system-clock cycles per
atomic write; no model records that, which matters for cycle-accurate work
only, never for boot-to-blink.

### Regmap file (data peripheral) — `peripherals/stm32c0/rcc.json`, abridged

```json
{
  "peripheral": "RCC",
  "size": "0x400",
  "source": "RM0490 rev 3 §5.4; drafted from STM32C031.svd",
  "verified": "2026-08-24 covers the four boot spins in stm32g0xx_hal_rcc.c as read; not yet traced against Renode or hardware",
  "registers": [
    {"name": "CR", "offset": "0x00", "reset": "0x00000500", "fields": [
      {"bits": "8",  "name": "HSION",  "kind": "rw"},
      {"bits": "10", "name": "HSIRDY", "kind": "ready-follows", "follows": "CR.HSION",
       "why": "HAL_RCC_OscConfig spins on HSIRDY; its HAL_GetTick timeout is dead without SysTick, so this bit must never read stuck-0"},
      {"bits": "24", "name": "PLLON",  "kind": "rw"},
      {"bits": "25", "name": "PLLRDY", "kind": "ready-follows", "follows": "CR.PLLON"}
    ]},
    {"name": "CFGR", "offset": "0x08", "reset": "0x00000000", "fields": [
      {"bits": "0-2", "name": "SW",  "kind": "rw"},
      {"bits": "3-5", "name": "SWS", "kind": "mirrors", "source": "CFGR.SW", "transform": "identity",
       "why": "HAL_RCC_ClockConfig polls SWS until it equals SW; the switch is instantaneous here"}
    ]},
    {"name": "IOPENR", "offset": "0x34", "reset": "0x00000000", "fields": [
      {"bits": "0-5", "name": "GPIOEN", "kind": "rw",
       "why": "HAL does a dummy readback after each enable; storage is sufficient, gating is not modelled"}
    ]}
  ]
}
```

The engine interpreting this is small: a read gathers fields and applies kind
rules against stored state plus `cycles`; a write stores and applies clear-
polarity rules. One engine, table-driven pytest per kind, N chips of data.

**Contract files for `coded:` peripherals (adopted 2026-08-24, proposed by
esp-soc).** A coded peripheral otherwise escapes the `source`/`verified`
checker entirely — a real hole. It therefore carries a regmap-shaped
`*-contract.json` with exactly two extra fields: `role: "contract"` and
`coded_because` (one sentence naming which clause of the data-vs-code rule
routed it). The engine must refuse to interpret a contract file as a regmap —
loading one is an error, not a warning. Contract files feed the conformance
fixtures for the coded model and the spin-log symbolizer, so a poll inside a
coded peripheral still logs by register name. **Chip files carry a top-level
`verified:`** like regmaps (also adopted): a chip file asserts base addresses
and a memory map, and dated evidence is the convention for asserted facts.

Two force multipliers. **Regmaps are draftable from vendor CMSIS-SVD files** —
names, offsets and reset values mechanically, with a human adding `kind` and
`why` — exactly as `draft_part_schemas.py` drafts part schemas. The drafting source is
per-vendor, and licence and completeness both decide it (verified by esp-soc
and rpi-soc-2 respectively): **Espressif** — draft from ESP-IDF's
`soc/*_reg.h` headers, which carry `SPDX-License-Identifier: Apache-2.0 OR
MIT`, electing MIT (spot-check the SPDX line of each additional header;
assumed-same is not verified-same). Not `espressif/svd` — and the reasons
rank (esp-soc): **the licence asymmetry alone decides it** — electable MIT
with zero notice obligations against Apache-2.0-only — and would still decide
it even if the SVD were complete and fresh. That its SVD is also two years
stale (esp-soc-2, commit dates) and self-declares incompleteness are the
second and third reasons, mutually reinforcing since staleness is the
mechanism by which incompleteness stops healing. Stating the licence reason
first keeps the rule portable: it generalises to any vendor with
dual-licensed headers, whereas "their SVD is stale" expires the moment they
update it. **RP2040** — `RP2040.svd` in pico-sdk
(`src/rp2040/hardware_regs/RP2040.svd`), BSD-3-Clause confirmed two ways
(pico-sdk `LICENSE.TXT` and the SVD's own `<licenseText>`), and it is the
first-party input pico-sdk's own generator consumes — the strongest of the
three. **ST** — the SVD, with a per-file licence check before committing
derived data.

**Per-column confidence (added after stm-soc-2's finding).** A clean licence
does not make the data right, and the columns of one SVD file carry different
confidence. `STM32C031.svd` declares `RCC_CR` resetValue `0x500` (HSIDIV ÷1),
while RM0490 prose (HCLK is 12 MHz at reset) and ST's own CMSIS
`system_stm32c0xx.c` (`SystemCoreClock = 12000000UL`) both require HSIDIV ÷4 —
two independent ST sources agreeing against ST's SVD. So phase one drafts
**names, offsets and bit positions** mechanically; **reset values require
corroboration** against RM prose and CMSIS startup code, and a regmap's
`verified:` string must say separately what its reset values were corroborated
against, not just what drafted its offsets. Otherwise a wrong reset value
arrives with a clean provenance trail behind it, which is the worst kind. The
sample `rcc.json` above illustrates the trap: its `"reset": "0x00000500"` is
the SVD's declared value, and it is exactly the column under this caveat.
The complementary hazard runs the other way: RM0490's PDF→text extraction has
a systematic one-heading lag in at least two chapters (RCC §6.4.8–15, PWR
§5.4.1–6) — prose under a heading describes the *previous* register — caught
by cross-checking the RM's own register-map summary tables. SVD is ground
truth for bits and offsets; RM plus CMSIS for reset values; neither source is
authoritative alone. And the same JSON drives a JS
engine in the WASM future, where Python models will not exist but data files
port for free.

House-rule check against concrete-over-abstract: this is convergence-led, not
speculative. Three architectures exhibited the same six declarative behaviours
*before* any engine code exists, which is rule 7's merge condition already met.
The closed kind vocabulary is the guard against the format becoming a language:
a register the vocabulary cannot express goes to `coded:`, never to a new schema
feature.

### The board layer

Not a new file type. `webui/boards/<board>.json` already exists — vendor-KiCad-
derived pads with label/x/y, an MIT `source` block, and every `pin` null with a
documented assumption that the electrical layer "does not exist yet"
(`webui/pinmap.py`). The D-label→GPIO mapping is exactly the data that gap was
shaped for. Extend each pad with an optional `"gpio": <int>` (chip-relative
GPIO number), and the file with an optional top-level `"chip":
"chips/<name>.json"` reference and a `"fixtures"` list for onboard parts
(`{"part": "led", "gpio": ..., "active": "high|low", "label": ...}` — empty
for XIAO ESP32-C3, which has no user LED). One caution the existing files
teach in reverse: pad x/y is documented there as cosmetic — wrong-by-ten-
pixels miswires nothing — but `gpio` is electrical, wrong-by-one wires the
wrong pin while reporting success, so it needs a `source` citation and a
`verified` date exactly as part schemas do. The PICSimLab `pin` index and our
`gpio` coexist; either may be null when its backend does not cover the board.

---

## 3. Where the C++/Python boundary sits

**Split along the manuals: what the ARM ARM specifies lives in C++ inside the
core; what the vendor RM specifies lives in Python beside the session.**

**In-core (C++): the System Control Space** — SysTick, NVIC, SCB/VTOR. Three
reasons. (a) They are ISA-adjacent: exception entry/exit *is* core machinery,
and NVIC state gates instruction boundaries, so outboarding it makes every step
an FFI negotiation. (b) They are vendor-invariant and precisely specified, so
they belong with the core's oracle story rather than per-chip data. (c) The
hottest legitimate poll loops — busy-delays on SysTick CVR — stay native. This
does not breach `rules/core-interface.md` ("backends never include parts or
UI"): the SCS is the CPU per the architecture manual, not a part.

The RISC-V instance of the same split, forced by ESP32-C3 (esp-soc): because
C3's clock bring-up has no polled ready-bits and every wait is a fixed
`esp_rom_delay_us()`, and because the boot decision there is to *execute* the
mask ROM rather than stub it, those delays busy-wait on a **CPU cycle-counter
CSR** — the delay-based C3 traded MMIO spin risk for CSR spin risk. A core
with a frozen or absent cycle counter hangs exactly as a frozen kind-7
`counter` register does, only inside the CPU rather than in a peripheral —
which is precisely why it lands on the core side of this boundary and not in
any regmap. IDF-side code reads Espressif's custom performance-counter CSR
family (0x7E2) rather than standard `rdcycle`; the specific CSR number is
unverified (the ROM's own internal choice was not disassembled), the
requirement is not. Same failure as kind 7, same fix, one layer down: the
core's own time sources must count, on every architecture.

**Outboard (Python): every vendor peripheral**, behind an MMIO callback seam in
the C ABI — the Cortex-M analogue of `kOpenBus`, which `exec_core.cc:161`
already promises ("when a board model arrives, this constant is the seam it
replaces"). Following the `i8086_*` style:

```c
typedef uint32_t (*cm0_mmio_read_fn)(void* user, uint32_t addr, uint8_t size);
typedef void     (*cm0_mmio_write_fn)(void* user, uint32_t addr, uint32_t value, uint8_t size);

CM0_API void     cm0_set_mmio(Cm0Cpu*, uint32_t base, uint32_t span,
                              cm0_mmio_read_fn, cm0_mmio_write_fn, void* user);
CM0_API uint64_t cm0_cycles(const Cm0Cpu*);   /* virtual time; the only clock models may read */
CM0_API void     cm0_set_irq(Cm0Cpu*, uint8_t irq, int level);
```

Unregistered space reads the architecture's open-bus answer, and is logged (§4).

Why Python for the models: the session already owns pins as its currency
(`webui/api.py` `Pin`, pin events) and the websocket, so a GPIO model in-process
emits a pin-change event with zero new marshalling, and a browser button press
mutates IDR and raises EXTI via `cm0_set_irq` in one line. Iteration speed and
pytest-ability matter more than MMIO latency, because **correct ready-bit
modelling is what makes MMIO cold**: boot is thousands of accesses once spins
exit on their second read. The pathological case — firmware hammering a
Python-side register a million times — is by definition a mis-modelled register,
and §4 turns it into a log line instead of a mystery. Vendor-side counters
polled in delay loops are computed lazily from `cm0_cycles` at read time: one
FFI trip per read, no per-tick work.

---

## 4. The unmodelled-register default

Three zones, distinguishable in every log line: **unmapped** (no chip-file
entry), **stub** (chip-file name, no model — one JSON line, buys readable logs),
and **unknown offset** inside a modelled peripheral.

**Base behaviour: reads-as-written word latch, plus access accounting. Not the
flip-flop.** Reads-as-written is exactly right for kinds 1 and 3-same-register,
and right-by-accident for kind 4 (firmware never writes a busy bit, so it reads
0). It is wrong for kinds 2 and 5 — which are precisely the *spin* cases, and
spins are detectable, so the failure funnels into the one place we instrument.
The flip-flop is rejected as a default because it feeds firmware a *different
lie every read*: config code takes impossible branches and the eventual crash is
far from the cause. Renode uses it to keep unattended CI moving; our stated
product is conformance, so the default posture is fail-loudly-and-name-the-
register.

**Spin detector.** Amended per esp-soc: the first draft counted *consecutive*
reads of one address with no other MMIO between, and the flagship ESP32-C3 spin
walks straight through that — its completion poll alternates RTCCALICFG (RDY)
with RTCCALICFG2 (a *hardware* TIMEOUT bit), so each address's streak resets
the other's and no threshold ever trips. Instead the bus keeps one read counter
per address: incremented on each read of that address, reset by any MMIO write
and by that address returning a value different from its previous read —
interleaved *reads* of other addresses do not reset it. The value-change reset
also stops healthy `counter` reads in delay loops from false-positiving, which
the first draft would have. At N=1024 it emits one structured line, once per
address per run:

```
MMIO SPIN  pc=0x08000f36  addr=0x40021008  RCC+0x08 "CFGR"  reads=4096  last=0x00000000
```

`pc` comes from the core with the callback; the symbolic name resolves through
the chip file. Stubs make this line say `TIMG0+0xB0` instead of a bare address —
that is the entire difference between "my firmware hangs" and a to-do list.
A recorded negative result (rpi-soc-2): every RP2040 boot spin it found —
RESETS, XOSC, PLL, both CLOCKS.SELECTED, both FC0 loops — is a single-address
wait with no write in its body; the ESP32-C3 two-address shape is real but not
universal, and FC0's RUNNING-then-DONE is two sequential single-address loops
separated by a write, which the amended counter handles. The complement from
esp-soc-2, reading `rtc_clk.c` in full: ESP32-C3's main clock and PLL path has
**no polled ready-bit at all** — BBPLL configuration goes over the write-only
analog REGI2C bus, and every RTC-domain switch is a fixed `esp_rom_delay_us()`
wait. Those fixed delays lean on the in-core cycle counter rather than any
peripheral, so the calibration poll really is C3's flagship spin, not one of
many.

**`--unstick` (off by default).** After logging, switch *that one address* to
flip-flop so the run proceeds to the next blocker. Without it you peel one spin
per run; with it, one run yields the complete shopping list. Every unstuck
address appears in the end-of-run report flagged as faked, so a green-looking
unstuck run can never masquerade as conformance.

**End-of-run report (always, both modes).** A table of every unmodelled touch:
`peripheral+offset, name-if-known, reads, writes, first pc, spun?, unstuck?`.
Crucially this includes *write-only* touches: "GPIOA.MODER written 4 times,
never modelled" is the diagnosis for the silent non-hang failure where firmware
runs happily and the LED just never exists.

**Verification tie-in.** Each kind gets table-driven fixtures; each regmap's
`verified:` field records what its behaviour was checked against (HAL source as
read → Renode trace diff → hardware capture), the same escalation ladder as the
part schemas. The checker that enforces citations on regmaps is
`check_part_schemas.py`'s pattern applied to a second schema directory.

**The evidence ladder.** Sources rank, and the ranking is not by formality:

    SVD text  <  RM prose  <  driver-structure argument  <  trace

The third rung deserves its name spelled out: an **absence argument** is
negative evidence from driver source, and it outranks the vendor prose it
corroborates, because prose can be wrong about hardware but a driver that
never clears a bit *depends* on hardware clearing it — the vendor's own code
would hang otherwise. It is evidence about silicon, not about documentation.
Two instances produced it: `FLASH_CR.STRT`, set in two places and cleared
nowhere in `stm32c0xx_hal_flash_ex.c` (stm-soc-2); and the original HAL-spin
evidence this design started from — the same shape, the driver's structure
proving what hardware must do. The ladder generalises past this repo's
current sources, which is what makes it vocabulary rather than an STM32 note.
The ladder ranks *strength*, not *cost* (session lead's framing): a
driver-structure argument is usually cheaper than fetching an RM PDF, so it is
strictly better evidence that also happens to be easier to obtain — and this
session produced hazards against both lower rungs (the SVD reset-value
contradiction; the RM one-heading lag) while neither touches the third. The
rung cheapest to obtain is also the one no documentation hazard reaches.

**`verified:` must assert content, not presence.** "SVD-only" and
"cross-checked against RM+CMSIS" read identically to a checker that only
tests non-emptiness (stm-soc-2). So the checker requires `verified:` to name
*which facts* each corroboration chain covers — offsets/bits and reset
values separately, per the per-column policy. This repo has made exactly this
hardening before: `README.md:128-129` records that `check_licenses` asserts
the presence of the *right* licence "after an earlier version could be
satisfied by a file with no header at all." Same failure, same fix — assert
the content of the claim, not the presence of the field.

---

## 5. Build order, if adopted

Vertical slices, each verified by the firmware getting observably further:

1. `cm0_set_mmio` seam + reads-as-written bus + spin log — proven by a
   hand-written spin firmware.
2. Regmap engine + `rcc.json` / `flash.json` — proven by HAL
   `SystemClock_Config` reaching `main`.
3. Coded GPIO + pin event to the websocket — blink.
4. The SVD drafter.

---

## 6. Evidence tally, as the test for a first schema version

Every schema feature carries a count of the architectures that forced it, and
the count is the adoption test. As of 2026-08-24:

- **Kinds 1–8, the read-purity rule, the spin detector, reads-as-written
  default**: three architectures (STM32, RP2040, ESP32-C3). First version. For the
  detector specifically, two of the three contributed *negative* results —
  RP2040 exercises the single-address case everywhere and defeats it nowhere;
  C3's clock path has no polled ready-bit at all — and only C3's calibration
  poll forced the amendment. Counting three without saying that would
  overstate the support: what the two contributed is a *bound*, which is why
  the detector is the best-evidenced part of the design rather than merely
  the most-cited.
- **Multi-source `follows`** (`op`, uniform `when`): two (ESP32-C3 TIMG RDY,
  RP2040 PLL LOCK). Zero on C0. First version, but its boundary — no nesting,
  no per-source polarity — is load-bearing.
- **`atomic_aliases` + per-peripheral opt-out**: one (RP2040) — and its first
  mechanism inverted once already on a closer datasheet reading. Ships marked
  **RP2040-shaped** until a second chip with alias regions exercises it. The
  caution is earned empirically, not by principle: the bus mechanism was
  adopted, then *hardened* with a required field and a checker rule, and only
  then disproven — one chip's evidence looked sufficient right up until it
  wasn't, and it had already been built on by the time it failed.

The inference that makes the tally worth keeping: a feature driven by one
chip is one datasheet reading away from another inversion; a feature driven
by none is speculation the closed vocabulary correctly refused to build.
Whoever writes the adoption ticket will not have this conversation — this
section is its record.
