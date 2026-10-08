# Architectures: what it would take to emulate each

Survey of every chip family on this project's board list, with a per-chip
checklist of the steps between "nothing" and "runs a PlatformIO blink you can
see". Compiled 2026-08-24 from sixteen parallel research passes.

**Every claim here is marked for how it was established.** [V] means an agent
fetched the primary source this session and quoted it. [W] means
well-established and spot-checked. [U] means unverified — a lead, not a fact.
Two agents contradicted each other on one point and both are recorded, in §7.

The unit of effort throughout is this repository's own i8086 core: **73
opcodes to first conformance, 252 to a complete map, 2,797,000 hardware cases
at 100%.** Estimates against that unit are the agents' judgement, not measured.

---

## 1. The verdict, before the detail

| Family | Core | Verdict | Why |
|---|---|---|---|
| **RP2040** | Cortex-M0+ | **Integrate, don't rewrite** | `rp2040js` is MIT, browser-native, runs real firmware, and was already silicon-diffed. PIO and USB are each bigger than the CPU core. |
| **STM32 C0/G0** | Cortex-M0+ | **Build our own** | Smallest ISA on the list. Prior art is weakest exactly on correctness. Oracle hardware costs ~$12. |
| **ESP32-C3** | RV32IMC | **Route through QEMU** | The CPU is the *smallest* obstacle — see §4.1. |
| **ESP32-S3** | Xtensa LX7 | **Avoid** | NDA-gated ISA, register windowing, and a licence trap in the only public doc. |
| **RP2350** | Cortex-M33 | **Defer** | As configured it carries Security + DSP + FPU — far past plain Armv8-M. |
| **RP2350** | Hazard3 RISC-V | **Cheapest oracle, not a sufficient one** | Apache-2.0, exact ISA string in the datasheet, **and the repo ships its own C++17 golden model** — built and run here. But it models no extension boundary and is wrong at the illegal-instruction edge for its own part; see §2.1b. |

The recommendation is not uniform because the situations are not: **integrate
where good MIT prior art exists, route through an existing emulator where the
SoC is the wall, and build our own only where prior art is weak on the thing
this project claims to care about.**

---

## 2. The oracle problem, which decides everything else

This repository's i8086 core is worth something because of SingleStepTests/8088
— 2.8 million cases captured from physical silicon. The first question for any
new architecture is whether an equivalent exists.

**It does not.** [V] The SingleStepTests organisation has 22 repositories —
8086, 8088, 80186/286/386, V20, Z80, SH4, R3000, HuC6280, ARM7TDMI, 65x02,
65816, m68000, 680x0, SPC700, SM83, TLCS900H, and two Ares forks. **No RISC-V.
No Xtensa. No Cortex-M.**

Two commonly-cited escape hatches were checked and are false:

- **riscv-arch-test** (now ACT4) ships **no** prebuilt ELFs and **no** static
  reference signatures. It needs GCC 15 or LLVM 22, Sail 0.13.1 and Ruby. [V]
- The repositories people cite as "prebuilt riscv-tests" hold MicroPython and
  FreeRTOS demos, or Doom and CoreMark benchmarks. Not conformance. [V]

### 2.1 The way out, found independently three times

Three agents working on three different chips converged on the same answer:
**capture the corpus ourselves, by single-stepping real silicon over a debug
interface.** That is the 8088 methodology, self-produced.

| Target | Rig | Status |
|---|---|---|
| RP2040 | SWD lockstep, "gdbdiff" | **Already done once** [V] — caught real bugs in ADCS overflow, CMP carry and LSRS edge cases |
| ESP32-C3/C6/S3 | built-in USB Serial/JTAG + OpenOCD `stepi` | The *only* hardware-grounded path that exists for Xtensa [V] |
| STM32 | Nucleo-C031C6, onboard ST-LINK, ~$12 | pyOCD single-step |

That rp2040js precedent matters more than it first appears: someone has already
run this exact method against this exact class of chip and found genuine flag
bugs with it. It is not speculative.

**This is the thing the project would actually own.** Nobody has published such
a corpus for these parts. Feasibility — throughput especially — is under
active investigation.

### 2.1a The SWD route is practical, and the feared blocker is not real

The worry was that Cortex-M0+ lacks hardware single-step. **It does not**, and
the confusion is between two different mechanisms [V]:

- **Halting debug** — halt via `DHCSR.C_HALT`, then `C_STEP` executes exactly
  one instruction and re-halts. Base Armv6-M. Universal across every Cortex-M.
- **Debug-monitor stepping** — non-invasive, via a DebugMonitor exception.
  **This** is what Armv6-M lacks.

Corpus capture wants the core fully halted between instructions anyway, so it
needs the mechanism that exists, not the one that does not. Confirmed in
pyOCD's own source (`pyocd/coresight/cortex_m.py`): its generic `step()` is
shared by every Cortex-M target, drives `DHCSR` directly, and sets
`C_MASKINTS` before stepping specifically so an interrupt cannot fire mid-step
and destroy the one-instruction assumption. The tool already handles the one
real gotcha.

**The actual risk is throughput, and nobody has published a number.** The
bottleneck is not SWD wire speed but CMSIS-DAP over USB HID — one 64-byte
packet per ~1 ms, with an ack per packet. Estimated 20–50 cases/sec realistic,
100–200 if well batched, single digits if not. At SST8088 density over a
15–25 opcode subset (150,000–250,000 cases) that is **1–3.5 hours**, or 1–2
days pessimistically. Not weeks — but this is arithmetic from a generic
latency figure, not a benchmark. SST8088's own README publishes no throughput
numbers either, so there is nothing to calibrate against.

Two design constraints to settle **before** writing the rig, not after:

- Armv6-M collapses every fault into one **HardFault** vector — no separate
  MemManage/BusFault/UsageFault. "This instruction faulted" has to be a
  designed outcome class, the way SST8088 special-cased the 8088's divide
  exception, not an afterthought.
- Cases whose operands would branch out of the sandbox or touch the debug unit
  must be filtered at *generation* time. SST8088 did the equivalent by masking
  CX to 7 bits and CL to 6.

**Nobody has published this exact recipe** — SWD halting-debug capture from a
Cortex-M, released as a portable corpus. That cuts both ways: no one has shown
it fails, and no one has left behind the pitfalls either.

### 2.1b Hazard3 ships its own golden model — cheap, and not sufficient alone

`Hazard3`'s repository contains **`test/sim/rvcpp/`, a 1080-line C++17 ISA
simulator written by the same author as the silicon**. Apache-2.0, confirmed
from the LICENSE file. Its `RVCore` exposes `regs[32]`, `pc`, `csr` and
`step()` as plain public members — already the shape a SingleStepTests-style
fixture generator needs. **Built and executed on this machine** [V]: MSVC
19.44 behind a 13-line shim (it needs `__attribute__((unused))` neutralised,
four GCC builtins, and `<string>`, which `main.cpp` uses without including),
then 15 hand-assembled instructions run with `add`, `clz`, `cpop`, `rev8` and
`ctz` all correct. No cross-compiler at any point.

**But it does not model what the hardware refuses, and that is measured, not
inferred.** [V]

* **It has no extension configuration of any kind** — no `#ifdef`, no runtime
  enable. All 94 opcodes are live unconditionally, including `Zbc`, which the
  RP2350 ISA string does not contain.
