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
 * What is NOT here is as deliberate as what is: no I2C, because the
 * description maps none, and the core's API surface equals the model.
 * GPIO_IN was absent on the same terms until OH-161's step 3, and the ADC
 * until its step 4.
 */

#ifndef OH_BOARD_XIAO_ESP32C3_H
#define OH_BOARD_XIAO_ESP32C3_H

#define OH_REG(address) (*(volatile uint32_t *)(address))

/* The chip's GPIO count, ESP-IDF's SOC_GPIO_PIN_COUNT from this variant's
 * `soc/soc_caps.h`, which cites where it was read. The core's `mask_of`
 * writes no bit for a pin at or past it, and a pin number known when the
 * sketch compiles that is at or past it does not compile (`Arduino.h`). */
#include "soc/soc_caps.h"
#define OH_GPIO_PIN_COUNT SOC_GPIO_PIN_COUNT

/* GPIO base 0x60004000; OUT at +0x04 with W1TS/W1TC at +0x08/+0x0C;
 * ENABLE at +0x20 with W1TS/W1TC at +0x24/+0x28. */
#define OH_GPIO_OUT_W1TS     0x60004008u
#define OH_GPIO_OUT_W1TC     0x6000400Cu
#define OH_GPIO_ENABLE_W1TS  0x60004024u
#define OH_GPIO_ENABLE_W1TC  0x60004028u

/* GPIO_IN at +0x3C, which reads the pins, and the IO_MUX pad registers
 * pinMode sets: GPIO0's at 0x60009004 and each next GPIO's four bytes on,
 * FUN_PD bit 7, FUN_PU bit 8, FUN_IE bit 9. `gpio_reg.h:122`, `soc.h:49`,
 * `io_mux_reg.h:175`, `:51`, `:56` and `:61`, via webui/boards/esp32c3.py.
 * The bits are hex literals for the reason the UART gate's is. */
#define OH_GPIO_IN           0x6000403Cu
#define OH_IO_MUX_GPIO0      0x60009004u
#define OH_IO_MUX_STRIDE     0x4u
#define OH_IO_MUX_FUN_PD     0x00000080u   /* bit 7 */
#define OH_IO_MUX_FUN_PU     0x00000100u   /* bit 8 */
#define OH_IO_MUX_FUN_IE     0x00000200u   /* bit 9 */

/* UART0's transmit FIFO at 0x60000000, and the clock register whose bit 24
 * (+0x78 on this part) gates the transmitter. `uart_reg.h:22` and `:1160`, via webui/boards/esp32c3.py.
 *
 * The FIFO is a STREAM in the description, not a register: every byte
 * written to it is kept, which is what makes a print arrive whole. */
#define OH_UART_FIFO         0x60000000u
#define OH_UART_CLK_CONF     0x60000078u
#define OH_UART_TX_SCLK_EN   0x01000000u   /* UART_TX_SCLK_EN, bit 24 */

/* SYSTIMER unit 0, base 0x60023000: write UPDATE to UNIT0_OP, wait for
 * VALUE_VALID, then read VALUE_HI and VALUE_LO, which hold the copy taken
 * at the write. `systimer_reg.h:108`, `:344` and `:356`, via
 * webui/boards/esp32c3.py, which cites each bit. The unit counts out of
 * reset, so nothing here enables it. */
#define OH_SYSTIMER_UNIT0_OP           0x60023004u
#define OH_SYSTIMER_UNIT0_UPDATE       0x40000000u   /* bit 30 */
#define OH_SYSTIMER_UNIT0_VALUE_VALID  0x20000000u   /* bit 29 */
#define OH_SYSTIMER_UNIT0_VALUE_HI     0x60023040u
#define OH_SYSTIMER_UNIT0_VALUE_LO     0x60023044u

/* Sixteen ticks a microsecond: the description's SYSTIMER_HZ, which cites
 * `soc_caps.h:250`'s SOC_SYSTIMER_FIXED_TICKS_US. What a tick costs in
 * emulator steps is the description's SYSTIMER_INSTRUCTIONS_PER_TICK, ten,
 * and its comment says what kind of number that is. A power of two, which
 * is what lets micros() divide the 64-bit count with a shift in an image
 * linked without libgcc. */
#define OH_SYSTIMER_TICKS_PER_US       16u

/* ADC1's one-time sample, base 0x60040000 (OH-161 step 4): clear done
 * through INT_CLR, write ONETIME_SAMPLE with ADC1's bit, the channel and
 * the attenuation, write it again with START, wait for done in INT_RAW,
 * read SAR1's data. `soc.h:67`, `apb_saradc_reg.h:176`, `:278`, `:391` and
 * `:467`, via webui/boards/esp32c3.py, which cites each bit. The clock gate
 * is CTRL's SAR_CLK_GATED, 1 out of reset; analogRead sets it as ESP-IDF's
 * adc_ll_digi_clk_sel does. The bits are hex literals for the reason the
 * UART gate's is, and the attenuation is 12 dB, arduino-esp32's default. */
#define OH_ADC_GATE                    0x60040000u
#define OH_ADC_GATE_EN                 0x00000040u   /* SAR_CLK_GATED, bit 6 */
#define OH_ADC_ONETIME_SAMPLE          0x60040020u
#define OH_ADC_SAR1_DATA               0x6004002Cu
#define OH_ADC_INT_RAW                 0x60040044u
#define OH_ADC_INT_CLR                 0x6004004Cu
#define OH_ADC_ONETIME_SAR1            0x80000000u   /* bit 31 */
#define OH_ADC_ONETIME_START           0x20000000u   /* bit 29 */
#define OH_ADC_ONETIME_ATTEN_12DB      0x01800000u   /* 3 in [24:23] */
#define OH_ADC_ONETIME_CHANNEL_SHIFT   25u
#define OH_ADC1_DONE                   0x80000000u   /* bit 31 */

/* ADC1's channels are GPIO0 to GPIO4, in order (TRM Table 34.2-1). A pin
 * outside them is on no ADC1 channel: the XIAO's A3, GPIO5, is ADC2's,
 * which ESP-IDF refuses on this part. */
#define OH_ADC1_FIRST_GPIO             0u
#define OH_ADC1_CHANNELS               5u

/* The top of DRAM (0x3FCE0000), minus a word so the first push stays
 * inside it -- the same arithmetic the blink fixtures state. */
#define OH_STACK_TOP         0x3FCDFFF0u

#endif
