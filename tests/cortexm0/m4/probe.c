/* OpenHardware - a Cortex-M4 image that exists to be read, not to be run.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * ## This is not a blink, and the difference is the whole point
 *
 * Every other compiled fixture in this repository is a program that *runs*:
 * `tests/cortexm0/blink/blink.c` toggles a pin, `tests/riscv32/c6blink/blink.c`
 * drives GPIO8, and a test watches each of them execute. **Nothing executes
 * this one.** `core/cortexm0/exec.cc` implements Armv6-M and answers
 * `StepResult::Unimplemented` -- processor completely untouched -- for every
 * Thumb-2 encoding, so a Cortex-M4 image stops on its first wide instruction.
 * OH-50 records why that is where the work stopped: there is no execution
 * oracle on this machine, QEMU is not installed, and a Thumb-2 interpreter
 * verified only against tests written by the same author is the kind of
 * evidence this repository declines to produce.
 *
 * What there *is* an oracle for is the decode, and this file is its subject.
 * `tests/cortexm0/test_thumb2_disasm.py` disassembles the committed binary
 * with `core/cortexm0/disasm.py` and with `arm-none-eabi-objdump`, and every
 * line must match.
 *
 * ## So it is written to be varied rather than to be short
 *
 * A blink compiled for Armv7E-M emits about ten wide instructions, nearly all
 * of them `mov.w` and `bl`. That would check three branches of a decoder with
 * a dozen. This asks for the operations GCC has to reach into Thumb-2 for:
 *
 *   - 64-bit arithmetic, which needs `umlal`, `smlal`, `adc.w`
 *   - the bit intrinsics, which are `clz`, `rbit`, `rev.w`
 *   - a struct with mixed field widths, for `ldrb.w`, `strh.w`, `ldrd`
 *   - a switch, for a table branch or a chain of wide compares
 *   - division, which on this part is a single `sdiv`/`udiv` instruction and
 *     on an Armv6-M part is a library call
 *   - enough live values at once to force `stmdb`/`ldmia.w` over `push`/`pop`
 *
 * Compiled `-mthumb -march=armv7e-m -mfloat-abi=soft`. The soft float is
 * deliberate: an nRF52840 is a Cortex-M4**F** and its FPU is real, but the VFP
 * encodings are a separate space this decoder does not attempt, and putting
 * them in the fixture would mean committing an image whose expected
 * disassembly is mostly `.word`.
 */

#include <stdint.h>

volatile uint32_t *const PORT = (uint32_t *)0x50000504;

struct record {
    uint64_t stamp;
    uint32_t key;
    uint16_t flags;
    uint8_t tag;
    uint8_t level;
};

static struct record store[8];

/* 64-bit multiply-accumulate: umlal, smlal, adc.w. */
uint64_t accumulate(const uint32_t *values, uint32_t count) {
    uint64_t total = 0;
    int64_t signed_total = 0;
    for (uint32_t i = 0; i < count; i++) {
        total += (uint64_t)values[i] * (i + 1u);
        signed_total += (int64_t)(int32_t)values[i] * (int32_t)(i + 1u);
    }
    return total + (uint64_t)signed_total;
}

/* The bit intrinsics GCC lowers to single Armv7E-M instructions. */
uint32_t reshape(uint32_t value) {
    uint32_t out = 0;
    out += __builtin_clz(value | 1u);
    out ^= __builtin_bswap32(value);
    /* Written out rather than `__builtin_popcount`, which GCC lowers to a call
     * to libgcc's `__popcountsi2` -- and a `-nostdlib` link has no libgcc, so
     * the fixture would not build. The shift-and-mask form is also better for
     * this file's purpose: it emits `and.w` with a modified immediate, which
     * is the `_expand_immediate` path a call would not have exercised. */
    uint32_t bits = value - ((value >> 1) & 0x55555555u);
    bits = (bits & 0x33333333u) + ((bits >> 2) & 0x33333333u);
    out += (((bits + (bits >> 4)) & 0x0F0F0F0Fu) * 0x01010101u) >> 24;
    out ^= (value >> 11) | (value << 21);
    return out;
}

/* Mixed field widths, so the byte and halfword loads and stores appear. */
void record_event(uint32_t index, uint32_t key, uint8_t tag) {
    struct record *slot = &store[index & 7u];
    slot->key = key;
    slot->tag = tag;
    slot->flags = (uint16_t)(key >> 16);
    slot->level = (uint8_t)(slot->level + 1u);
    slot->stamp += key;
}

/* Division, which is one instruction here and a library call on Armv6-M. */
uint32_t ratio(uint32_t numerator, uint32_t denominator, int32_t bias) {
    if (denominator == 0u) {
        return 0u;
    }
    return (numerator / denominator) + (uint32_t)(bias / 3);
}

/* A switch wide enough that the compiler stops using a chain of compares. */
uint32_t classify(uint32_t code) {
    switch (code) {
    case 0: return 11u;
    case 1: return 22u;
    case 2: return 33u;
    case 3: return 44u;
    case 4: return 55u;
    case 5: return 66u;
    case 6: return 77u;
    case 7: return 88u;
    default: return 99u;
    }
}

/* Enough live values to force the wide register list. */
uint32_t mix(uint32_t a, uint32_t b, uint32_t c, uint32_t d) {
    uint32_t p = reshape(a), q = reshape(b), r = reshape(c), s = reshape(d);
    uint32_t t = classify(p & 7u), u = ratio(q, r | 1u, (int32_t)s);
    return p + q + r + s + t + u;
}

void _start(void) {
    uint32_t values[4] = {1u, 2u, 3u, 4u};
    record_event(0u, 0xDEADBEEFu, 0x5Au);
    *PORT = (uint32_t)accumulate(values, 4u);
    *PORT = mix(values[0], values[1], values[2], values[3]);
    for (;;) {
    }
}