* **Its RVC decoder has no XLEN gate.** `C_LD` (`rv_core.cpp:732`), `C_SD`
  (764), `C_LDSP` (981) and `C_SDSP` (1000) are the RV64 meanings of encodings
  that on RV32 belong to Zcf/Zcd — and rvcpp is `XLEN=32` with zero
  floating-point support. On RP2350, which has no FPU, all four must raise
  illegal-instruction. Measured at `8af9929`: they execute as integer loads and
  stores whenever the destination or source register is **even**. Odd registers
  reject only because the generated opcode masks carry a spurious `rd[0] == 0`
  constraint — half the register space rejects by coincidence, not because the
  model knows `F` is absent.
* **The defect camouflages itself.** With registers at their reset zeros the
  even-register cases still trap, but with cause 5 or 7 (access fault) rather
  than 2 (illegal instruction). So it presents as a correct rejection in three
  of the four register-parity × base-validity quadrants, and is visible only
  when a probe hits an even register and a valid base together.

So: **the cheapest RISC-V oracle that runs on Windows, and the right thing to
debug a fixture generator against — but not the sole oracle for a conformance
corpus.** It is wrong at the illegal-instruction edge for its own target part,
and that edge is where this project's corpora earn their keep: the 8086 work's
value was exactness at the undefined and undocumented boundaries. Illegal-
instruction expectations need a configurable model (UDB with an explicit
config, or Sail) or silicon.

**The general acceptance criterion this produced**, which §6.1 did not ask for
and should have: *does the candidate model what the hardware refuses?* Building
and exposing the right shape is necessary and not sufficient.

A second, independent model is available for CI: `riscv/sail-riscv`, the
official RISC-V golden model, BSD-2-Clause, publishes **prebuilt Linux x86_64
binaries** in weekly releases — no build, no toolchain. No Windows binary, so
the natural split is rvcpp locally and Sail in CI, which also gives two
independent implementations rather than one. [V]

### 2.1c A trap in the obvious shortcut

**Unicorn Engine's core is QEMU's TCG.** They are not independent
implementations, so "our core agrees with Unicorn" is nearly worthless as
cross-validation against QEMU. A genuinely separate second implementation is
needed for agreement to mean anything. [V]

**And so is Renode.** [V] `antmicro/tlib`'s LICENSE opens *"This code is based
on libqemu code and is LGPL licensed"*, and `arch/arm/translate.c` carries
*"Copyright (c) 2003 Fabrice Bellard"*. So the graph is
`QEMU/TCG → {Unicorn, tlib → Renode}` and **two** candidate second opinions
retire at once.

**This is one hazard with at least three instances, and it deserves a name.**
In each case a thing that *looked* like corroboration was downstream of what it
appeared to corroborate:

| Instance | Apparent second opinion | Actual ancestor |
|---|---|---|
| Unicorn, Renode | separate emulators | QEMU TCG |
| QEMU-xtensa vs `objdump` | separate toolchains | the same Tensilica archive, via `import_core.sh` (§4.4) |
| IDF vs LLVM extension lists | separate repos, languages, maintainers | both answer *"what the compiler emits"* (§4.2) |

**The check that catches all three is the same one: before treating agreement
as evidence, establish that the two sources do not share an ancestor.** It is
cheap, and it retired two candidate oracles here in about ten minutes.

**A related correction to this document's own premise.** [V] "SST-shaped" has
been read throughout as implying hardware-captured. It does not. Of
SingleStepTests' 22 repositories, only the x86 family — 8086/8088/80186/80286/
80386/V20 — claims hardware generation. ARM7TDMI is generated from
NanoBoyAdvance, m68000 from MAME, sh4 from Reicast, huc6280 from Mesen, and
z80/spc700/sm83 from JSMoo. That is the same kind of artefact we would be
producing, so the format carries no implication about the oracle behind it.

That matters because the risk is not hypothetical: a published study
differential-tested real Arm hardware against QEMU across 2,774,649
instruction streams and found **155,642 divergences (30% of encodings)** plus
four confirmed QEMU bugs — including missing alignment enforcement on
LDRD/STRD/LDM/STM. A simulator oracle is a real oracle, but it is an oracle
for agreement with an implementation, not with silicon. [V]

Worth noting against our own instinct: the RISC-V industry's own standard is
*simulator*-oracle, not hardware. OpenHW's CORE-V-VERIF verifies CV32E40P by
lock-step co-simulation against a commercial ISS inside RTL simulation. So a
self-captured hardware corpus would be outside normal practice, not following
it. [V]

### 2.2 A third route, possibly toolchain-free

`riscv/riscv-unified-db` publishes one YAML per instruction under
BSD-3-Clause-Clear, carrying an `encoding.match` bit pattern, field positions,
and an executable `operation()`. If that holds up, a corpus generator needs no
assembler and no cross-compiler at all. Under verification.

---

## 3. Arm Cortex-M

### 3.1 Armv6-M — the numbers, from the primary source

Agents were asked not to trust folklore here, and the folklore was wrong.

From **ARM DDI 0419E** §A6.7, extracted from the 374-page PDF [V]:
- **77 numbered encoding-variant sections** (A6.7.1–A6.7.77) — each a distinct
  bit-pattern-to-semantics mapping, which is what a decoder actually needs
- **59 distinct mnemonics** once addressing-mode variants collapse
- the widely-repeated "56" figure could not be found anywhere in the manual —
  **treat it as folklore**

**The 16-vs-32-bit rule**, quoted verbatim from §A5.1 (p. A5-76) [V]:

> If bits[15:11] of the halfword being decoded take any of the following
> values, the halfword is the first halfword of a 32-bit instruction:
> `0b11101`, `0b11110`, `0b11111`. Otherwise, the halfword is a 16-bit
> instruction.

That single check is the entire desynchronisation risk. Get it right and the
rest is a two-level dispatch.

**Six entries use a 32-bit encoding** [V]: `BL`, `DMB`, `DSB`, `ISB`, `MRS`,
`MSR (register)`. DDI0419C §A4.1 states exactly that list verbatim, and §A4.1.1
adds that `BL` is *"the only 32-bit instruction in ARMv6-M that updates the
PC"*.

*Two agents disagreed here* — one reading DDI0419**E** counted seven, including
a T2 encoding of `UDF`; the other, reading DDI0419**C**, counted six and
classifies `UDF` as a name for the permanently-undefined space rather than an
instruction.

**Resolved for decoding purposes: six.** [V] Three sources now agree, two of
them independent implementations rather than readings of the same document:

| Source | Kind | What it does |
|---|---|---|
| **DDI0419C §A4.1** | primary specification | states the list verbatim |
| **QEMU** `target/arm/tcg/translate.c:6218-6229` | independent implementation | whitelists exactly those six by mask; every other 32-bit encoding falls through to `illegal_op` |
| **GNU binutils 2.40** (`arm-none-eabi-as -mcpu=cortex-m0plus`) | independent implementation | assembles exactly those six, and **rejects `udf.w` by name**: *"selected processor does not support `udf.w #0' in Thumb-2 mode"*. Also rejects `movw`, `mls`, `clz`, `ldrex` |

**What this does not settle**, and the distinction is worth keeping: it does
not disprove that DDI0419E names a `UDF` T2 form inside the permanently-
undefined encoding space. The two readings never conflicted about *behaviour* —
both agree `UDF` means "refuse". The disagreement was taxonomic, about whether
a name given to permanently-undefined space counts as an instruction, and that
question is left open because it does not affect a decoder. What is settled is
that no specification, emulator or assembler treats a seventh 32-bit encoding
as available.

