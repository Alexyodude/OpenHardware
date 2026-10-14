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
 * What is NOT here is as deliberate as what is: the core's API surface
 * equals the model. GPIO_IN was absent on the same terms until OH-161's
 * step 3, the ADC until its step 4, and I2C until its step 5.
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

/* GPIO_IN at +0x3c, which reads the pins, and the IO_MUX pad registers
 * pinMode sets: GPIO0's at 0x60090004 and each next GPIO's four bytes on,
 * FUN_PD bit 7, FUN_PU bit 8, FUN_IE bit 9. `gpio_reg.h:197`,
 * `reg_base.h:47`, `io_mux_reg.h:175`, `:42`, `:47` and `:52`, via
 * webui/boards/esp32c6.py. */
#define OH_GPIO_IN           0x6009103Cu
#define OH_IO_MUX_GPIO0      0x60090004u
#define OH_IO_MUX_STRIDE     0x4u
#define OH_IO_MUX_FUN_PD     0x00000080u   /* bit 7 */
#define OH_IO_MUX_FUN_PU     0x00000100u   /* bit 8 */
#define OH_IO_MUX_FUN_IE     0x00000200u   /* bit 9 */

/* UART0's transmit FIFO at 0x60000000, and the clock register whose bit 24
 * (+0x88 on this part) gates the transmitter. `register/soc/uart_reg.h:17` and `:1477`, via webui/boards/esp32c6.py.
 *
 * The FIFO is a STREAM in the description, not a register: every byte
 * written to it is kept, which is what makes a print arrive whole. */
#define OH_UART_FIFO         0x60000000u
#define OH_UART_CLK_CONF     0x60000088u
#define OH_UART_TX_SCLK_EN   0x01000000u   /* UART_TX_SCLK_EN, bit 24 */

/* SYSTIMER unit 0, base 0x6000A000 (reg_base.h:23): write UPDATE to
 * UNIT0_OP, wait for VALUE_VALID, then read VALUE_HI and VALUE_LO, which
 * hold the copy taken at the write. `register/soc/systimer_reg.h:106`,
 * `:342` and `:354`, via webui/boards/esp32c6.py, which cites each bit: the
 * C3's offsets at another base. The unit counts out of reset. */
#define OH_SYSTIMER_UNIT0_OP           0x6000A004u
#define OH_SYSTIMER_UNIT0_UPDATE       0x40000000u   /* bit 30 */
#define OH_SYSTIMER_UNIT0_VALUE_VALID  0x20000000u   /* bit 29 */
#define OH_SYSTIMER_UNIT0_VALUE_HI     0x6000A040u
#define OH_SYSTIMER_UNIT0_VALUE_LO     0x6000A044u

/* Sixteen ticks a microsecond: the description's SYSTIMER_HZ, 40 MHz over
 * the fixed 2.5 as it cites them. A tick is ten emulator steps, the
 * description's SYSTIMER_INSTRUCTIONS_PER_TICK, which says what kind of
 * number that is. */
#define OH_SYSTIMER_TICKS_PER_US       16u

/* ADC1's one-time sample, base 0x6000E000 (OH-161 step 4): clear done
 * through INT_CLR, write ONETIME_SAMPLE with ADC1's bit, the channel and
 * the attenuation, write it again with START, wait for done in INT_RAW,
 * read SAR1's data. `reg_base.h:27`, `apb_saradc_reg.h:225`, `:352`, `:508`
 * and `:616`, via webui/boards/esp32c6.py, which cites each bit.
 *
 * The clock is in PCR (0x60096000), and on out of reset here: the function
 * clock SARADC_CLKM_EN, bit 22 of PCR + 0x84, is the gate, and the register
 * clock SARADC_REG_CLK_EN is bit 2 of PCR + 0x80. analogRead sets both, as
 * ESP-IDF does. A C5 keeps them at + 0x88 and + 0x8C, and off. The bits are
 * hex literals for the reason the UART gate's is, and the attenuation is
 * 12 dB, arduino-esp32's default. */
#define OH_ADC_BUS_CLOCK               0x60096080u
#define OH_ADC_BUS_CLOCK_EN            0x00000004u   /* SARADC_REG_CLK_EN, bit 2 */
#define OH_ADC_GATE                    0x60096084u
#define OH_ADC_GATE_EN                 0x00400000u   /* SARADC_CLKM_EN, bit 22 */
#define OH_ADC_ONETIME_SAMPLE          0x6000E020u
#define OH_ADC_SAR1_DATA               0x6000E02Cu
#define OH_ADC_INT_RAW                 0x6000E044u
#define OH_ADC_INT_CLR                 0x6000E04Cu
#define OH_ADC_ONETIME_SAR1            0x80000000u   /* bit 31 */
#define OH_ADC_ONETIME_START           0x20000000u   /* bit 29 */
#define OH_ADC_ONETIME_ATTEN_12DB      0x01800000u   /* 3 in [24:23] */
#define OH_ADC_ONETIME_CHANNEL_SHIFT   25u
#define OH_ADC1_DONE                   0x80000000u   /* bit 31 */

/* ADC1's channels are GPIO0 to GPIO6, in order (TRM Table 39.2-1). */
#define OH_ADC1_FIRST_GPIO             0u
#define OH_ADC1_CHANNELS               7u

