/* OpenHardware - a bare-metal ESP32-C6 blink, for proving the second RV32 board.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * The sibling of `tests/riscv32/c3blink/blink.c`, and reading them side by
 * side is the point: same shape, same `_start`, and **not one address in
 * common**. If a C6 were a C3 with a different name, this file would be a
 * copy and there would be no reason to have it.
 *
 * ## Why it sets its own stack pointer
 *
 * The same reason the C3 fixture does, and it is not a shortcut. An Armv6-M
 * part loads SP from its vector table before its first instruction; an RV32
 * part does not, so `crt0` sets it, and a `-nostartfiles` build has no crt0.
 * Without `_start` the first `addi sp, sp, -16` makes `sp` 0xFFFFFFF0 and the
 * next store faults -- which is the core reporting correctly on an image that
 * never set up its stack, not a gap in the model.
 *
 * ## Addresses, from ESP-IDF v5.5.0 (`8c750b0`), and every one different
 *
 *     components/soc/esp32c6/register/soc/reg_base.h:48
 *         DR_REG_GPIO_BASE   0x60091000        (a C3's is 0x60004000)
 *     components/soc/esp32c6/register/soc/gpio_reg.h:29
 *         GPIO_OUT_REG       (base + 0x4)
 *     components/soc/esp32c6/register/soc/gpio_reg.h:113
 *         GPIO_ENABLE_REG    (base + 0x20)
 *     components/soc/esp32c6/include/soc/soc.h:162-165
 *         SOC_IRAM_LOW = SOC_DRAM_LOW = 0x40800000
 *         SOC_IRAM_HIGH = SOC_DRAM_HIGH = 0x40880000
 *
 * See `docs/esp-idf-reference.md` for how to get that tree. The C3's numbers
 * come from Espressif's headers too, by a different route -- and IDF v5.5
 * reproduces all of them, which is what licensed using it for these two parts.
 *
 * **SRAM has one address here, not two.** On a C3 the same 384 KB appears at
 * 0x3FC80000 on the data bus and 0x4037C000 on the instruction bus, and
 * `webui/boards/esp32c3.py` can map only one of them. The C6's `soc.h` gives
 * IRAM and DRAM the *same* low and high, so 0x40800000 is the whole story and
 * a stack pointer into it needs no note about which bus it belongs to.
 *
 * ## No LED, and no atomics
 *
 * No user LED is claimed: this watches a GPIO register rather than a pin
 * anything is wired to. GPIO8 is ESP-IDF's own blink default --
 * `examples/get-started/blink/main/Kconfig.projbuild:34-37`, `default 8` --
 * and a real output on this part either way.
 *
 * Compiled `-march=rv32imac`, which is what ESP-IDF compiles a C6 with
 * (`tools/cmake/toolchain-esp32c6.cmake:10`, less the `_zicsr_zifencei` this
 * GCC 8.4 is too old to name). The `a` is in the string and **not in the
 * image**: plain C with no `__atomic_*` emits no atomic, which is what makes
 * this runnable on a core that classifies A and does not execute it.
 * `test_the_board_declares_the_a_this_core_does_not_execute` is the other half
 * of that statement, and it fails if an atomic ever appears here.
 */

#define GPIO_OUT     (*(volatile unsigned int *)0x60091004)
#define GPIO_ENABLE  (*(volatile unsigned int *)0x60091020)

#define LED 8

/* The top of SRAM, minus a word so the first push stays inside it.
 * SOC_DRAM_HIGH is 0x40880000 and the stack grows down. */
#define STACK_TOP 0x4087FFF0

int main(void);

/* The entry point, and the whole of what a crt0 would do here. `naked` because
 * a prologue would use the stack this is setting up. */
__attribute__((naked, section(".text.start"))) void _start(void) {
    __asm__ volatile(
        "li sp, %0\n"
        "j  main\n"
        :: "i"(STACK_TOP)
    );
}

int main(void) {
    GPIO_ENABLE |= (1u << LED);

    for (;;) {
        GPIO_OUT ^= (1u << LED);
        for (volatile unsigned int i = 0; i < 100; i++) {
        }
    }
}
