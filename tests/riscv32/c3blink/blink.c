/* OpenHardware - a bare-metal ESP32-C3 blink, for proving the RISC-V core.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * No ESP-IDF and no startup files, for the reason the Arm and AVR fixtures
 * give: a vendor runtime brings code this project would have to model before
 * the thing under test ever runs. ESP-IDF also reads `mstatus` and `mtvec`
 * within its first hundred instructions, and this core has no CSRs.
 *
 * ## It sets its own stack pointer, and that is not a shortcut
 *
 * An Armv6-M part loads SP from the vector table before its first instruction.
 * An RV32 part does not: `sp` is whatever reset left it, and **every** RISC-V
 * image begins by setting it -- that is what `crt0` is for. Built with
 * `-nostartfiles` there is no crt0, so `_start` below does the one thing it
 * would have done.
 *
 * Without it the first `addi sp, sp, -16` makes `sp` 0xFFFFFFF0 and the next
 * store faults. That is the core reporting correctly on an image that never
 * set up its stack, not a gap in the model -- so the fix belongs here rather
 * than in `webui/boards/esp32c3.py` inventing a stack pointer for it.
 *
 * Addresses from Espressif's own SoC headers, which is where
 * `webui/boards/esp32c3.py` cites them from too:
 *
 *     soc.h:45         DR_REG_GPIO_BASE  0x60004000
 *     soc.h:227-228    SOC_DRAM_LOW      0x3FC80000 .. SOC_DRAM_HIGH 0x3FCE0000
 *     gpio_reg.h:58    GPIO_OUT_REG      (base + 0x4)
 *     gpio_reg.h:90    GPIO_ENABLE_REG   (base + 0x20)
 *
 * **The XIAO ESP32-C3 has no user LED** -- Seeed's own variant file
 * `XIAO_ESP32C3/pins_arduino.h` is 34 lines and never says "LED". So this
 * watches a GPIO register rather than a pin anything is wired to. GPIO8 is
 * what Espressif's DevKitM-1 uses and is a real output either way.
 *
 * Compiled with -march=rv32imc, so the compiler emits compressed instructions
 * by default -- which is the point: most of the image is 16-bit, and no core
 * without RVC executes any of it.
 */

#define GPIO_OUT     (*(volatile unsigned int *)0x60004004)
#define GPIO_ENABLE  (*(volatile unsigned int *)0x60004020)

#define LED 8

/* The top of SRAM, minus a word so the first push stays inside it.
 * SOC_DRAM_HIGH is 0x3FCE0000 and the stack grows down. */
#define STACK_TOP 0x3FCDFFF0

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