The same agent
also notes 2 of the 71 16-bit entries are deprecated assembler aliases with no
unique encoding — `CPY` (for `MOV` register) and `NEG` (for `RSB #0`) — giving
**74 functionally distinct operations** if you fold those out.

Estimated effort: **~0.6–0.8×** the i8086's 73-opcode first conformance. No
segments, no ModRM combinatorics, uniform 32-bit register file.

### 3.2 STM32 — the families

Five families are built on Cortex-M0/M0+: **C0, F0, G0, L0, U0**. (STM32WB and
WL also contain an M0+, but only as a radio co-processor.)

| Family | Core | Clock | Flash / SRAM | Sold for |
|---|---|---|---|---|
| **F0** | Cortex-M0 | 48 MHz | 16–256 KB / 4–32 KB | The original cheap mainstream line (2012) |
| **L0** | Cortex-M0+ | 32 MHz | 16–192 KB / 2–20 KB [U] | Ultra-low-power; LCD driver and AES on upper parts |
| **G0** | Cortex-M0+ | 64 MHz | 16–512 KB / ≤144 KB | Cost-optimised F0 successor; CAN FD and USB-C PD at the top |
| **C0** | Cortex-M0+ | 48 MHz | ≤256 KB / 6–36 KB | ST's explicit 8/16-bit displacement line — lowest price in the catalogue |
| **U0** | Cortex-M0+ | 56 MHz | ≤256 KB / ≤40 KB | 2024, 18 nm FD-SOI; 160 nA standby |

Boards: NUCLEO-C031C6, NUCLEO-G031K8, NUCLEO-G0B1RE, NUCLEO-F030R8,
NUCLEO-L053R8, NUCLEO-U031R8, STM32G071B-DISCOVERY, and the third-party
"Blue Pill" (F103C8T6) and WeAct "Black Pill" (F411CEU6).

One confirmed quirk worth knowing: **STM32F0308-DISCOVERY carries an
STM32F051R8T6**, not an F030. [V]

### 3.3 Checklist — STM32 Cortex-M0/M0+ (all five families)

The spine is shared; per-family deltas follow.

```
core: Cortex-M0/M0+, Armv6-M
 1. Decode Armv6-M Thumb + the seven 32-bit encodings; implement NVIC.
    — wrong decode faults or hangs on the first instruction.
 2. Vector table: initial SP at word 0, reset vector at word 1, bit 0 set
    (Thumb) or the core faults.
    — flash lives at 0x08000000 and is aliased to 0x00000000 by BOOT0.
      Get the alias wrong and the first fetch is garbage.
 3. Memory map: flash 0x08000000, SRAM 0x20000000, peripherals 0x40000000.
    — incomplete map means GPIO writes silently vanish.
 4. RCC clock tree and its READY bits (HSIRDY, HSERDY, PLLRDY).
    — THE CRITICAL ONE. See §3.4.
 5. RCC peripheral-clock gating (IOPENR / AHBENR / APBENR).
    — if GPIO works while its clock bit is clear, the emulator passes and
      real silicon fails. A false green, which is worse than a red.
 6. FLASH->ACR LATENCY, which must read back what was written.
    — not fatal for blink; wrong for anything timed.
 7. GPIO: MODER, OTYPER, OSPEEDR, PUPDR, IDR, ODR, BSRR.
    — BSRR specifically: HAL uses atomic set/reset, not read-modify-write.
 8. SysTick (0xE000E010) counting on virtual time, and its exception.
    — without it HAL_Delay never returns. See §3.4 for why that is worse
      than it sounds.
 9. NVIC dispatch so SysTick_Handler runs and HAL_GetTick advances.
10. USART TXE/TC — every tutorial adds a printf immediately after blink.
11. IWDG/WWDG: inert registers. Disabled at reset unless option bytes say
    otherwise, and Arduino never enables them. Half-modelling them causes
    spurious resets; ignoring them is safe.
12. Option bytes (BOR, RDP, boot address) matching a shipped dev kit.
```

Per-family deltas:
- **L0** adds MSI (the power-on default clock) with its own RDY bit and an
  MSIRANGE field that must read back, and couples flash wait states to
  `PWR->CR` VCORE range rather than frequency alone.
- **G0** renamed `AHBENR`→`IOPENR` and split `APBENR1`/`APBENR2`. On G0B1/G0C1,
  `FLASH->OPTR.DBANK` selects single- or dual-bank addressing — get the
  polarity backwards and the vector table is not where you think.
- **C0** is derived from G0's IP, so a correct G0 gets most of C0 free. Always
  single-bank. HSI 48 MHz is often the only high-speed source — many small
  packages have no crystal.
- **U0** is newest and has the thinnest public reference base. Budget
  reference-manual reading over copying known-good examples.

**Cheapest first: STM32F030** — plain Cortex-M0 (smaller ISA than M0+, no MPU
to stub), one clock path, single-bank flash, no USB/CAN/crypto in the value
line, and the largest body of existing reference firmware to check against.
Runner-up **STM32C011** if matching current hardware matters more.

### 3.4 The spin-wait trap, stated precisely

This is the single most valuable finding in the entire survey, and it is
worse than the usual description.

Fetched verbatim from ST's `stm32g0xx_hal_rcc.c` [V]: all four classic loops
are there — wait for `HSERDY`, wait for `PLLRDY`, wait for `FLASH->ACR` to read
back the latency just written, wait for `RCC->CFGR` `SWS` to match `SW`.

> **That is a G0 measurement, and it does not transfer to C0.** [V]
> **STM32C0 has no PLL at all** — HSI48 with an HSIDIV divider — confirmed
> absent from `RCC_CR` and `RCC_CFGR` in both the SVD and the RM chapter. Its
> own `stm32c0xx_hal_rcc.c` contains **11 `while` loops across three
> functions**, of which only **three** are exercised on the stock no-crystal
> Nucleo-C031C6 boot path: `HSIRDY` (line 414), the `FLASH_ACR.LATENCY`
> readback (670), and `SWS == SW` (756). So *finding no PLL wait on C0 confirms
> this analysis rather than contradicting it*, and a C0 register map is
> legitimately smaller than the four-loop figure implies. Do not transcribe the
> G0 list onto C0 unexamined.

**Every one of them uses `HAL_GetTick()` as its timeout. `HAL_GetTick` is
incremented by the SysTick interrupt.**

So with no SysTick, the loop's escape hatch is as dead as the loop itself —
even the `HAL_TIMEOUT` error path can never fire. A naive emulator hangs
silently inside `SystemClock_Config`, before `setup()` is ever reached.

The fix is one pattern, which is what Renode does [V]: **ready-mirrors-enable.**
`PLLRDY` reads back `PLLON`; `HSERDY` reads back `HSEON`; `SWS` reflects `SW`
immediately.

Polarity matters and cuts both ways:

| Pattern | Example | Correct default |
|---|---|---|
| wait-for-set after enable | `HSERDY`, `PLLRDY`, RP2040 `RESET_DONE` | status mirrors enable |
| wait-for-match after write | `SWS`, `ACR` latency | register stores and reflects |
| wait-for-clear | SAMD21 `SYNCBUSY` | default 0, never stuck at 1 |
| unmodelled register | anything | see below |

