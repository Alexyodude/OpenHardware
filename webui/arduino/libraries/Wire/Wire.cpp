/* OpenHardware - Wire against the modelled I2C0 controller.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * ## What this is a face on
 *
 * I2C0 in master mode, as the board's description models it
 * (`webui/boards/esp32c3.py` or `esp32c5.py`; the registers are the board's
 * `oh_board.h` macros, and a chip's differences are macros: no `#ifdef` on the
 * chip, one on whether the board has a register clock): bytes go into the DATA
 * FIFO, up to eight commands go into COMD0 to COMD7, and setting TRANS_START in
 * CTR runs the list. The board's description runs
 * it between two instructions, so by the time the next instruction polls
 * INT_RAW the transaction is over. `begin` and each method below do what
 * ESP-IDF's I2C HAL does for the same step (`i2c_ll.h`, `i2c_hal.c`), less
 * the interrupts, the ring buffers and the timing, which this model has none
 * of.
 *
 * ## The two call stacks, as command lists
 *
 *   endTransmission(stop):
 *     RSTART | WRITE 1 (address, W) | WRITE n (the bytes) | STOP
 *   requestFrom(address, n):
 *     RSTART | WRITE 1 (address, R) | READ n-1 (ACK) | READ 1 (NACK) | STOP
 *
 * and, after `endTransmission(false)`, the write is not sent at all until
 * `requestFrom`, which sends it ahead of the read as a repeated START:
 *
 *     RSTART | WRITE 1 (address, W) | WRITE n | RSTART | WRITE 1 (address, R)
 *     | READ n-1 | READ 1 | STOP
 *
 * That is eight commands, which is all the controller has -- COMD0 to COMD7 --
 * and why the longest deferred read is the one whose write and read both have
 * a data phase. The address byte of each WRITE 1 has `ack_en` set, so a part
 * that does not answer ends the transaction with NACK in INT_RAW.
 *
 * ## What `endTransmission` returns, and what it does not tell apart
 *
 * 0 for a transaction that completed, 1 for a write that overflowed the
 * buffer (`Wire.h` says how big), 2 for a NACK of a zero-length write, 4 for
 * a NACK of a write that carries data, 5 for a timeout.
 *
 * **The reference is arduino-esp32 @ 2787dab, on every chip.** Its
 * `libraries/Wire/src/Wire.cpp:445-476` maps ESP_OK to 0, ESP_FAIL and
 * ESP_ERR_NOT_FOUND to 2, ESP_ERR_TIMEOUT to 5 and **everything else to 4**,
 * and `cores/esp32/esp32-hal-i2c-ng.c:259-275` sends a zero-length `i2cWrite`
 * to `i2c_master_probe` (a NACK is ESP_ERR_NOT_FOUND, so 2) and any other to
 * `i2c_master_transmit` (a NACK is ESP_ERR_INVALID_STATE, IDF 5.5
 * `i2c_master.c`, so 4). So `beginTransmission(a); endTransmission()` of an
 * absent part is 2, and a write with data is 4 whether its address or one of
 * its bytes was NACKed. Arduino documents 3 for a NACKed data byte, and
 * the vendor's core has no 3, so a sketch that tests for 3 never sees it
 * there and does not here. **This changed from the older core 3.20017.241212
 * (arduino-esp32 2.0.17, IDF 4.4.7), which mapped every NACK to 2** and which
 * cannot build for a C5 or C6; slice 1 cited it. The model could tell address
 * from data apart -- it leaves a NACKed command without DONE, so COMD1 reads
 * DONE only when the address was acknowledged -- and nothing in the vendor's
 * software reads DONE, so nothing here does.
 *
 * 5 is a transaction that raised neither TRANS_COMPLETE nor NACK within
 * 50 ms of SYSTIMER, which on this model happens only when `begin` was not
 * called: the controller's function clock is closed and answers nothing.
 * **That 5 is this model's, not the vendor's.** 2787dab allocates its buffers
 * only in `begin` (`Wire.cpp:44`) and returns 4 from `endTransmission`'s
 * NULL-buffer guard (`:452-455`) without reaching the bus; its 5 is a probe
 * or bus lock that timed out. This one goes to the bus anyway, because it is
 * the only way a sketch shows what a closed gate does.
 *
 * ## What `begin` does, and what it cannot
 *
 * It opens the controller's clock gate -- and the register clock first,
 * where the board has one (`OH_I2C_BUS_CLOCK`, the C5's PCR; the model
 * stores it and checks only the function clock) -- and routes both pads
 * through the GPIO matrix as the description's `i2c_pad` checks at every
 * TRANS_START: each pad on function 1 with its input on and a pull-up, the
 * signal out of the pad with its output enable from GPIO_ENABLE, and the
 * signal back in from the same pad. The pins are the vendor's `SDA` and `SCL`
 * from `pins_arduino.h` -- GPIO6 and GPIO7 on a C3, GPIO23 and GPIO24 on a
 * C5, `D4` and `D5` on both. Each pad's GPIO_PINn PAD_DRIVER is set, which
 * makes it open-drain as I2C wants; the model maps the register and stores
 * the bit, and `i2c_pad` does not check it.
 *
 * CTR is written whole, `OH_I2C_CTR_INIT`, as the HAL writes it: on a C3
 * `i2c_ll_master_init` (`i2c_ll.h:909-918` in the framework copy) sets
 * MS_MODE, CLK_EN, SDA_FORCE_OUT and SCL_FORCE_OUT, and on a C5
 * `i2c_hal_master_init` (v5.5 `i2c_hal.c:39-50`) sets MS_MODE and clears the
 * FORCE_OUTs -- **the bits mean opposite things**: set is open drain on the
 * C3 and direct output on the C5; everything else is 0. And before each
 * TRANS_START CONF_UPGATE is set, as
 * `i2c_hal_update_config` does by way of `i2c_ll_update` (`i2c_ll.h:143-146`).
 * The model stores CONF_UPGATE as a write-trigger 0 and does nothing with it,
 * so no run can tell the write is there; it is here because the HAL does it.
 *
 * **One thing silicon wants that this does not write.** The controller's
 * reset is released out of reset on both parts, so nothing writes it: on a C3
 * it is PERIP_RST_EN0 bit 7, which the model maps no register for (writing it
 * would only fault), and on a C5 PCR_I2C_RST_EN, bit 1 of PCR_I2C_CONF
 * (`pcr_reg.h:272`, default 0), which `install_i2c` maps and nothing here
 * sets. The model checks the routing and the function clock and not that.
 *
 * ## Why `setClock` does nothing
 *
 * The timing registers (SCL_LOW_PERIOD and the rest) are unmapped, and a
 * transaction here takes no time: INT_RAW answers on the next instruction
 * whether the bus is 100 kHz or 400 kHz. Writing them would fault at a named
 * address, and answering a clock the model cannot honour would be a wrong
 * value rather than a missing feature, so the argument is accepted and
 * unused, as `OhSerial::begin`'s baud is.
 */

