/* OpenHardware - the XIAO ESP32-C3 as the openhardware core sees it.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * Every address here restates a constant from `webui/boards/esp32c3.py`,
 * which is where the citation to ESP-IDF's own headers lives -- reg_base.h
 * for the GPIO base, gpio_reg.h for the offsets, soc.h for the RAM bounds.
 * `tests/webui/test_compile.py` parses this file and asserts each value
 * equals the description's, so the two spellings of one register cannot
 * drift; a change to the description that forgets this header fails a test
 * that names it.
 *
 * What is NOT here is as deliberate as what is: no GPIO_IN, because the
 * description leaves it unmapped on purpose (its comment says why), and the
 * core's API surface equals the model.
 */

#ifndef OH_BOARD_XIAO_ESP32C3_H
#define OH_BOARD_XIAO_ESP32C3_H

#define OH_REG(address) (*(volatile uint32_t *)(address))

/* GPIO base 0x60004000; OUT at +0x04 with W1TS/W1TC at +0x08/+0x0C;
 * ENABLE at +0x20 with W1TS/W1TC at +0x24/+0x28. */
#define OH_GPIO_OUT_W1TS     0x60004008u
#define OH_GPIO_OUT_W1TC     0x6000400Cu
#define OH_GPIO_ENABLE_W1TS  0x60004024u
#define OH_GPIO_ENABLE_W1TC  0x60004028u

/* The top of DRAM (0x3FCE0000), minus a word so the first push stays
 * inside it -- the same arithmetic the blink fixtures state. */
#define OH_STACK_TOP         0x3FCDFFF0u

/* **A judgement, and it says so** -- the same kind of number BOARD_MASK is
 * in `tools/compose_board_3d.py`. This model configures no PLL and counts
 * no cycles, so a millisecond here cannot be a measurement of anything.
 * The choice, then the measurement: 4,000 iterations of the volatile spin
 * loop (six instructions each at this toolchain's -Os) makes delay(1)
 * cost ~24,000 emulator steps -- measured 2026-08-31, transitions 24,031
 * steps apart for a HIGH/LOW/delay(1) sketch (re-measured 2026-09-04 by
 * OH-156 at 24,043, the figure the C5 and C6 give the same day) -- the
 * same order as the 16,000 a real timer-driven millisecond costs on the
 * AVR board at its cited 16 MHz. One page, three families, comparable
 * blinks. */
#define OH_DELAY_LOOPS_PER_MS 4000u

#endif