For registers nobody has modelled, Renode's `stm32g0.repl` uses an inline
Python stub whose reads alternate `0x00000000` / `0xFFFFFFF8`, which terminates
a poll of *either* polarity within two reads [V]. Crude, semantics-free, and
effective.

---

## 4. Espressif

### 4.1 Why the CPU is the smallest obstacle

Three walls sit behind a correct ESP core, and none of them is the ISA:

1. **ROM linkage.** IDF and Arduino apps link directly against functions
   resident in the mask ROM via `esp32c3.rom.ld` — memcpy variants,
   `esp_rom_printf`, UART and SPI-flash primitives. You can skip the
   bootloader; you cannot skip the ROM. Every working emulator ships a ROM
   image. [V]
2. **A custom interrupt matrix, not a PLIC** — but this is stated too broadly.
   [V] The matrix-not-PLIC shape is datasheet-confirmed **for the C3**
   (§4.1.3.4 "Interrupt Matrix"), and the numbers there are **62 peripheral
   sources in, 31 CPU peripheral interrupts out** — this document's "43 to 32"
   conflated the CPU's 32 vectored slots with the matrix's 31 outputs, and the
   43 has no source. But **C5 and P4 datasheets explicitly say CLIC**
   ("compliant with RISC-V Core-Local Interrupt Controller"), so the blanket
   claim is wrong for them. And the PLIC half is weaker still: `soc_caps.h`
   sets `SOC_INT_PLIC_SUPPORTED=1` for C6/H2/H21, but neither the C6 nor the H2
   datasheet ever uses the word — C6 says only "Interrupt controller with up to
   28 external vectored interrupts". **Treat CLIC as datasheet-confirmed and
   PLIC as IDF-header-only.** ESP RISC-V chips route peripheral
   sources through an Espressif crossbar, using IDs 1–31 where the RISC-V
   standard reserves 0–15 for core-internal use. A generic PLIC bolted on will
   silently mis-route every driver interrupt. [V]
3. **Flash cache MMU.** IDF linker scripts assume code executes from the
   0x42000000 window. Without that mapping, the first jump after handoff
   faults. [V]

Plus the classic hang: the RTC slow-clock calibration poll
(`TIMG_RTCCALICFG` waiting on a ready bit) spins forever when unimplemented
registers read as zero. [V]

### 4.2 The RISC-V chips

All verified against Espressif's own datasheets [V].

| Chip | ISA | Cores | Clock | Radio |
|---|---|---|---|---|
| **ESP32-C2** (ESP8684) | RV32IMAC | 1 | 120 MHz | WiFi 4, BLE 5.3 |
| **ESP32-C3** | **RV32IMC — no A** | 1 | 160 MHz | WiFi 4, BLE 5 |
| **ESP32-C5** | RV32IMAC + Zcb/Zcmp/Zcmt + Xhwlp | HP + LP | 240 / 48 MHz | **Dual-band** WiFi 6, BLE 6.0, 802.15.4 |
| **ESP32-C6** | RV32IMAC | HP + LP | 160 / 20 MHz | WiFi 6 (2.4 only), BLE 5, 802.15.4 |
| **ESP32-C61** | RV32IMAC + Zc | 1 | 160 MHz | WiFi 6 (2.4), BLE 6.0 |
| **ESP32-H2** | RV32IMAC | 1 | 96 MHz | **No WiFi** — BLE 5.3 + 802.15.4 |
| **ESP32-H4** | RV32IMAC [U] | 2 | 96 MHz | BLE 5.4, 802.15.4 — **sampling, no public TRM** |
| **ESP32-P4** | **RV32IMAFC** + Zc + **Zb** + XespV + XespLoop | 2 HP + 1 LP | 400 / 40 MHz | **None** — pairs with a C6 over SDIO |
| **ESP32-H21** | RV32IMAC [U — IDF headers only] | 1 | — | 802.15.4 + BLE |

The S2 and S3 also carry a **ULP RISC-V coprocessor** (RV32IMC) beside their
Xtensa main cores, restricted to RTC memory and registers. [V]

**ESP32-C3 is confirmed RV32IMC with no atomics**, quoted from the datasheet
and corroborated behaviourally: ESP-IDF's C3 port uses critical sections rather
than LR/SC *because* the core lacks A. [V] A decoder that accepts `lr.w` on C3
is out of spec.

#### The C2 lesson: `-march` is compiler policy, the datasheet is silicon

This table was challenged and **survived**, and how it survived is worth more
than the table. An agent built a competing extension list from ESP-IDF's
`project_include.cmake` and Espressif LLVM's `RISCVProcessors.td` — different
repositories, languages and maintainers — found them in agreement, and issued
corrections against the `[V]` datasheet cells. Two were wrong. The ESP8684
datasheet says verbatim: *"base integer (I), multiplication/division (M),
**atomic (A)** and compressed (C)"*, **"RV32IMAC ISA"**. The C2 row was right
all along; IDF and LLVM simply *compile* C2 as `rv32imc`. [V]

> **Two sources agreeing is not independence when they share a premise.**

Both answer *"what does the compiler emit"*. The cells here answer *"what does
the silicon implement"*. This is the same trap as §2.1c's "Unicorn's core is
QEMU's TCG", one level up — and the agent that walked into it had built an
independence matrix in the same report.

**The operational rule:**

* **Emulator or decoder → the datasheet.** Accept everything the hardware
  accepts, or you trap a legal instruction. Had the C2 "correction" landed, a
  C2 core would have refused `lr.w`.
* **Fixture corpus covering only real firmware → `-march`.** Nothing outside it
  appears in an IDF build.
* Where they disagree, **record both and name the question being answered.**

That dissolves the C5/C61 Zc question rather than leaving it contradictory:
silicon has Zcb/Zcmp/Zcmt per the datasheets, and `ZCMP_WORKAROUND=1` gates
them out of the default build. So a claim that stock firmware needs them is
wrong, *and* a decoder must still implement them. Both true, different
questions.

Also from the same pass: vendor extensions have **two naming registers, both
correct**. `Xhwlp`, `XespV` and `XespLoop` are the datasheets' own prose names;
`_xesploop`, `_xespv` and `_xespdsp` are the `-march` substrings a decoder
author actually meets. Record both. And **ESP32-H4** is `rv32imafcb` + xespdsp
rather than the RV32IMAC this table guessed — but its datasheet 404s, so that
is toolchain-sourced, which is an improvement on a `[U]` guess and *not* the
same class as a datasheet row.

### 4.3 Checklist — ESP32-C3 (the reference case)

