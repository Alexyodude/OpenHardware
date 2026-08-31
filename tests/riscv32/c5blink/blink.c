/* OpenHardware - a bare-metal ESP32-C5 blink that uses the part's own Zc.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * The third sibling of `tests/riscv32/c3blink/blink.c` and
 * `tests/riscv32/c6blink/blink.c`, and reading the three side by side stays
 * the point: same `_start`, same shape, and not one address in common with
 * either. What THIS one has that they do not is the reason it exists at all:
 * an ESP32-C5 is `RV32IMAC + Zcb/Zcmp/Zcmt`, and this image exercises all
 * three groups, so watching it run is watching the part's own instruction
 * set rather than the subset every RV32 part shares (OH-147).
 *
 * ## The Zc encodings are hand-placed `.hword`s, and that is provenance
 *
 * This machine's `riscv32-esp-elf-gcc` is 8.4.0, which predates the Zc
 * ratification and refuses `-march=rv32imac_zcb_zcmp_zcmt` outright -- so
 * the compiler cannot emit these instructions and the assembler cannot name
 * them. The encodings are therefore written as halfwords with their fields
 * stated, the same way `tests/riscv32/test_zc.py` builds them -- and that
 * file, plus the rvcpp cross-checks recorded in OH-146, is what makes a
 * hand encoding here BETTER evidence than a newer toolchain would be: every
 * one of these four halfwords is already executed and asserted elsewhere in
 * this repository before this image runs them in sequence.
 *
 *     0xB852  cm.push {ra, s0}, -16    101 11000 0101 00 10   Zcmp
 *     0xBE52  cm.popret {ra, s0}, 16   101 11110 0101 00 10   Zcmp
 *     0x9CF5  c.not s1                 100 111 001 11 101 01  Zcb
 *     0xA082  cm.jalt 32               101 000 00100000 10    Zcmt
 *
 * ## Addresses, from ESP-IDF v5.5.0 (`8c750b0`), and every one different
 *
 * The same headers `webui/boards/esp32c5.py` cites, read the same way:
 *
 *     components/soc/esp32c5/register/soc/reg_base.h
 *         DR_REG_GPIO_BASE   0x60091000   (a C6's is 0x60091000 too -- the
 *                                          REGISTERS inside differ)
 *     components/soc/esp32c5/register/soc/gpio_reg.h
 *         GPIO_OUT_REG       (base + 0x4)
 *         GPIO_ENABLE_REG    (base + 0x34)  (a C6's ENABLE is base + 0x20)
 *     components/soc/esp32c5/include/soc/soc.h
 *         SOC_IRAM_LOW = 0x40800000, SOC_IRAM_HIGH = 0x40860000
 *
 * ## No LED wired, no atomics emitted
 *
 * GPIO8 is ESP-IDF's own blink default, a real output on this part; plain C
 * with no `__atomic_*` emits no atomic, so the A in `-march=rv32imac` is in
 * the string and not in the image -- the same statement the C6 fixture
 * makes, load-bearing here for the same reason.
 *
 * ## Build
 *
 *     riscv32-esp-elf-gcc -march=rv32imac -mabi=ilp32 -Os -nostartfiles \
 *         -nostdlib -T blink.ld -o blink.elf blink.c
 *     riscv32-esp-elf-objcopy -O binary blink.elf blink.bin
 */

#define GPIO_OUT     (*(volatile unsigned int *)0x60091004)
#define GPIO_ENABLE  (*(volatile unsigned int *)0x60091034)

#define LED 8

/* The top of SRAM, minus a word so the first push stays inside it.
 * SOC_IRAM_HIGH is 0x40860000 and the stack grows down. */
#define STACK_TOP 0x4085FFF0

int main(void);

/* The entry point, and the whole of what a crt0 would do here. `naked`
 * because a prologue would use the stack this is setting up. */
__attribute__((naked, section(".text.start"))) void _start(void) {
    __asm__ volatile(
        "li sp, %0\n"
        "j  main\n"
        :: "i"(STACK_TOP)
    );
}

/* The delay, framed by Zcmp's own pair and counting through Zcb's c.not.
 * `naked` so the compiler adds no second prologue around the hand-placed
 * one; s1 is deliberately NOT in the pushed list, and the call site says
 * so in its clobbers. */
__attribute__((naked)) void zc_pause(void) {
    __asm__ volatile(
        ".hword 0xB852\n"        /* cm.push {ra, s0}, -16 */
        "li s0, 100\n"
        "1:\n"
        ".hword 0x9CF5\n"        /* c.not s1 */
        ".hword 0x9CF5\n"        /* c.not s1 -- round-tripped, not junk */
        "addi s0, s0, -1\n"
        "bnez s0, 1b\n"
        ".hword 0xBE52\n"        /* cm.popret {ra, s0}, 16 */
    );
}

/* The jump-vector table cm.jalt reads through. 64-aligned because JVT's
 * mode bits are WARL zeros, so the base has no room for a smaller
 * alignment; slot 32 because indices below 32 are the non-linking cm.jt
 * range and a call wants its return address. */
__attribute__((aligned(64))) const unsigned int jvt_table[33] = {
    [32] = (unsigned int)&zc_pause,
};

int main(void) {
    __asm__ volatile(
        "la t0, jvt_table\n"
        "csrw 0x017, t0\n"       /* jvt: the one CSR the core has */
        ::: "t0"
    );
    GPIO_ENABLE |= (1u << LED);

    for (;;) {
        GPIO_OUT ^= (1u << LED);
        /* cm.jalt 32 -> zc_pause, through the table. ra is the link the
         * jump writes; s1 is what zc_pause leaves inverted-and-restored. */
        __asm__ volatile(".hword 0xA082" ::: "ra", "s1");
    }
}