#include "Wire.h"

OhWire Wire;

namespace {

/* Wire's own timeout (arduino-esp32's default is 50 ms, `Wire.cpp:48`). */
constexpr unsigned long kTimeoutMs = 50;

/* SOC_I2C_FIFO_LEN, the controller's FIFO in either direction. */
constexpr unsigned kFifoBytes = 32;

void reg_set(uint32_t address, uint32_t bits) {
    OH_REG(address) = OH_REG(address) | bits;
}

void reg_clear(uint32_t address, uint32_t bits) {
    OH_REG(address) = OH_REG(address) & ~bits;
}

/* One pad of the bus, as `i2c_pad` reads it back. OUT_SEL carries the signal
 * in its low bits (8 on a C3, 9 on a C5); OEN_SEL (OE_SEL on a C5,
 * `gpio_reg.h:6175`) makes GPIO_ENABLE the pad's output enable; PAD_DRIVER
 * makes the pad open-drain. */
void route(uint8_t gpio, uint32_t signal) {
    const uint32_t pad = OH_IO_MUX_GPIO0 + OH_IO_MUX_STRIDE * gpio;
    reg_clear(pad, OH_IO_MUX_MCU_SEL_MASK | OH_IO_MUX_FUN_PD);
    reg_set(pad, OH_IO_MUX_MCU_SEL_GPIO | OH_IO_MUX_FUN_IE | OH_IO_MUX_FUN_PU);
    reg_set(OH_GPIO_PIN0 + OH_GPIO_PIN_STRIDE * gpio, OH_GPIO_PIN_PAD_DRIVER);
    OH_REG(OH_GPIO_ENABLE_W1TS) = 1u << gpio;
    OH_REG(OH_GPIO_FUNC_OUT_SEL_CFG0 + 4u * gpio) = signal | OH_GPIO_OUT_SEL_OEN_SEL;
    OH_REG(OH_GPIO_FUNC_IN_SEL_CFG0 + 4u * signal) = OH_GPIO_SIG_IN_SEL | gpio;
}

/* A transaction's first stores: the two interrupts this waits on cleared --
 * INT_RAW holds a NACK until something clears it, so without this a probe
 * after a NACKed one would read the old NACK -- and both FIFOs reset (set the
 * reset bits, then clear them). */
void prepare(void) {
    OH_REG(OH_I2C_INT_CLR) = OH_I2C_INT_NACK | OH_I2C_INT_TRANS_COMPLETE;
    reg_set(OH_I2C_FIFO_CONF, OH_I2C_FIFO_TX_RST | OH_I2C_FIFO_RX_RST);
    reg_clear(OH_I2C_FIFO_CONF, OH_I2C_FIFO_TX_RST | OH_I2C_FIFO_RX_RST);
}

/* The next command word, COMD`n`; the new count. Never past COMD7: the
 * longest list built below is the eight in this file's header. */
unsigned add(unsigned n, uint32_t op, uint32_t flags, uint32_t count) {
    OH_REG(OH_I2C_COMD0 + 4u * n) = (op << OH_I2C_OP_SHIFT) | flags | count;
    return n + 1u;
}

enum Outcome { kDone, kNack, kTimeout };

/* TRANS_START, then wait for the transaction to say how it ended. A NACK
 * raises TRANS_COMPLETE too (the STOP the controller sends after it), so
 * NACK is read first. */
Outcome go(void) {
    reg_set(OH_I2C_CTR, OH_I2C_CTR_CONF_UPGATE);
    reg_set(OH_I2C_CTR, OH_I2C_CTR_TRANS_START);
    const unsigned long began = millis();
    for (;;) {
        const uint32_t raw = OH_REG(OH_I2C_INT_RAW);
        if ((raw & OH_I2C_INT_NACK) != 0u) {
            return kNack;
        }
        if ((raw & OH_I2C_INT_TRANS_COMPLETE) != 0u) {
            return kDone;
        }
        if (millis() - began >= kTimeoutMs) {
            return kTimeout;
        }
    }
}

}  // namespace