```
core: RISC-V RV32IMC, single-core, 160 MHz
 1. Decode RV32I + M + C only. Do NOT accept A.
    — an illegal atomic must trap, not silently NOP, or you diverge from
      silicon in a way no test will catch.
 2. CSRs: mstatus, mie, mip, mtvec, mepc, mcause, mtval, plus Espressif's
    interrupt-threshold extensions.
    — wrong mepc/mcause means ESP-IDF's panic handler prints garbage
      backtraces, and every later bug becomes unfixable from inside.
 3. Reset vector in mask ROM; GPIO_STRAP_REG selects UART-download vs
    SPI-boot.
    — without strap sampling you can never enter flashing mode, so you are
      limited to pre-baked images.
 4. Memory map: IRAM/DRAM, ROM, and the flash MMU windows at 0x42000000
    (exec) and 0x3C000000 (rodata).
    — IDF's linker script assumes these. Without them the first post-handoff
      jump faults.
 5. esp image format + partition table at flash 0x8000, app at 0x10000.
    — skip it and you can only run raw blobs, not what people actually build.
 6. Clock/system registers enough that esp_clk_cpu_freq() reads sane.
    — ets_delay_us and every UART divider derive from it.
 7. GPIO matrix + IO MUX — any pin to (almost) any signal, via a routing
    table. NOT a fixed pinout.
    — hardcode the mapping and firmware that routes UART1 TX to GPIO4 gets
      silence on the pin it asked for.
 8. UART0 with FIFOs, baud generator, and the ROM download protocol
    (autobaud on 07 07 12 20).
 9. Watchdogs: RWDT, 2x MWDT, analog Super WDT, XTAL32K WDT — four
    mechanisms.
    — an emulator that ignores them entirely is SAFE. One that half-models
      them resets spuriously. Ignoring is the right first move.
10. Interrupt matrix, NOT a PLIC. **62** sources to **31** CPU lines [V —
    corrected; see the note under this list], 7 priorities,
    IDs 1-31.
    — a generic PLIC mis-routes esp_intr_alloc and breaks every driver that
      uses interrupts, which is everything but trivial polling.
```

**Cheapest ESP first: C3.** Smallest ISA scope on the list, single core, no
LP-core handoff, no dual-band clock sequencing, most mature tooling and the
only one with a dedicated QEMU machine to differential-test against.

Deltas for the rest: **C2** adds A and has only 2 watchdogs. **C6/C5** add a
second (LP) core with its own reset entry, a shared LP-SRAM region, and a
separate interrupt controller — booting both cores at power-on corrupts the
handshake. **C5** additionally needs Zcb/Zcmp/Zcmt and the custom `Xhwlp`;
these are compiler-emitted in *ordinary function prologues*, so a decoder
without them fails on essentially all C5 firmware — the highest-risk unknown
in the family. **P4** needs an FPU plus two proprietary extensions whose
encodings are not in upstream `riscv-opcodes`, three independent CSR/trap
domains, and per-core interrupt matrices (32+32, not shared) — estimated
**3–4×** the C3/C6 surface. **H4** has no public TRM; do not start there.

### 4.4 Xtensa (ESP32-S3) — avoid, and here is why

- **~76–82 base instructions + 12 code-density forms ≈ 90–100** for a minimal
  core, before FPU or the custom PIE SIMD block. Code density is *not*
  optional — GCC emits the 16-bit `.N` forms by default, so stock firmware is
  full of them. [V]
- **Register windowing** is the real cost: a register number in a decoded
  instruction is not a fixed physical index but must be translated through
  `WINDOWBASE`, and you must implement window overflow/underflow exceptions in
  three spill sizes whose stack layout must match what Espressif's GCC assumes.
  Get the bookkeeping wrong and *every function call* silently corrupts a
  caller's registers. [V]
- Estimated **2–3×** the complete 8086 effort.

**Two licence traps were recorded here. One is real; the second was wrong and
is struck below.** The Avoid verdict does not rest on either — see the note
after them.

1. `espressif/xtensa-isa-doc` — the README says CC-BY-SA-3.0, the LICENSE file
   says **Attribution-NonCommercial-ShareAlike**. The repository contradicts
   itself. It cannot go into an MIT tree.
2. ~~Espressif QEMU's `core-esp32s3/xtensa-modules.inc.c` is GPL-2, external
   process only, never in-tree.~~ **STRUCK — this was wrong.** [V] The file
   (1,312,360 bytes) and `core-isa.h` beside it carry a verbatim **MIT** grant,
   "Copyright (c) 2003-2021 Tensilica Inc.", and QEMU's `LICENSE` §2 says
   per-file licences govern. The GPL-2 file is a *different* one — upstream's
   FSF/BFD-derived `core-dc232b/xtensa-modules.c.inc`, which we do not need.
   QEMU's whole Xtensa **CPU model** (`translate.c`, `cpu.c`, `helper.c`,
   `op_helper.c`, `win_helper.c` — where the windowing bookkeeping actually
   lives — `exc_helper.c`, `mmu_helper.c`) is **BSD-3-Clause**, Max Filippov;
   `xtensa-isa.c` is MIT. And LLVM carries a **hand-written** Xtensa backend
   with AsmParser and Disassembler under Apache-2.0-WITH-LLVM-exception, with
   `esp32s3` in Espressif's fork. So "no legally consumable ISA description"
   is false.

   One caveat a human should rule on before anything is vendored: the tables
   carry "Customer ID=15128", so they are per-customer generated artefacts.
   The MIT grant is in the file and Espressif has redistributed them publicly
   inside a GPL project for years — but a copyright grant is not a patent or
   trademark grant. **Flag, do not vendor silently.**

**Net: Avoid still holds — on cost and oracle scarcity, not on licence.** [V]
The engineering argument above is untouched: ~90–100 instructions with
mandatory `.N` density forms, and register windowing through `WINDOWBASE` with
overflow/underflow in three spill sizes matching Espressif's GCC ABI. And it
gains a second leg stronger than the licence claim ever was: **no
permissively-licensed *executable* Xtensa ISS exists anywhere.** There is no
rvcpp and no Sail for Xtensa; LLVM has a backend but no simulator; QEMU's is a
TCG translator, not a steppable golden model. A verdict resting on "we cannot
check it" is more durable than one resting on a licence reading — which is just
as well, since the licence reading turned out to be wrong.

One further collision for the independence graph: `import_core.sh` extracts
`binutils/xtensa-modules.c` from the same Tensilica archive QEMU imports, so
**"our decoder agrees with `objdump`" is a tautology on Xtensa.** LLVM's
hand-written backend is the only permissive second opinion. [V]

### 4.5 What QEMU does and does not give you

Espressif's QEMU fork supports ~~**ESP32, ESP32-S3 and ESP32-C3 only** — no C5,
no C6~~ — **out of date.** [V] `espressif/qemu` at `esp-develop` now carries
`hw/riscv/esp32c6.c`, `esp32c6_clk.c` and `esp32c6_intmatrix.c`, so **C6 is
supported**; the Xtensa side has `core-esp32` and `core-esp32s3` only, so there
is **no S2**. The prebuilt binaries lag the source — `-machine help` on the
current release exposes only `esp32c3` for riscv32.

**And it runs on Windows natively.** [V] Espressif publishes a prebuilt
`x86_64-w64-mingw32` build (esp-develop-9.2.2). A real PlatformIO XIAO
ESP32-C3 blink was taken end-to-end on this machine under it — ROM →
second-stage bootloader → app → `blink HIGH/blink LOW` on UART0 — with two
flash-fidelity traps reproduced and diagnosed: an 80 MHz `f_flash` default that
asserts in `do_core_init`, and Arduino's sdkconfig probing QIO regardless of
the image header. That materially narrows the paragraph below: the fork is no
longer load-bearing for the *CPU and firmware-input* path, only for the
pin/I2C/SPI/RMT callback ABI.

On *every* target, stock QEMU still emulates **no GPIO matrix or IO MUX, no
I2C, I2S, SPI, RMT, USB, WiFi, BLE or ULP**. [V]

