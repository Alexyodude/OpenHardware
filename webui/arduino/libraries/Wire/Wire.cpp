/* OpenHardware - Wire against the modelled I2C0 controller.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * ## What this is a face on
 *
 * The C3's I2C0 in master mode, as `webui/boards/esp32c3.py` models it:
 * bytes go into the DATA FIFO, up to eight commands go into COMD0 to COMD7,
 * and setting TRANS_START in CTR runs the list. The board's description runs
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
 * buffer (`Wire.h` says how big), 2 for every NACK, 5 for a timeout.
 *
 * **2 for EVERY NACK, as arduino-esp32's own Wire does.** Arduino documents 2
 * as "received NACK on transmit of address" and 3 as "received NACK on
 * transmit of data", but `Wire.cpp:466-468` at arduino-esp32 3.20017.241212
 * maps its driver's one failure, `ESP_FAIL`, to 2 and has no 3 anywhere, so
 * a sketch that tests for 3 never sees it on the vendor's own core and does
 * not here. The model could tell the two apart -- it leaves a NACKed command
 * without DONE, so COMD1 reads DONE only when the address was acknowledged
 * -- and nothing in the vendor's software reads DONE, so nothing here does.
 *
 * 5 is a transaction that raised neither TRANS_COMPLETE nor NACK within
 * 50 ms of SYSTIMER, which on this model happens only when `begin` was not
 * called: the controller's function clock is closed and answers nothing.
 *
 * ## What `begin` does, and what it cannot
 *
 * It opens the controller's clock gate and routes both pads through the GPIO
 * matrix as `webui/boards/esp32c3.py`'s `i2c_pad` checks at every
 * TRANS_START: each pad on function 1 with its input on and a pull-up, the
 * signal out of the pad with its output enable from GPIO_ENABLE, and the
 * signal back in from the same pad. The pins are the vendor's `SDA` and `SCL`
 * from `pins_arduino.h`, GPIO6 and GPIO7, `D4` and `D5`. Each pad's
 * GPIO_PINn PAD_DRIVER is set, which makes it open-drain as I2C wants; the
 * model maps the register and stores the bit, and `i2c_pad` does not check it.
 *
 * CTR is written whole as `i2c_ll_master_init` writes it (`i2c_ll.h:909-918`
 * in the framework copy): MS_MODE, CLK_EN, SDA_FORCE_OUT and SCL_FORCE_OUT,
 * everything else 0. And before each TRANS_START CONF_UPGATE is set, as
 * `i2c_hal_update_config` does by way of `i2c_ll_update` (`i2c_ll.h:143-146`).
 * The model stores CONF_UPGATE as a write-trigger 0 and does nothing with it,
 * so no run can tell the write is there; it is here because the HAL does it.
 *
 * **One thing silicon wants that this does not write, because the model maps
 * no such register.** PERIP_RST_EN0 bit 7, the controller's reset, is 0 out of
 * reset -- released -- so writing it would only fault. The model checks the
 * routing and the clock gate and not that.
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
 * in [7:0]; OEN_SEL makes GPIO_ENABLE the pad's output enable; PAD_DRIVER
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
    reg_set(OH_I2C_GATE, OH_I2C_GATE_EN);
    route(SDA, OH_I2C_SDA_SIGNAL);
    route(SCL, OH_I2C_SCL_SIGNAL);
    OH_REG(OH_I2C_CTR) = OH_I2C_CTR_MS_MODE | OH_I2C_CTR_CLK_EN |
                         OH_I2C_CTR_SDA_FORCE_OUT | OH_I2C_CTR_SCL_FORCE_OUT;
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
        /* 2 for every NACK, and why: see this file's header. */
        return 2;
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
        /* Nothing is read and the deferred write stays deferred. */
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