/* I2C0, base 0x60004000 (OH-161 step 5): what `Wire` writes, from
 * `webui/boards/esp32c6.py`, which cites each line of `i2c_reg.h`,
 * `reg_base.h`, `pcr_reg.h`, `gpio_reg.h` and `i2c_ll.h`. A test holds every
 * line equal to the description's, and the bits the description does not
 * carry to the vendor's own headers. Hex literals, for the reason the UART
 * gate's is.
 *
 * **Neither the C3's header with the base changed nor the C5's**, and each
 * difference is a register `Wire` would write wrongly without the model
 * faulting it:
 *   - the base is the C5's, 0x60004000, and the gate is in PCR as on a C5:
 *     the register clock PCR_I2C_CONF (+ 0x20) CLK_EN, bit 0, and the
 *     function clock PCR_I2C_SCLK_CONF (+ 0x24) SCLK_EN, bit 22. **Both
 *     reset to 1 here and to 0 on a C5**: `Wire.begin` sets them as ESP-IDF
 *     does, and a sketch that never calls it is not stopped by the gate. The
 *     model checks the second and stores the first, as the ADC's two;
 *   - the matrix registers are the C3's shape: GPIO_FUNCn_IN_SEL_CFG at
 *     + 0x154 with SIG_IN_SEL bit 7 and a 6-bit IN_SEL; GPIO_FUNCn_OUT_SEL_CFG
 *     at + 0x554 with OEN_SEL at bit 9; GPIO_PINn at + 0x74, PAD_DRIVER bit 2;
 *   - the signals are I2CEXT0_SCL 45 and I2CEXT0_SDA 46
 *     (`gpio_sig_map.h:79-82`);
 *   - **open drain is FORCE_OUT clear** (`i2c_reg.h:32-42`, "0: open drain
 *     output"), and ESP-IDF sets it so (`i2c_ll_enable_pins_open_drain`,
 *     `i2c_ll.h:920-924`, called with true by `i2c_hal_master_init`), where
 *     the C3's is FORCE_OUT set. So CTR is written MS_MODE alone, and
 *     OH_I2C_CTR_INIT is the word `Wire.begin` stores.
 * The op codes are `i2c_ll.h`'s (:45-49), **not the register header's own
 * `I2C_COMMANDn` comment**, which is the original ESP32's encoding; a command
 * word is byte_num [7:0], ack_en [8], ack_exp [9], ack_val [10], op_code
 * [13:11]. */
#define OH_I2C_CTR                     0x60004004u
#define OH_I2C_FIFO_CONF               0x60004018u
#define OH_I2C_DATA                    0x6000401Cu
#define OH_I2C_INT_RAW                 0x60004020u
#define OH_I2C_INT_CLR                 0x60004024u
#define OH_I2C_COMD0                   0x60004058u
#define OH_I2C_CTR_MS_MODE             0x00000010u   /* bit 4 */
#define OH_I2C_CTR_TRANS_START         0x00000020u   /* bit 5, write-trigger */
#define OH_I2C_CTR_CONF_UPGATE         0x00000800u   /* bit 11, write-trigger */
#define OH_I2C_CTR_INIT                0x00000010u   /* MS_MODE; open drain is FORCE_OUT clear */
#define OH_I2C_FIFO_TX_RST             0x00002000u   /* FIFO_CONF bit 13 */
#define OH_I2C_FIFO_RX_RST             0x00001000u   /* FIFO_CONF bit 12 */
#define OH_I2C_INT_NACK                0x00000400u   /* bit 10 */
#define OH_I2C_INT_TRANS_COMPLETE      0x00000080u   /* bit 7 */
#define OH_I2C_OP_SHIFT                11u
#define OH_I2C_OP_RSTART               6u
#define OH_I2C_OP_WRITE                1u
#define OH_I2C_OP_READ                 3u
#define OH_I2C_OP_STOP                 2u
#define OH_I2C_ACK_EN                  0x00000100u   /* bit 8 */
#define OH_I2C_ACK_EXP                 0x00000200u   /* bit 9 */
#define OH_I2C_ACK_VAL                 0x00000400u   /* bit 10: 1 NACKs the byte read */
#define OH_I2C_BUS_CLOCK               0x60096020u
#define OH_I2C_BUS_CLOCK_EN            0x00000001u   /* PCR_I2C_CLK_EN, bit 0 */
#define OH_I2C_GATE                    0x60096024u
#define OH_I2C_GATE_EN                 0x00400000u   /* PCR_I2C_SCLK_EN, bit 22 */
#define OH_I2C_SCL_SIGNAL              45u
#define OH_I2C_SDA_SIGNAL              46u
#define OH_GPIO_FUNC_IN_SEL_CFG0       0x60091154u
#define OH_GPIO_FUNC_OUT_SEL_CFG0      0x60091554u
#define OH_GPIO_SIG_IN_SEL             0x00000080u   /* IN_SEL_CFG bit 7 */
#define OH_GPIO_OUT_SEL_OEN_SEL        0x00000200u   /* OUT_SEL_CFG bit 9: OEN_SEL, gpio_reg.h:5013 */
#define OH_GPIO_PIN0                   0x60091074u
#define OH_GPIO_PIN_STRIDE             0x4u
#define OH_GPIO_PIN_PAD_DRIVER         0x00000004u   /* GPIO_PINn bit 2 */
#define OH_IO_MUX_MCU_SEL_MASK         0x00007000u   /* [14:12] */
#define OH_IO_MUX_MCU_SEL_GPIO         0x00001000u   /* function 1 */

/* The top of HP SRAM (0x40880000, soc.h's SOC_DRAM_HIGH), minus a word so
 * the first push stays inside it -- the C3 header's arithmetic applied to
 * this part's own bound. One window here where the C3 has two: the C6's
 * IRAM and DRAM share a base and a top. */
#define OH_STACK_TOP         0x4087FFF0u

#endif