That looks fatal for our purposes, and it is — for *stock* QEMU. PICSimLab's
fork (`lcgamboa/qemu`, branch `picsimlab-esp32`) adds exactly those callbacks:
pin write/direction, I2C, SPI, UART tx, RMT events out, plus
`qemu_picsimlab_set_pin` and `uart_receive` inbound. [V, read from
`bsim_qemu.cc`]

**So the value sits in the fork, not upstream.** Which makes the PICSimLab
build blocker (OH-9) load-bearing for the entire ESP path — see §7.

### 4.6 Prebuilt binaries, checked 2026-09-04 (OH-158)

Three tickets -- OH-36, OH-64 and OH-9 -- were blocked on tools this machine
does not have, and in each case the test performed was "can it be BUILT
here", never "can a prebuilt be obtained". Asked directly, both answers are
**yes** [V], and **neither was installed**: that is the machine owner's
decision, not a ticket's.

| Tool | Prebuilt? | Where | What is offered | Integrity | Licence |
|---|---|---|---|---|---|
| QEMU for Windows | **YES** [V] | `https://qemu.weilnetz.de/w64/`, the build qemu.org's own download page links | `qemu-w64-setup-20260811.exe`, described on the index as the QEMU 11.1.0 installer; 20260805 and 20260729 also listed | `qemu-w64-setup-20260811.sha512` beside it (`5bcf9eed...dbf543`); no `.sig` in the listing | GPLv2 |
| PICSimLab for Windows | **YES** [V] | GitHub releases of `lcgamboa/picsimlab` | stable `v0.9.2` (2024-10-05): `PICSimLab_0.9.2_241005_win64_setup.exe` 60,517,223 B and `_win64.zip` 92,937,379 B; rolling prerelease `latestbuild` (2026-08-30): `PICSimLab_0.9.3_260830_win64_setup.exe` 67,200,934 B, `_win64.zip` 99,424,702 B, and `PICSimLab_NOGUI-0.9.3_260830_Ubuntu_22.04.5_LTS_x86_64.AppImage` 16,595,448 B | **no checksum or signature asset on any release** | GPL-2.0 (per the GitHub API) |

**What was NOT verified, because it needs a download and nothing was
downloaded** [U]: whether the weilnetz installer carries `qemu-system-arm.exe`
(the index names it the QEMU installer and lists no per-target contents), and
whether PICSimLab's win64 zip carries the `share/` tree `install_root()` needs
(§7 records that the NOGUI AppImage bundles `lib/qemu`; the zip was not
opened). Secondary routes qemu.org names, unchecked: MSYS2's QEMU package.

Two more facts, from this machine rather than the network:

* **A QEMU is already here and is not usable.** The Android SDK emulator
  ships `qemu-system-armel.exe` and `qemu-system-aarch64.exe` under
  `AppData/Local/Android/Sdk/emulator/qemu/windows-x86_64/` (it reports
  "Android emulator version 36.2.12.0"). It is Google's fork: it needs the
  emulator's own DLL directory on PATH to start at all, rejects `-machine`
  as an unknown option, and `-cpu help` lists no Cortex-M. Not an oracle. [V]
* **OH-36's blocker (b) is stale.** It records "arm-none-eabi-gcc is
  absent". Resolved through the compile service's own toolchain table rather
  than through PATH, `toolchain-gccarmnoneeabi` is installed and runs --
  "xPack GNU Arm Embedded GCC x86_64" 12.3.1 -- and it is what builds the
  SAMD21 recipe today. It is not on PATH, which is almost certainly why a
  `which`-style check said otherwise; no cross toolchain here is. OH-36 is
  held by another session, so the finding lives here and in OH-158 rather
  than in that ticket. [V]

What this does **not** change is the single-source objection (§2). A running
QEMU turns "no oracle at all" for Armv7E-M and Armv8-M into "one source,
limitation recorded" -- the bar OH-36 already set for itself: it can detect a
disagreement and cannot adjudicate one. `ORACLES` in
`webui/boards/catalogue.py` now says so, because that string is what
`missing_cores()` shows a reader, and a stale entry there is what makes a
board look deader than it is.

---

## 5. Raspberry Pi silicon

### 5.1 RP2040 — integrate `rp2040js`

MIT, TypeScript, browser-native, by the author of Wokwi. Full Armv6-M core,
GDB server, and 28 peripheral modules including **PIO** and **USB** — each of
which is a larger job than the CPU. Runs real Arduino, MicroPython and
CircuitPython builds. [V]

Its correctness story is the part that matters here: instructions were verified
with **gdbdiff — lockstep against real RP2040 silicon, diffing register state
instruction by instruction** — and it caught genuine bugs in ADCS overflow, CMP
carry and LSRS edge cases. [V]

That is our methodology, already executed once, informally and without a
published corpus. **The gap worth filling is not the emulator. It is turning
that one-off into a continuously-checked claim.**

Caveats: its clocks are an "always ready" stub with no frequency semantics; no
FC0; RP2350 unsupported.

### 5.2 The RP2040 spin-wait list, verified from pico-sdk source

Every place startup polls a status bit [V, fetched from pico-sdk master]:

| Register | Source file | Behaviour needed |
|---|---|---|
| `RESETS.RESET_DONE` | `resets.h` | bits set immediately after un-reset |
| `XOSC.STATUS.STABLE` | `xosc.c` | return stable |
| `PLL CS.LOCK` (×2) | `pll.c` | return locked — runs for sys and usb |
| `CLOCKS.CLK_{REF,SYS}_SELECTED` | `clocks.c` | one-hot readback of the requested source |
| `FC0_STATUS` RUNNING/DONE | `clocks.c` | tier 2 — MicroPython hits it, blink does not |

Plus: the TIMER must actually advance, because `delay()` uses a timer **alarm
interrupt**, not polling — a frozen timer is indistinguishable from a hang.
And `SIO` CPUID must return 0, or crt0 branches into the core-1 park loop.

**GPIO on RP2040 is unusual and worth internalising**: output does not go
through an APB peripheral. The SIO block at 0xD0000000 sits on the M0+'s
single-cycle IOPORT bus — `digitalWrite` is one store to `GPIO_OUT_SET/CLR`.
But SIO only drives the pad if `IO_BANK0`'s `FUNCSEL` selects function 5.

**XIAO RP2040 specifics** [V]: `LED_BUILTIN` is **GPIO17** (red, **active-low**)
— green 16, blue 25. Every "Pico blink" tutorial targets GPIO25 and therefore
lights the *blue* LED on this board.

### 5.3 UF2, the firmware format

512-byte blocks, each self-contained and self-locating [V]:

| Offset | Field |
|---|---|
| 0 | magic `0x0A324655` |
| 4 | magic `0x9E5D5157` |
| 8 | flags |
| 12 | **targetAddr** — where this block's payload goes |
| 16 | payloadSize (256 on RP2040) |
| 28 | familyID when flag `0x2000` set |
| 32 | 476 bytes of data |
| 508 | magic `0x0AB16F30` |

Family IDs: RP2040 `0xE48BFF56`; RP2350 ARM-S `0xE48BFF59`, RISC-V
`0xE48BFF5A`, ARM-NS `0xE48BFF5B`.

A parser is ~50 lines. **Prefer UF2 as the canonical input** — it is what both
IDEs emit, it carries addresses per block, and a wrong-family file can be
rejected with a good error. `.bin` is address-free; `.elf` is worth accepting
as a second input for symbols.

### 5.4 RP2350 — two doors, one much cheaper

