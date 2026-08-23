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
| **RP2350** | Hazard3 RISC-V | **Strongest oracle in the field** | Open source Apache-2.0, the datasheet states the exact ISA string, **and the repo ships its own C++17 golden model** — see §2.1b. |

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

### 2.1b Hazard3 ships its own golden model — the cheapest oracle in the field

The strongest single finding of the survey. `Hazard3`'s repository contains
**`test/sim/rvcpp/`, a ~1080-line C++17 ISA simulator written by the same
author as the silicon**, covering exactly the RP2350 configuration. Apache-2.0.
Builds with `g++ -std=c++17`, no dependencies and **no cross-compiler**. Its
`RVCore` exposes `regs[32]`, `pc`, `csr` and `step()` as plain public members —
it is already the shape a SingleStepTests-style fixture generator needs.
Roughly 150 lines of new C++ turns it into one. [V]

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
instruction. The difference does not change a decoder (both agree `UDF` means
"refuse"), but it is recorded rather than silently averaged. The same agent
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
2. **A custom interrupt matrix, not a PLIC.** ESP RISC-V chips route peripheral
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
| **ESP32-P4** | **RV32IMAFC** + Zc + XespV + XespLoop | 2 HP + 1 LP | 400 / 40 MHz | **None** — pairs with a C6 over SDIO |

The S2 and S3 also carry a **ULP RISC-V coprocessor** (RV32IMC) beside their
Xtensa main cores, restricted to RTC memory and registers. [V]

**ESP32-C3 is confirmed RV32IMC with no atomics**, quoted from the datasheet
and corroborated behaviourally: ESP-IDF's C3 port uses critical sections rather
than LR/SC *because* the core lacks A. [V] A decoder that accepts `lr.w` on C3
is out of spec.

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
10. Interrupt matrix, NOT a PLIC. 43 sources to 32 CPU lines, 7 priorities,
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

**Two licence traps** [V], both worth catching before anyone vendors anything:

1. `espressif/xtensa-isa-doc` — the README says CC-BY-SA-3.0, the LICENSE file
   says **Attribution-NonCommercial-ShareAlike**. The repository contradicts
   itself. It cannot go into an MIT tree.
2. Espressif QEMU's `target/xtensa/core-esp32s3/xtensa-modules.inc.c` is
   1.31 MB of **vendor-generated** Tensilica decode tables, imported from a
   Cadence overlay rather than reverse-engineered. GPL-2. External process
   only, never in-tree.

### 4.5 What QEMU does and does not give you

Espressif's QEMU fork supports **ESP32, ESP32-S3 and ESP32-C3 only** — no C5,
no C6. And on *every* target it emulates **no GPIO matrix or IO MUX, no I2C,
I2S, SPI, RMT, USB, WiFi, BLE or ULP**. [V]

That looks fatal for our purposes, and it is — for *stock* QEMU. PICSimLab's
fork (`lcgamboa/qemu`, branch `picsimlab-esp32`) adds exactly those callbacks:
pin write/direction, I2C, SPI, UART tx, RMT events out, plus
`qemu_picsimlab_set_pin` and `uart_receive` inbound. [V, read from
`bsim_qemu.cc`]

**So the value sits in the fork, not upstream.** Which makes the PICSimLab
build blocker (OH-9) load-bearing for the entire ESP path — see §7.

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

**"ESP32-S31" — disputed.** One agent reports a dual-core RISC-V part at
320 MHz with WiFi 6, BLE 5.4 including Classic, 802.15.4 and a gigabit Ethernet
MAC, announced 2026-03-26, citing an Espressif news page and Hackaday. Another
agent, enumerating boards, saw a similar string in one page render and
concluded it was **garbled, could not verify the chip exists, and excluded it**.
**Do not treat S31 as real until a datasheet is fetched.** If it is real it is
preview-only with no public TRM either way.

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

**STM32C0 or F030, built here, verified against a corpus we capture ourselves
from a Nucleo over SWD.**

It is the only combination where all four are true at once: the ISA is small
and precisely specified from a free primary source; the prior art is weakest
exactly on correctness (Renode's G0 clock model is an admitted stub, QEMU's
classic STM32 machines cannot even blink); the licences allow an MIT
implementation where LGPL `tlib` and GPL QEMU do not; and the oracle hardware
costs about twelve pounds.

Everything else on this page is either already solved by someone with a better
licence than we could offer (RP2040), or gated behind an SoC wall that has
nothing to do with instruction-level correctness (ESP).