void OhWire::begin(void) {
#ifdef OH_I2C_BUS_CLOCK
    reg_set(OH_I2C_BUS_CLOCK, OH_I2C_BUS_CLOCK_EN);
#endif
    reg_set(OH_I2C_GATE, OH_I2C_GATE_EN);
    route(SDA, OH_I2C_SDA_SIGNAL);
    route(SCL, OH_I2C_SCL_SIGNAL);
    OH_REG(OH_I2C_CTR) = OH_I2C_CTR_INIT;
    deferred_ = false;
    overflow_ = false;
}

void OhWire::setClock(uint32_t hz) {
    /* Accepted and unused; see this file's header for why that is a
     * statement about the model. */
    (void)hz;
}

void OhWire::beginTransmission(uint8_t address) {
    /* A write deferred by `endTransmission(false)` and never followed by
     * `requestFrom` is dropped, as arduino-esp32 drops it. */
    deferred_ = false;
    overflow_ = false;
    tx_address_ = address;
    tx_length_ = 0;
}

size_t OhWire::write(uint8_t value) {
    if (tx_length_ >= kBuffer) {
        /* Remembered for `endTransmission`, which answers 1 ("data too long",
         * Arduino's documented code) rather than send a write that is not the
         * one the sketch made. The vendor's buffer is 128 bytes and its
         * `write` drops silently; see `Wire.h`. */
        overflow_ = true;
        return 0;
    }
    tx_[tx_length_++] = value;
    return 1;
}

size_t OhWire::write(const uint8_t* data, size_t length) {
    for (size_t i = 0; i < length; ++i) {
        if (write(data[i]) == 0) {
            return i;
        }
    }
    return length;
}