The chip carries **both** dual Cortex-M33 and dual Hazard3 RISC-V cores;
whichever is unused is held in reset. [V]

The M33s are configured with **Security, DSP and FPU extensions** plus 8 SAU
and 16 MPU regions [V] — that is far past plain Armv8-M mainline, and secondary
sources put the resulting instruction count in the 300–450 range [U, flagged
for a primary-source pass on DDI 0553].

**Hazard3 is the cheaper door.** Open source (Apache-2.0), by a Raspberry Pi
engineer, and the RP2350 datasheet §3.8 states the exact configuration [V]:

```
rv32ima_zicsr_zifencei_zba_zbb_zbs_zbkb_zca_zcb_zcmp
```

plus four custom extensions — `Xh3power`, `Xh3bextm`, `Xh3irq`, `Xh3pmpm` —
of which only `Xh3irq` matters before you model interrupts. **137 mnemonics**
including pseudo-ops, from the datasheet's own alphabetical index [V].

**Measured 2026-10-08 under OH-157, walking through that door** [V], against
pico-sdk 2.3.0's `src/rp2350/hardware_regs` (`98a542c`, the submodule
arduino-pico `33201a6` pins) and the datasheet at build `80d627281ed5`
(sha256 `a638d6780da919162660691bfa02c6dcf7c2a0b6e9f18e2d7519c80b664a2e39`).
Four things this section did not have:

* **A bare-metal blink needs no Zbb, and that is now a fact about the
  program.** riscv32-esp-elf GCC 14.2.0 emits the same blink bytes under
  `-march=rv32imac` and under the full string above, while the same compiler
  emits `clz`, `minu` and `rev8` for a three-line probe under the full string
  and none of them under `rv32imac`. GCC 8.4, the RISC-V compiler this
  repository had before, rejects `_zbb` and `_zbkb` outright, so it could not
  tell those two cases apart.
* **Entry needs no vector table and no boot2.** The minimum RISC-V IMAGE_DEF
  is twenty bytes inside the first 4 kB, and with no entry point named "the
  bootrom will enter the binary at its lowest address" (datasheet 5.9.5.2,
  Table 504) -- the rule `core/riscv32/machine.py` already enters by. The
  ROM's source is BSD-3-Clause (datasheet chapter 5), unlike the RP2040's.
* **A pad is isolated until software releases it**, which the RP2040 has no
  equivalent of: each PADS_BANK0 pad's `ISO` resets to 1 and latches the pad
  (datasheet 9.7). And every SIO offset past `GPIO_OUT` moved: the RP2040's
  `GPIO_OE` offset is the RP2350's `GPIO_OUT_CLR`.
* **The two sources disagree about the mailbox's depth**: pico-sdk's `sio.h`
  says eight words, the datasheet's 3.1.5 four entries. Recorded, not
  resolved; a stub that never fills it depends on neither.

### 5.5 The dual-core question

For a first emulator, **core 1 can simply not exist** [V]. At reset core 1 runs
bootrom code that parks itself, draining its mailbox and waiting for a six-word
handshake `{0, 0, 1, vector_table, sp, entry}` from core 0. Nothing at boot
spins waiting *for* core 1 — it is the reverse. The SIO FIFO registers need to
exist as stubs that do not fault; a second register file and pipeline can wait
until someone wants `multicore_launch_core1` or FreeRTOS SMP.

---

## 6. Boards, and whose CAD we can import

This project already imports 25 Seeed XIAO boards from vendor KiCad. Ranked by
how usable each vendor's published design files are [V for the mechanisms]:

| Rank | Vendor | Format | Notes |
|---|---|---|---|
| 1 | **Olimex** | **native KiCad** (newer), Eagle (older) | True OSHW, CC-BY-SA, one repo per board with `HARDWARE/` per revision. Covers **both** ESP32 and STM32. Closest to our existing pipeline. |
| 2 | **SparkFun** | **native KiCad** (newer) | Thing Plus ESP32-S3 and ESP32-C5 confirmed `.kicad_pcb` in-repo. |
| 3 | **Adafruit** | Eagle | Huge catalogue, one `Adafruit-<name>-PCB` repo each. KiCad imports Eagle natively. |
| 4 | **Seeed** | KiCad | Already in use. |
| 5 | **Espressif** | schematic/PCB **PDF** + dimensions **DXF** + reference-design ZIP | DXF gives outline and pin positions, no netlist. |
| 6 | **ST** | **Altium** source + gerbers + BOM | Per-product-page "CAD Resources", occasionally login-walled. Complete data, more friction. KiCad 7+ imports Altium usably. |
| 7 | WeAct / LilyGO / M5Stack / Wemos | schematic **PDF only** | Not importable as CAD. |
| 8 | "Blue Pill" | none | Community redraws only (stm32-base.org). Beware counterfeit F103s. |

**Nucleo naming**: `NUCLEO-` + MCU shorthand; the 32/64/144 suffix is the MCU
package pin count, which sets board size and headers — Nucleo-32 takes Arduino
Nano headers, Nucleo-64 takes Uno R3 plus ST morpho, Nucleo-144 adds Zio and
usually Ethernet. All carry an on-board ST-LINK. **Discovery** kits are feature
demonstrators with board-specific headers; **Eval** boards are full reference
designs at $200+.

Also worth noting: **Seeed announced a XIAO ESP32-C5** (~$6.90, first XIAO with
5 GHz WiFi 6) [V board listing; design files not yet checked]. It would extend
the 25 boards already imported.

---

## 7. Contradictions and open questions

Recorded rather than resolved, because both sides were argued by agents that
fetched sources.

**"ESP32-S31" — RESOLVED: it exists, and it is RISC-V.** [V] This was recorded
as disputed — one agent citing an Espressif news page, another concluding the
string was garbled and excluding the part. The instruction was "do not treat
S31 as real until a datasheet is fetched". No datasheet exists (the URL still
404s), but three converging **non**-datasheet lines settle it, and the first is
Espressif's own published silicon artefact:

1. **`espressif/esp-rom-elfs` publishes `esp32s31_rev0_rom.elf`.** Read
   directly: `e_machine = 0xF3` (RISC-V) with **345,660 bytes** of real
   `PT_LOAD` content — not a stub — and an entry point of `0x2f800000`, a
   different address space from both C3 (`0x40000000`) and S3
   (`0x40000400`). The control case holds in the same release: S3 really is
   Xtensa (`0x5E`), so the "S" prefix does **not** imply Xtensa.
2. `toolchain-esp32s31.cmake` sets `_CMAKE_TOOLCHAIN_PREFIX riscv32-esp-elf-`.
3. Espressif's LLVM fork defines `ESPRESSIF_ESP32S31` as a
   `RISCVProcessorModel`.

**ISA, from two machine-readable sources** — IDF's
`components/soc/project_include.cmake` and LLVM's `RISCVProcessors.td`:

```
rv32imafcb_zicsr_zifencei_zcb_zcmp_zcmt_xesploop_xespv
```

the largest in the Espressif family. Two things make it notable: `soc_caps.h`
gives it `ZC_EXTENSIONS=1` with **no** `ZCMP_WORKAROUND`, making it the only
ESP part shipping Zc on by default; and it needs two vendor extensions that
riscv-unified-db does not contain, so those would be ours to write.

