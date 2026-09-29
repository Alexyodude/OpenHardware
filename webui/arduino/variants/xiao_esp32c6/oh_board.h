/* OpenHardware - the XIAO ESP32-C6 as the openhardware core sees it.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * Every address here restates a constant from `webui/boards/esp32c6.py`,
 * which is where the citation to ESP-IDF's own headers lives -- reg_base.h
 * for the GPIO base, gpio_reg.h for the offsets, soc.h for the RAM bounds.
 * `tests/webui/test_compile.py` parses this file and asserts each value
 * equals the description's, so the two spellings of one register cannot
 * drift; a change to the description that forgets this header fails a test
 * that names it.
 *
 * **The C3's offsets at a different base, and that is a fact rather than a
 * shortcut**: a C6's GPIO register file keeps the C3's layout while the
 * peripheral bus was renumbered wholesale (0x60004000 -> 0x60091000). Its
 * neighbour the C5 shares the base and NOT the layout -- see that variant's
 * header -- which is why none of these three files is a copy of another.
 *
 * No GPIO_IN, for the reason every variant here gives: the description
 * leaves it unmapped on purpose, and the core's API surface equals the
 * model.
 */

#ifndef OH_BOARD_XIAO_ESP32C6_H
#define OH_BOARD_XIAO_ESP32C6_H

#define OH_REG(address) (*(volatile uint32_t *)(address))

/* The chip's GPIO count, ESP-IDF's SOC_GPIO_PIN_COUNT from this variant's
 * `soc/soc_caps.h`, which cites where it was read. The core's `mask_of`
 * writes no bit for a pin at or past it, and a pin number known when the
 * sketch compiles that is at or past it does not compile (`Arduino.h`). */
#include "soc/soc_caps.h"
#define OH_GPIO_PIN_COUNT SOC_GPIO_PIN_COUNT

/* GPIO base 0x60091000 (reg_base.h:48); OUT at +0x04 with W1TS/W1TC at
 * +0x08/+0x0C; ENABLE at +0x20 with W1TS/W1TC at +0x24/+0x28 -- gpio_reg.h
 * as esp32c6.py quotes it, line numbers and all. */
#define OH_GPIO_OUT_W1TS     0x60091008u
#define OH_GPIO_OUT_W1TC     0x6009100Cu
#define OH_GPIO_ENABLE_W1TS  0x60091024u
#define OH_GPIO_ENABLE_W1TC  0x60091028u

/* UART0's transmit FIFO at 0x60000000, and the clock register whose bit 24
 * (+0x88 on this part) gates the transmitter. `register/soc/uart_reg.h:17` and `:1477`, via webui/boards/esp32c6.py.
 *
 * The FIFO is a STREAM in the description, not a register: every byte
 * written to it is kept, which is what makes a print arrive whole. */
#define OH_UART_FIFO         0x60000000u
#define OH_UART_CLK_CONF     0x60000088u
#define OH_UART_TX_SCLK_EN   0x01000000u   /* UART_TX_SCLK_EN, bit 24 */

/* The top of HP SRAM (0x40880000, soc.h's SOC_DRAM_HIGH), minus a word so
 * the first push stays inside it -- the C3 header's arithmetic applied to
 * this part's own bound. One window here where the C3 has two: the C6's
 * IRAM and DRAM share a base and a top. */
#define OH_STACK_TOP         0x4087FFF0u

/* **A judgement, and it says so** -- the same kind of number BOARD_MASK is
 * in `tools/import_3d_model.py`. This model configures no PLL and counts
 * no cycles, so a millisecond here cannot be a measurement of anything.
 * The choice is the C3's 4,000 iterations; the measurement is this
 * part's own, because a copied constant is exactly what OH-156 said not
 * to do: built with this recipe's -march=rv32imac at -Os and watched on
 * the described C6, a HIGH/LOW/delay(1) sketch's rises came 24,043
 * steps apart (2026-09-04). The C3 re-measured the same day gives 24,043
 * too -- its header's 24,031 is dated 2026-08-31, so the twelve steps lie
 * between the dates and not between the parts -- and both are the same
 * order as the 16,000 a real timer-driven millisecond costs on the AVR
 * board at its cited 16 MHz. One page, three families, comparable
 * blinks. */
#define OH_DELAY_LOOPS_PER_MS 4000u

#endif