uint8_t OhWire::endTransmission(bool stop) {
    if (overflow_) {
        overflow_ = false;
        deferred_ = false;
        return 1;
    }
    if (!stop) {
        /* The write goes out ahead of the next `requestFrom`, as a repeated
         * START. Nothing is on the bus yet, so there is nothing to NACK. */
        deferred_ = true;
        return 0;
    }
    deferred_ = false;
    prepare();
    OH_REG(OH_I2C_DATA) = static_cast<uint32_t>(tx_address_) << 1;
    for (unsigned i = 0; i < tx_length_; ++i) {
        OH_REG(OH_I2C_DATA) = tx_[i];
    }
    unsigned n = add(0, OH_I2C_OP_RSTART, 0, 0);
    n = add(n, OH_I2C_OP_WRITE, OH_I2C_ACK_EN, 1);
    if (tx_length_ != 0) {
        n = add(n, OH_I2C_OP_WRITE, OH_I2C_ACK_EN, tx_length_);
    }
    add(n, OH_I2C_OP_STOP, 0, 0);
    switch (go()) {
    case kDone:
        return 0;
    case kNack:
        /* 2 for a zero-length write (a probe), 4 for one with data; see this
         * file's header for the vendor core this follows. */
        return tx_length_ == 0 ? 2 : 4;
    default:
        return 5;
    }
}

uint8_t OhWire::requestFrom(uint8_t address, uint8_t quantity, bool stop) {
    /* `stop` is accepted and unused: arduino-esp32's `requestFrom` reads and
     * stops whatever it is given (`Wire.cpp:474-519` at 3.20017.241212), the
     * flag only deciding when its lock is released. The controller's other
     * way to end a list, END, is not modelled. */
    (void)stop;
    rx_length_ = 0;
    rx_index_ = 0;
    const bool repeated = deferred_;
    if (quantity == 0) {
        /* Nothing is read. A zero-byte request at the deferred write's own
         * address ends the repeated START, as the vendor's does
         * (`Wire.cpp:494` sets `nonStop = false` once the address matches,
         * whatever the size); at another address it does not
         * (`Wire.cpp:490-493`), and the write stays deferred. The vendor's
         * driver also sends the write ahead of its zero-byte read; here
         * nothing goes out, so the part keeps the pointer it had. */
        if (repeated && address == tx_address_) {
            deferred_ = false;
        }
        return 0;
    }
    if (quantity > kBuffer) {
        quantity = kBuffer;
    }
    if (repeated) {
        /* arduino-esp32 refuses a repeated START to another address, and
         * keeps `nonStop` set when it does (`Wire.cpp:490-493`): the write
         * stays deferred for the `requestFrom` that names its address. Two
         * address bytes and the data must also fit the 32-byte FIFO, which is
         * this controller's limit and not the vendor driver's. */
        if (address != tx_address_ || tx_length_ + 2u > kFifoBytes) {
            return 0;
        }
    }
    deferred_ = false;
    prepare();
    unsigned n = 0;
    if (repeated) {
        OH_REG(OH_I2C_DATA) = static_cast<uint32_t>(tx_address_) << 1;
        for (unsigned i = 0; i < tx_length_; ++i) {
            OH_REG(OH_I2C_DATA) = tx_[i];
        }
        n = add(n, OH_I2C_OP_RSTART, 0, 0);
        n = add(n, OH_I2C_OP_WRITE, OH_I2C_ACK_EN, 1);
        if (tx_length_ != 0) {
            n = add(n, OH_I2C_OP_WRITE, OH_I2C_ACK_EN, tx_length_);
        }
    }
    OH_REG(OH_I2C_DATA) = (static_cast<uint32_t>(address) << 1) | 1u;
    n = add(n, OH_I2C_OP_RSTART, 0, 0);
    n = add(n, OH_I2C_OP_WRITE, OH_I2C_ACK_EN, 1);
    if (quantity > 1) {
        n = add(n, OH_I2C_OP_READ, 0, quantity - 1u);
    }
    n = add(n, OH_I2C_OP_READ, OH_I2C_ACK_VAL, 1);
    add(n, OH_I2C_OP_STOP, 0, 0);
    if (go() != kDone) {
        return 0;
    }
    for (unsigned i = 0; i < quantity; ++i) {
        rx_[i] = static_cast<uint8_t>(OH_REG(OH_I2C_DATA) & 0xFFu);
    }
    rx_length_ = quantity;
    return rx_length_;
}

int OhWire::available(void) { return rx_length_ - rx_index_; }

int OhWire::read(void) {
    if (rx_index_ >= rx_length_) {
        return -1;
    }
    return rx_[rx_index_++];
}