**Evidence class: toolchain-sourced, not datasheet-sourced** — see the C2
lesson in §4.2 before treating this as equivalent to a `[V]` datasheet row.
One honest disagreement inside it: LLVM omits Zcmp with a "TODO … HW bug
workaround" comment while IDF's GCC path emits it. GCC-yes / Clang-not-yet,
recorded rather than picked.

**ESP32-H4's exact ISA string** is unconfirmed — RV32IMAC by lineage, no public
TRM. [U]

**ESP32-P4 clock**: the datasheet says 400 MHz, a secondary repost says
360 MHz — probably an earlier silicon revision. Trust the datasheet.

**Armv8-M mainline instruction count** was not verified from primary source;
the 300–450 range is secondary. Needs a pass on DDI 0553.

**STM32 register/bit names in §3.3** are drawn from Armv6-M architecture
knowledge and general STM32 design, not from a reference manual fetched this
session — one agent lost WebFetch to st.com timeouts throughout. Cross-check
RM0091 (F0), RM0451 (L0), RM0454 (G0), RM0490 (C0) before treating exact names
as implementable.

**The PICSimLab build turned out not to gate anything — and our own note was
wrong.** `known-issues.md` 4a.6 asserted that GCC 11.4 on Ubuntu 22.04 cannot
link the NOGUI build. Upstream's CI disproves it, and the evidence is inside
our own reference clone: `.github/workflows/linux-release.yml` runs a
`[ubuntu-22.04, ubuntu-24.04]` matrix, gates the appimage step to 22.04, and
that step runs `bscripts/build_appimage.sh`, whose line 68 performs the NOGUI
link — on every master push. [V]

The published `PICSimLab_NOGUI-0.9.3_260822_Ubuntu_22.04.5_LTS_x86_64.AppImage`
is 16,435,704 bytes, returns HTTP 200, and was built from commit `62e8b5b` —
**the exact commit our clone sits on.** [V] So the local ICE is environmental,
not a property of this source and this compiler. 4a.6 has been corrected.

Better still: `build_appimage.sh` copies `lib/qemu` into the AppDir, so the
prebuilt NOGUI AppImage **already bundles `libqemu-riscv32`, `libqemu-xtensa`
and the ESP ROM images** [V] — the whole stack the ESP path needs, with no
build at all. And since nothing in OH-9 requires NOGUI, and 4a.6 records the
WX GUI build working here, the adapter work can proceed today.

---

## 8. If we do one thing next

**STM32C0 — ~~or F030~~ — built here, verified against a corpus we capture
ourselves from a Nucleo over SWD.**

> **F030 is struck.** [V] It is a Cortex-**M0**, not M0+, and the two differ in
> a way that decides this plan. `core_cm0.h` mentions **VTOR zero times**;
> `core_cm0plus.h` mentions it 14. With no VTOR the vector table is pinned at
> `0x00000000`, so a per-case HardFault handler **cannot be relocated** — and
> the fault-outcome class below is the main reason to buy hardware at all.
> There is a second delta: `CONTROL.nPRIV` exists only on M0+, so an M0 has no
> unprivileged thread mode. **Capture on M0+**; an M0 corpus is a strict subset
> derivable from an M0+ one, never the reverse, and the corpus format must
> record which variant it came from.

It is the only combination where all four are true at once: the ISA is small
and precisely specified from a free primary source; the prior art is weakest
exactly on correctness (Renode's G0 clock model is an admitted stub, QEMU's
classic STM32 machines cannot even blink); the licences allow an MIT
implementation where LGPL `tlib` and GPL QEMU do not; and the oracle hardware
costs about twelve pounds.

Everything else on this page is either already solved by someone with a better
licence than we could offer (RP2040), or gated behind an SoC wall that has
nothing to do with instruction-level correctness (ESP).

### 8.1 The throughput question is answered, and the answer moves the plan

This section previously left "how many cases per second?" as the one open
question, estimated at 20–50/sec and requiring hardware to settle. It was
settled **without hardware** [V], by driving pyOCD's own packer and reading the
constants out of Arm's CMSIS-DAP reference firmware, pyOCD and OpenOCD:

| Rig | Limited by | cases/s | 2.797 M cases |
|---|---|---|---|
| ST-LINK/V3 + OpenOCD dap-direct, SWD 24 MHz | USB | **~2,000** | 0.4 h |
| RPi Debug Probe (CMSIS-DAP), lean, SWD 4 MHz | USB | **~333** | 2.3 h |
| Nucleo ST-LINK/V2-1 + OpenOCD dap-direct | SWD | **~245** | 3.2 h |
| Nucleo ST-LINK/V2-1 + **pyOCD** | USB | **19** | **42 h** |

**≈250–350 cases/sec for a competent rig — 2–3 hours, not two days.** The 10×
spread is real but it is *host tooling*, not physics: OpenOCD's ST-LINK driver
batches 64 MEM-AP accesses per USB transaction (1227 on V3) and reads all 21
registers in one, and **pyOCD's ST-LINK backend does neither**. So drive it
with OpenOCD `interface/stlink-dap.cfg` (firmware ≥V2J32), or bypass the
on-board probe — every Nucleo brings SWD out — with a ~£12 Raspberry Pi Debug
Probe, which is CMSIS-DAP and batches natively. **The board decision is really
a probe decision.**

**OPEN, and it gates the purchase:** confirm the NUCLEO-C031C6's on-board
debugger revision. V2-1 is USB full speed; V3E is high speed with a 19× larger
batch. It decides between the top and bottom rows above. Answerable from the
board's silkscreen or UM2953 — not from here, since st.com fails at the
connection level from this network.

### 8.2 Buy the board for the fault space, not for throughput

The reason to buy silicon changed. **No free Armv6-M model implements faults at
all** [V]: rp2040js never calls `exceptionEntry(EXC_HARDFAULT)` — an unknown
opcode reaches `logger.warn('… not implemented yet!')` and execution continues
— and thumbulator's `decode_error()` prints to stderr and calls `sim_exit(1)`.
They are a good oracle for the defined instruction space and a **null oracle
for the fault space**.

And which variant each oracle models turns out to be a hard constraint, not a
configuration detail:

| Oracle | Variant | Matches a Nucleo-C031C6 (M0+)? |
|---|---|---|
| **rp2040js** | **M0+** — has VTOR and `nPRIV` | **yes** |
| thumbulator | M0 — zero VTOR references | no |
| QEMU | **M0 only** — `arm_v7m_cpus[]` has no `cortex-m0plus` at all | no |
| Arm FVP | both — ships M0 and M0plus binaries | yes, but see below |

So **build the generator against rp2040js first**: MIT, independent of QEMU,
the only free oracle matching the target variant, and it runs here today at
**1,188,334 cases/sec** [V] — three orders of magnitude faster than any
hardware rig, which is what makes it the right place to debug the schema,
operand filters and differ before a board arrives.

**The Arm FVP is licence-blocked pending a human decision.** It downloads
unauthenticated, its sha256 matches Arm's published digest, and it runs here
[V]. The EULA alone would permit a corpus — clause 3.1(e) preserves the right
to distribute "Reports". But EULA note (B) makes `supplementary_terms.txt`
**prevail**, and its paragraph 2 scopes *"testing, debugging, analysing …
**Software Models**"* to holders of an Arm architecture licence, with
"Software" defined to exclude Software Models. An Armv6-M core in this
repository is a Software Model by that file's own definition. **This is a
reading of the terms, not legal advice. Default: build nothing on the FVP.**
