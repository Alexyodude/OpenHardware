# Peripheral-layer research — NOT adopted

Everything in this directory is **research output from a single session, not
repository policy.** Nothing here is loaded by any code, checked by any
checker, or referenced by any rule. Adopting any of it is a separate decision
and needs its own ticket.

It is here because it existed only in a session-scoped scratchpad that is
destroyed when that session ends, and re-deriving it would mean redoing work
that carries real citations to vendor source.

## What is here

| Path | What | Author |
|---|---|---|
| `design.md` | The peripheral-layer design — taxonomy, file shapes, C++/Python boundary, spin detector, drafting policy, verification ladder, evidence tally. Nine provenance rounds, each naming its evidence and its author. | `stm-soc` |
| `esp32c3/` | Chip file, TIMG contract, RTC_CNTL, SYSTEM, IO_MUX, GPIO and UART contracts, boot sequence | `esp-soc`, `esp-soc-2` |
| `rp2040_v2/` | Chip file plus RESETS, XOSC, PLL, CLOCKS, IO_BANK0, PADS_BANK0 regmaps and three coded-model notes | `rpi-soc-2` |
| `stm32c0/` | STM32C031C6 chip file, RCC and FLASH regmaps, GPIO and USART contracts | `stm-soc-2` |

## How to read it, if it is ever adopted

**§6 of `design.md` is the scoping test**, and it is the most useful page here.
It counts how many architectures forced each schema feature:

- kinds 1–8, the read-purity rule, the spin detector, the reads-as-written
  default — **three** architectures. First version.
- multi-source `follows` (`op`, uniform `when`) — **two**. First version, but
  its no-nesting boundary is load-bearing.
- `atomic_aliases` with a per-peripheral opt-out — **one**, and its first
  mechanism was adopted, hardened with a checker rule, and *then* disproven.
  Ships marked RP2040-shaped until a second chip exercises it.

The inference that makes the tally worth keeping: a feature driven by one chip
is one datasheet reading away from another inversion.

## What to distrust

Every claim in these files carries an evidence class, and they are not
equivalent. `verified:` strings say what was checked and against what — and in
the STM32 files, separately for bits/offsets versus reset values, because ST's
own SVD declares an `RCC_CR` reset value that contradicts both RM0490 and
CMSIS's `SystemCoreClock`.

Two known-unfinished threads are recorded inside the files themselves rather
than here, so they cannot drift: the ESP32-C3 RTC_CNTL merge (two agents wrote
competing descriptions; the ruling and the reason are in the files), and the
`atomic_aliases` mechanism above.
