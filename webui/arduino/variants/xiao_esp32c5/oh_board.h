/* OpenHardware - the XIAO ESP32-C5 as the openhardware core sees it.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * Every address here restates a constant from `webui/boards/esp32c5.py`,
 * which is where the citation to ESP-IDF's own headers lives -- reg_base.h
 * for the GPIO base, gpio_reg.h for the offsets, soc.h for the RAM bounds.
 * `tests/webui/test_compile.py` parses this file and asserts each value
 * equals the description's, so the two spellings of one register cannot
 * drift; a change to the description that forgets this header fails a test
 * that names it.
 *
 * **Not the C3's header with the base changed, and not the C6's either.**
 * The C5 lays its GPIO register file out differently from both: the OUT
 * trio sits where a C3's and a C6's do, and ENABLE moves from +0x20 to
 * +0x34 -- so +0x24, which is ENABLE_W1TS on a C6, is something else here,
 * and a header copied from the C6 would drive the wrong register without
 * the model faulting it. `esp32c5.py`'s module docstring is where that
 * collision is recorded and `test_the_c5_register_file_is_not_the_c6_one`
 * is what pins it.
 *
 * No ADC and no I2C, because the description maps neither, and the core's
 * API surface equals the model. GPIO_IN was absent on the same terms until
 * OH-161's step 3.
 */

#ifndef OH_BOARD_XIAO_ESP32C5_H
#define OH_BOARD_XIAO_ESP32C5_H

#define OH_REG(address) (*(volatile uint32_t *)(address))

/* The chip's GPIO count, ESP-IDF's SOC_GPIO_PIN_COUNT from this variant's
 * `soc/soc_caps.h`, which cites where it was read. The core's `mask_of`
 * writes no bit for a pin at or past it, and a pin number known when the
 * sketch compiles that is at or past it does not compile (`Arduino.h`). */
#include "soc/soc_caps.h"
#define OH_GPIO_PIN_COUNT SOC_GPIO_PIN_COUNT

/* GPIO base 0x60091000 (reg_base.h:62); OUT at +0x04 with W1TS/W1TC at
 * +0x08/+0x0C; ENABLE at +0x34 with W1TS/W1TC at +0x38/+0x3C -- gpio_reg.h
 * as esp32c5.py quotes it, line numbers and all. */
#define OH_GPIO_OUT_W1TS     0x60091008u
#define OH_GPIO_OUT_W1TC     0x6009100Cu
#define OH_GPIO_ENABLE_W1TS  0x60091038u
#define OH_GPIO_ENABLE_W1TC  0x6009103Cu

/* GPIO_IN at +0x64 -- +0x3c, which is IN on a C3 and a C6, is
 * ENABLE_W1TC here -- and the IO_MUX pad registers pinMode sets: GPIO0's at
 * 0x60090000, at + 0x0 where a C3's and a C6's are at + 0x4, and each next
 * GPIO's four bytes on; FUN_PD bit 7, FUN_PU bit 8, FUN_IE bit 9.
 * `gpio_reg.h:235`, `reg_base.h:61`, `io_mux_reg.h:155`, `:46`, `:51` and
 * `:56`, via webui/boards/esp32c5.py. GPIO15 to GPIO22, the SPI flash pads,
 * have no register in the description, so a pinMode on one faults naming
 * where it would be. */
#define OH_GPIO_IN           0x60091064u
#define OH_IO_MUX_GPIO0      0x60090000u
#define OH_IO_MUX_STRIDE     0x4u
#define OH_IO_MUX_FUN_PD     0x00000080u   /* bit 7 */
#define OH_IO_MUX_FUN_PU     0x00000100u   /* bit 8 */
#define OH_IO_MUX_FUN_IE     0x00000200u   /* bit 9 */

/* UART0's transmit FIFO at 0x60000000, and the clock register whose bit 24
 * (+0x88 on this part) gates the transmitter. `register/soc/uart_reg.h:17` and `:1548`, via webui/boards/esp32c5.py.
 *
 * The FIFO is a STREAM in the description, not a register: every byte
 * written to it is kept, which is what makes a print arrive whole. */
#define OH_UART_FIFO         0x60000000u
#define OH_UART_CLK_CONF     0x60000088u
#define OH_UART_TX_SCLK_EN   0x01000000u   /* UART_TX_SCLK_EN, bit 24 */

/* SYSTIMER unit 0, base 0x6000A000 (reg_base.h:23): write UPDATE to
 * UNIT0_OP, wait for VALUE_VALID, then read VALUE_HI and VALUE_LO, which
 * hold the copy taken at the write. `register/soc/systimer_reg.h:121`,
 * `:370` and `:382`, via webui/boards/esp32c5.py, which cites each bit. The
 * unit counts out of reset. */
#define OH_SYSTIMER_UNIT0_OP           0x6000A004u
#define OH_SYSTIMER_UNIT0_UPDATE       0x40000000u   /* bit 30 */
#define OH_SYSTIMER_UNIT0_VALUE_VALID  0x20000000u   /* bit 29 */
#define OH_SYSTIMER_UNIT0_VALUE_HI     0x6000A040u
#define OH_SYSTIMER_UNIT0_VALUE_LO     0x6000A044u

/* Sixteen ticks a microsecond, the description's SYSTIMER_HZ -- and NOT
 * the 48 MHz crystal over `soc_caps.h`'s 2.5, which would say 19.2; the
 * description says why. A tick is fifteen emulator steps here, the
 * description's SYSTIMER_INSTRUCTIONS_PER_TICK, because this board's
 * Arduino build runs at 240 MHz. */
#define OH_SYSTIMER_TICKS_PER_US       16u

/* The top of HP SRAM (0x40860000, soc.h's SOC_DRAM_HIGH), minus a word so
 * the first push stays inside it -- the C3 header's arithmetic applied to
 * this part's own bound. One window here where the C3 has two: the C5's
 * IRAM and DRAM share a base and a top, so there is no second view to
 * choose between. */
#define OH_STACK_TOP         0x4085FFF0u

#endif
