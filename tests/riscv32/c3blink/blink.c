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
 * Addresses from the ESP32-C3 Technical Reference Manual chapter 5 (GPIO):
 *
 *     GPIO_OUT_REG     0x60004004
 *     GPIO_ENABLE_REG  0x60004020
 *
 * **The XIAO ESP32-C3 has no user LED.** So this watches a GPIO register
 * rather than a pin anything is wired to, which is what OH-48 measured and
 * recorded before the board description existed. GPIO8 is the pin Espressif's
 * own devkit puts its LED on, and is a real output on this part either way.
 *
 * Compiled with -march=rv32imc, so the compiler emits compressed instructions
 * by default -- which is the whole point: eleven of the sixteen instructions
 * below are 16-bit, and no core without RVC executes any of them.
 */

#define GPIO_OUT     (*(volatile unsigned int *)0x60004004)
#define GPIO_ENABLE  (*(volatile unsigned int *)0x60004020)

#define LED 8

int main(void) {
    GPIO_ENABLE |= (1u << LED);

    for (;;) {
        GPIO_OUT ^= (1u << LED);
        for (volatile unsigned int i = 0; i < 100; i++) {
        }
    }
}
