// OpenHardware — RV32 state and the memory a board gave it.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Memory only. Decode and execute are in exec.cc, so that the question "can
// this core reach this address" stays answerable without reading an
// instruction set.

#include "cpu.h"

#include <algorithm>

namespace riscv32 {

namespace {

/// Does the span [address, address + bytes) fit inside a region at `base` of
/// `size` bytes?
///
/// In 64-bit arithmetic throughout, because every part of this can wrap.
/// `address + bytes` wraps at the top of the address space, and a wrapped sum
/// compares as *smaller* than the base -- which turns a read off the end of
/// memory into a read that passes the range check. The C3 has a region ending
/// at 0x60000000 and firmware that walks off it, so this is reachable rather
/// than theoretical.
bool span_fits(uint32_t address, uint32_t bytes, uint32_t base, uint32_t size) {
    if (address < base) {
        return false;
    }
    const uint64_t offset = static_cast<uint64_t>(address) - base;
    return offset + bytes <= static_cast<uint64_t>(size);
}

}  // namespace

Cpu::Cpu() { reset(); }

void Cpu::reset() {
    x_.fill(0);
    pc_ = 0;
    jvt_ = 0;
    extensions_ = 0;
    regions_.clear();
    mmio_.clear();
    streams_.clear();
    snapshots_.clear();
    inputs_.clear();
    samplers_.clear();
    doorbells_.clear();
    fifos_.clear();
    rung_ = 0;
    fault_address_ = 0;
    fault_was_fetch_ = false;
    fault_reason_ = FaultReason::Unmapped;
}

const Cpu::Region* Cpu::region_for(uint32_t address, uint32_t bytes) const {
    for (const Region& region : regions_) {
        if (span_fits(address, bytes, region.base, region.size)) {
            return &region;
        }
    }
    return nullptr;
}

Cpu::Region* Cpu::region_for(uint32_t address, uint32_t bytes) {
    const Cpu* self = this;
    return const_cast<Region*>(self->region_for(address, bytes));
}

bool Cpu::in_range(uint32_t address, uint32_t bytes) const {
    return region_for(address, bytes) != nullptr;
}

bool Cpu::executable_at(uint32_t address) const {
    // Two bytes, not four. With C enabled a 16-bit instruction may legally sit
    // in the last halfword of a region, and asking for four would refuse it.
    // Without C the fetch itself asks for four and fails there instead, which
    // is the same refusal reported against the access that actually needed the
    // width.
    const Region* region = region_for(address, 2);
    return region != nullptr && region->executable;
}

bool Cpu::read_byte_checked(uint32_t address, uint8_t& out) const {
    // **The sub-word paths consult MMIO too, and this is not decoration.**
    // ESP32 peripheral registers are word-accessed by convention, but nothing
    // stops a compiler emitting `lbu` against one -- and a byte read that fell
    // through to the region lookup would fault at an address the board
    // describes perfectly well. `core/cortexm0` shipped without this and had
    // to have it added.
    if (is_mapped(address)) {
        // A FIFO's data is byte 0. A read above it would pop a byte and
        // answer zero, so it faults before popping, as the write side
        // refuses the mirror case.
        if ((address & 3u) != 0 && fifos_.count(address & ~3u) != 0) {
            note_fault(address, false, FaultReason::FifoSubword);
            return false;
        }
        uint32_t word = 0;
        if (!mmio_read(address, word)) {
            return false;
        }
        out = static_cast<uint8_t>(word >> ((address & 3u) * 8u));
        return true;
    }
    const Region* region = region_for(address, 1);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    out = region->bytes[address - region->base];
    return true;
}

bool Cpu::write_byte_checked(uint32_t address, uint8_t value) {
    if (is_mapped(address)) {
        const unsigned shift = (address & 3u) * 8u;
        return mmio_write(address, static_cast<uint32_t>(value) << shift,
                          0xFFu << shift);
    }
    Region* region = region_for(address, 1);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    region->bytes[address - region->base] = value;
    return true;
}

bool Cpu::read_halfword(uint32_t address, uint16_t& out) const {
    if (is_mapped(address)) {
        if ((address & 2u) != 0 && fifos_.count(address & ~3u) != 0) {
            note_fault(address, false, FaultReason::FifoSubword);
            return false;
        }
        uint32_t word = 0;
        if (!mmio_read(address, word)) {
            return false;
        }
        out = static_cast<uint16_t>(word >> ((address & 2u) * 8u));
        return true;
    }
    const Region* region = region_for(address, 2);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    const uint32_t offset = address - region->base;
    out = static_cast<uint16_t>(region->bytes[offset] |
                                (region->bytes[offset + 1] << 8));
    return true;
}

bool Cpu::write_halfword(uint32_t address, uint16_t value) {
    if (is_mapped(address)) {
        const unsigned shift = (address & 2u) * 8u;
        return mmio_write(address, static_cast<uint32_t>(value) << shift,
                          0xFFFFu << shift);
    }
    Region* region = region_for(address, 2);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    const uint32_t offset = address - region->base;
    region->bytes[offset] = static_cast<uint8_t>(value);
    region->bytes[offset + 1] = static_cast<uint8_t>(value >> 8);
    return true;
}

bool Cpu::read_word(uint32_t address, uint32_t& out) const {
    if (is_mapped(address)) {
        return mmio_read(address, out);
    }
    const Region* region = region_for(address, 4);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    const uint32_t offset = address - region->base;
    out = static_cast<uint32_t>(region->bytes[offset]) |
          (static_cast<uint32_t>(region->bytes[offset + 1]) << 8) |
          (static_cast<uint32_t>(region->bytes[offset + 2]) << 16) |
          (static_cast<uint32_t>(region->bytes[offset + 3]) << 24);
    return true;
}

bool Cpu::write_word(uint32_t address, uint32_t value) {
    if (is_mapped(address)) {
        return mmio_write(address, value, 0xFFFFFFFFu);
    }
    Region* region = region_for(address, 4);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    const uint32_t offset = address - region->base;
    region->bytes[offset] = static_cast<uint8_t>(value);
    region->bytes[offset + 1] = static_cast<uint8_t>(value >> 8);
    region->bytes[offset + 2] = static_cast<uint8_t>(value >> 16);
    region->bytes[offset + 3] = static_cast<uint8_t>(value >> 24);
    return true;
}

uint8_t Cpu::read_byte(uint32_t address) const {
    const Region* region = region_for(address, 1);
    return region == nullptr ? 0 : region->bytes[address - region->base];
}

void Cpu::write_byte(uint32_t address, uint8_t value) {
    Region* region = region_for(address, 1);
    if (region != nullptr) {
        region->bytes[address - region->base] = value;
    }
}

void Cpu::clear_memory() {
    // Back to each region's own fill byte, not to zero. A flash region reads
    // 0xFF when erased, and clearing it to zero would leave the core in a
    // state the part it models can never be in.
    for (Region& region : regions_) {
        std::fill(region.bytes.begin(), region.bytes.end(), region.fill);
    }
}

bool Cpu::add_region(uint32_t base, uint32_t size, bool executable,
                     uint8_t fill) {
    if (size == 0) {
        return false;
    }
    // The region must not wrap the address space, and must not overlap one
    // that already exists. Overlap is refused rather than merged: two boards
    // describing the same address differently is a bug in a board file, and
    // silently keeping one of them makes it a bug that only shows up as a
    // wrong value much later.
    if (static_cast<uint64_t>(base) + size > 0x100000000ull) {
        return false;
    }
    for (const Region& existing : regions_) {
        const uint64_t new_end = static_cast<uint64_t>(base) + size;
        const uint64_t old_end = static_cast<uint64_t>(existing.base) + existing.size;
        if (base < old_end && existing.base < new_end) {
            return false;
        }
    }
    Region region;
    region.base = base;
    region.size = size;
    region.executable = executable;
    region.fill = fill;
    region.bytes.assign(size, fill);
    regions_.push_back(std::move(region));
    return true;
}

void Cpu::clear_regions() {
    regions_.clear();
    // A machine with no board has no peripherals either. Leaving `mmio_`
    // behind would let a second board inherit the first one's registers, which
    // is the kind of state that makes one test pass only when another ran
    // first. A stream carries BYTES as well as a mapping, so leaving one
    // behind would also let a second board answer with what the first one
    // printed. A snapshot counter carries a COUNT, so leaving one behind
    // would start the next board's clock where the last board's stopped. An
    // input carries a DRIVE, so leaving one behind would hand the next board
    // levels nobody put on its pins. A sampler carries SAMPLES, so leaving
    // one behind would convert the next board's register to voltages nobody
    // put on its pins either. A doorbell carries a RING and a FIFO carries
    // BYTES, so leaving either behind would ring the next board's device, or
    // hand it a byte nobody sent.
    mmio_.clear();
    streams_.clear();
    snapshots_.clear();
    inputs_.clear();
    samplers_.clear();
    doorbells_.clear();
    fifos_.clear();
    rung_ = 0;
}

void Cpu::clear_mmio() {
    mmio_.clear();
    streams_.clear();
    snapshots_.clear();
    inputs_.clear();
    samplers_.clear();
    doorbells_.clear();
    fifos_.clear();
    rung_ = 0;
}

void Cpu::forget_input(uint32_t at) {
    inputs_.erase(
        std::remove_if(inputs_.begin(), inputs_.end(),
                       [&](const Input& input) { return input.address == at; }),
        inputs_.end());
}

void Cpu::forget_sampler(uint32_t at) {
    samplers_.erase(
        std::remove_if(samplers_.begin(), samplers_.end(),
                       [&](const Sampler& sampler) { return sampler.control == at; }),
        samplers_.end());
}

void Cpu::forget_doorbell(uint32_t at) {
    doorbells_.erase(
        std::remove_if(doorbells_.begin(), doorbells_.end(),
                       [&](const Doorbell& bell) { return bell.address == at; }),
        doorbells_.end());
}

void Cpu::forget_fifo(uint32_t at) { fifos_.erase(at); }

bool Cpu::is_snapshot_register(uint32_t at) const {
    for (const Snapshot& counter : snapshots_) {
        if (counter.op == at || counter.low == at || counter.high == at) {
            return true;
        }
    }
    return false;
}

void Cpu::map_register(uint32_t address, uint32_t value) {
    const uint32_t at = address & ~3u;
    forget_input(at);
    forget_sampler(at);
    forget_doorbell(at);
    forget_fifo(at);
    Mapped entry;
    entry.value = value;
    entry.target = at;
    mmio_[at] = entry;
}

void Cpu::map_alias(uint32_t address, uint32_t target, WriteOp op,
                    bool readable) {
    const uint32_t at = address & ~3u;
    forget_input(at);
    forget_sampler(at);
    forget_doorbell(at);
    forget_fifo(at);
    Mapped entry;
    entry.target = target & ~3u;
    entry.op = op;
    entry.readable = readable;
    mmio_[at] = entry;
}

void Cpu::map_stream(uint32_t address, uint32_t enable_address,
                     uint32_t enable_mask) {
    const uint32_t at = address & ~3u;
    forget_input(at);
    forget_sampler(at);
    forget_doorbell(at);
    forget_fifo(at);
    // Registered in `mmio_` as well, so `is_mapped` sees it and a READ answers
    // this entry's value, which stays zero. The stream table alone would make
    // the address respond to writes and fault on reads -- and a UART data
    // register that faults on read is a board that cannot be probed.
    Mapped entry;
    entry.target = at;
    mmio_[at] = entry;

    Stream stream;
    stream.enable = enable_address & ~3u;
    stream.enable_mask = enable_mask;
    streams_[at] = stream;
}

void Cpu::map_snapshot_counter(uint32_t op_address, uint32_t update_mask,
                               uint32_t valid_mask, uint32_t low_address,
                               uint32_t high_address, uint32_t high_mask,
                               uint32_t enable_address, uint32_t enable_mask,
                               uint32_t instructions_per_tick) {
    Snapshot counter;
    counter.op = op_address & ~3u;
    counter.update_mask = update_mask;
    counter.valid_mask = valid_mask;
    counter.low = low_address & ~3u;
    counter.high = high_address & ~3u;
    counter.high_mask = high_mask;
    counter.enable = enable_address & ~3u;
    counter.enable_mask = enable_mask;
    // Zero would divide by zero at the first snapshot. A board asking for a
    // counter that never advances has asked for the hang this exists to
    // prevent, so it is corrected to the fastest legal rate -- the answer
    // `core/cortexm0`'s `map_counter` gives -- and `abi.py` refuses it first.
    counter.instructions_per_tick =
        instructions_per_tick == 0 ? 1u : instructions_per_tick;

    // Registered in `mmio_` too, so `is_mapped` sees all three and their
    // accesses reach `mmio_read`/`mmio_write`, which consult `snapshots_`
    // before the stored word -- so the word these entries hold is never read.
    for (const uint32_t at : {counter.op, counter.low, counter.high}) {
        forget_input(at);
        forget_sampler(at);
        forget_doorbell(at);
        forget_fifo(at);
        Mapped entry;
        entry.target = at;
        mmio_[at] = entry;
    }
    // Mapping the same unit twice replaces it, rather than leaving two
    // counters answering one address in whichever order the scan meets them.
    snapshots_.erase(
        std::remove_if(snapshots_.begin(), snapshots_.end(),
                       [&](const Snapshot& existing) {
                           return existing.op == counter.op;
                       }),
        snapshots_.end());
    snapshots_.push_back(counter);
}

void Cpu::map_input(uint32_t address, uint32_t out_address,
                    uint32_t enable_address, uint32_t pad_base,
                    uint32_t pad_stride, uint32_t pads,
                    uint32_t input_enable_mask, uint32_t pull_up_mask,
                    uint32_t pull_down_mask) {
    Input input;
    input.address = address & ~3u;
    input.out = out_address & ~3u;
    input.enable = enable_address & ~3u;
    input.pad_base = pad_base;
    input.pad_stride = pad_stride;
    input.pads = pads;
    input.input_enable_mask = input_enable_mask;
    input.pull_up_mask = pull_up_mask;
    input.pull_down_mask = pull_down_mask;

    // Registered in `mmio_` too, so `is_mapped` sees it and its accesses
    // reach `mmio_read`/`mmio_write`, which consult `inputs_` first -- so a
    // write lands in a word nobody reads, as a read-only register's does.
    forget_sampler(input.address);
    forget_doorbell(input.address);
    forget_fifo(input.address);
    Mapped entry;
    entry.target = input.address;
    mmio_[input.address] = entry;

    // Mapping the same register twice replaces it, drive and all, rather
    // than leaving two answering one address in whichever order the scan
    // meets them.
    inputs_.erase(
        std::remove_if(inputs_.begin(), inputs_.end(),
                       [&](const Input& existing) {
                           return existing.address == input.address;
                       }),
        inputs_.end());
    inputs_.push_back(input);
}

bool Cpu::drive_input(uint32_t address, uint32_t driven, uint32_t levels) {
    for (Input& input : inputs_) {
        if (input.address == (address & ~3u)) {
            input.driven = driven;
            input.levels = levels;
            return true;
        }
    }
    return false;
}

void Cpu::map_sampler(uint32_t control_address, uint32_t value,
                      uint32_t start_mask, uint32_t key_mask,
                      uint32_t result_address, uint32_t status_address,
                      uint32_t done_mask, uint32_t enable_address,
                      uint32_t enable_mask) {
    Sampler sampler;
    sampler.control = control_address & ~3u;
    sampler.start_mask = start_mask;
    sampler.key_mask = key_mask;
    sampler.result = result_address & ~3u;
    sampler.status = status_address & ~3u;
    sampler.done_mask = done_mask;
    sampler.enable = enable_address & ~3u;
    sampler.enable_mask = enable_mask;

    // The control register is a plain register in `mmio_`, so a read answers
    // the stored word; `mmio_write` asks `samplers_` before storing.
    forget_input(sampler.control);
    forget_doorbell(sampler.control);
    forget_fifo(sampler.control);
    Mapped entry;
    entry.value = value;
    entry.target = sampler.control;
    mmio_[sampler.control] = entry;

    // Mapping the same register twice replaces it, and what it held, rather
    // than leaving two converting on one address.
    forget_sampler(sampler.control);
    samplers_.push_back(sampler);
}

bool Cpu::hold_samples(uint32_t control_address, const uint32_t* keys,
                       const uint32_t* words, uint32_t count) {
    for (Sampler& sampler : samplers_) {
        if (sampler.control != (control_address & ~3u)) {
            continue;
        }
        sampler.held.clear();
        for (uint32_t i = 0; i < count; ++i) {
            sampler.held[keys[i]] = words[i];
        }
        return true;
    }
    return false;
}

bool Cpu::map_doorbell(uint32_t address, uint32_t value, uint32_t ring_mask,
                       uint32_t write_trigger) {
    const uint32_t at = address & ~3u;
    if (is_snapshot_register(at)) {
        return false;
    }
    forget_input(at);
    forget_sampler(at);
    forget_doorbell(at);
    forget_fifo(at);
    // A stream at the address would answer a write before the doorbell is
    // asked, and it would never ring.
    streams_.erase(at);
    // A plain register in `mmio_`, so a read answers the stored word;
    // `mmio_write` asks `doorbells_` before storing. The reset value is held
    // to the same rule as a write: a trigger bit does not store.
    Mapped entry;
    entry.value = value & ~write_trigger;
    entry.target = at;
    mmio_[at] = entry;

    Doorbell bell;
    bell.address = at;
    bell.ring_mask = ring_mask;
    bell.write_trigger = write_trigger;
    doorbells_.push_back(bell);
    return true;
}

uint32_t Cpu::take_rung() {
    const uint32_t rung = rung_;
    rung_ = 0;
    return rung;
}

bool Cpu::map_fifo(uint32_t address, uint32_t enable_address,
                   uint32_t enable_mask) {
    const uint32_t at = address & ~3u;
    if (is_snapshot_register(at)) {
        return false;
    }
    forget_input(at);
    forget_sampler(at);
    forget_doorbell(at);
    // A FIFO answers writes as a stream does, so it must not leave one
    // behind to capture them first.
    streams_.erase(at);
    // Registered in `mmio_` too, so `is_mapped` sees it. Its reads and
    // writes reach `mmio_read` and `mmio_write`, which ask `fifos_` first.
    Mapped entry;
    entry.target = at;
    mmio_[at] = entry;

    Fifo fifo;
    fifo.enable = enable_address & ~3u;
    fifo.enable_mask = enable_mask;
    fifos_[at] = fifo;
    return true;
}

const std::vector<uint8_t>& Cpu::written(uint32_t address) const {
    static const std::vector<uint8_t> none;
    const auto found = fifos_.find(address & ~3u);
    return found == fifos_.end() ? none : found->second.written;
}

std::vector<uint8_t> Cpu::take_written(uint32_t address) {
    std::vector<uint8_t> taken;
    const auto found = fifos_.find(address & ~3u);
    if (found != fifos_.end()) {
        taken.swap(found->second.written);
    }
    return taken;
}

bool Cpu::is_doorbell(uint32_t address) const {
    for (const Doorbell& bell : doorbells_) {
        if (bell.address == (address & ~3u)) {
            return true;
        }
    }
    return false;
}

bool Cpu::is_fifo(uint32_t address) const {
    return fifos_.count(address & ~3u) != 0;
}

bool Cpu::peek_word(uint32_t address, uint32_t& out, FaultReason& why) const {
    // A viewer's read must leave the fault record as the last instruction
    // left it, so the reason a failure had is handed back and the record put
    // back.
    const uint32_t fault_address = fault_address_;
    const bool fault_was_fetch = fault_was_fetch_;
    const FaultReason fault_reason = fault_reason_;
    const bool read = is_mapped(address) ? mmio_read(address, out, false)
                                         : read_word(address, out);
    why = read ? FaultReason::Unmapped : fault_reason_;
    fault_address_ = fault_address;
    fault_was_fetch_ = fault_was_fetch;
    fault_reason_ = fault_reason;
    return read;
}

bool Cpu::hold_readable(uint32_t address, const uint8_t* bytes, uint32_t count) {
    const auto found = fifos_.find(address & ~3u);
    if (found == fifos_.end()) {
        return false;
    }
    found->second.held.assign(bytes, bytes + count);
    return true;
}

bool Cpu::sampler_write(Sampler& sampler, Mapped& control, uint32_t address,
                        uint32_t value, uint32_t byte_mask) {
    // `value` arrives positioned in its lane by the sub-word paths, so the
    // stored word after this access is the whole word the key is read from,
    // whichever bytes the store carried.
    const uint32_t before = control.value;
    const uint32_t after = (before & ~byte_mask) | (value & byte_mask);
    const bool rises = (after & sampler.start_mask) != 0 &&
                       (before & sampler.start_mask) == 0;
    if (!rises) {
        control.value = after;
        return true;
    }
    uint32_t gate = 0;
    if (!mmio_read(sampler.enable, gate)) {
        // A clock register the board never mapped: a converter that could
        // never have converted. Named at the control register, the address
        // the instruction used, as a stream names its FIFO and not its gate.
        note_fault(address, false);
        return false;
    }
    if ((gate & sampler.enable_mask) == 0) {
        // Clock off: the word stores and nothing converts, as on silicon.
        control.value = after;
        return true;
    }
    // Each through its own target, as `mmio_write` stores, so a result or
    // status the board mapped as a readable alias lands where it is read.
    const auto storage = [&](uint32_t at) {
        const auto found = mmio_.find(at);
        return found == mmio_.end() ? mmio_.end() : mmio_.find(found->second.target);
    };
    const auto held = sampler.held.find(after & sampler.key_mask);
    const auto result = storage(sampler.result);
    const auto status = storage(sampler.status);
    if (held == sampler.held.end() || result == mmio_.end() ||
        status == mmio_.end()) {
        // Nothing held for the channel this write names, or nowhere to put
        // the answer. A 0 in the result would read as a voltage.
        note_fault(address, false);
        return false;
    }
    control.value = after;
    result->second.value = held->second;
    status->second.value |= sampler.done_mask;
    return true;
}

bool Cpu::input_levels(const Input& input, uint32_t address,
                       uint32_t& out) const {
    uint32_t out_word = 0;
    uint32_t enable_word = 0;
    if (!mmio_read(input.out, out_word) || !mmio_read(input.enable, enable_word)) {
        note_fault(address, false);
        return false;
    }
    uint32_t value = 0;
    for (uint32_t pin = 0; pin < 32; ++pin) {
        const uint32_t bit = 1u << pin;
        if ((input.pads & bit) == 0) {
            continue;
        }
        uint32_t pad = 0;
        if (!mmio_read(input.pad_base + pin * input.pad_stride, pad)) {
            // The pad register the board named cannot be read. Named at the
            // input register, the address the instruction used, as a stream
            // names its FIFO and not its gate: `mmio_read` may have recorded
            // the pad's own address on the way, and this replaces it.
            note_fault(address, false);
            return false;
        }
        if ((pad & input.input_enable_mask) == 0) {
            continue;
        }
        if ((enable_word & bit) != 0) {
            value |= out_word & bit;
            continue;
        }
        if ((input.driven & bit) != 0) {
            value |= input.levels & bit;
            continue;
        }
        // A pull-up alone reads high. A pull-down, both pulls, or neither
        // reads 0 -- the last a floating pin, whose 0 the board states.
        const bool up = (pad & input.pull_up_mask) != 0;
        const bool down = (pad & input.pull_down_mask) != 0;
        if (up && !down) {
            value |= bit;
        }
    }
    out = value;
    return true;
}

void Cpu::note_executed() {
    for (Snapshot& counter : snapshots_) {
        // An unmapped gate counts nothing here, and is NOT silently a timer
        // that never moves: the first snapshot asked for through it faults,
        // naming the unit. This runs between instructions, where there is
        // no access to fault.
        //
        // **And so it must not leave a fault behind either.** `mmio_read`
        // records one when a readable alias's target is unmapped, which is
        // right for an access and wrong here: it would rewrite the fault
        // record after every retired instruction, naming an address no
        // instruction touched. The record is put back as it was; the
        // snapshot is where the broken gate is reported.
        const uint32_t fault_address = fault_address_;
        const bool fault_was_fetch = fault_was_fetch_;
        const FaultReason fault_reason = fault_reason_;
        uint32_t gate = 0;
        if (!mmio_read(counter.enable, gate)) {
            fault_address_ = fault_address;
            fault_was_fetch_ = fault_was_fetch;
            fault_reason_ = fault_reason;
            continue;
        }
        if ((gate & counter.enable_mask) != 0) {
            ++counter.instructions;
        }
    }
}

const std::vector<uint8_t>& Cpu::stream(uint32_t address) const {
    static const std::vector<uint8_t> none;
    const auto found = streams_.find(address & ~3u);
    return found == streams_.end() ? none : found->second.bytes;
}

bool Cpu::is_mapped(uint32_t address) const {
    return mmio_.find(address & ~3u) != mmio_.end();
}

bool Cpu::mmio_read(uint32_t address, uint32_t& out, bool pop) const {
    const auto found = mmio_.find(address & ~3u);
    if (found == mmio_.end()) {
        return false;
    }
    const uint32_t at = address & ~3u;
    // A FIFO's read pops what was held, and faults when nothing was: nothing
    // has changed by then, so the fault names the read that found it empty.
    const auto fifo = fifos_.find(at);
    if (fifo != fifos_.end()) {
        std::deque<uint8_t>& held = fifo->second.held;
        if (held.empty()) {
            note_fault(address, false, FaultReason::EmptyFifo);
            return false;
        }
        out = held.front();
        if (pop) {
            held.pop_front();
        }
        return true;
    }
    // A snapshot counter's three registers answer its state rather than a
    // stored word, so they are checked before the stored-value path below.
    for (const Snapshot& counter : snapshots_) {
        if (at == counter.op) {
            // UPDATE is a write trigger and reads zero; only VALID is held.
            out = counter.valid ? counter.valid_mask : 0u;
            return true;
        }
        if (at == counter.low) {
            out = static_cast<uint32_t>(counter.latched);
            return true;
        }
        if (at == counter.high) {
            out = static_cast<uint32_t>(counter.latched >> 32) & counter.high_mask;
            return true;
        }
    }
    // An input register answers the pins rather than a stored word.
    for (const Input& input : inputs_) {
        if (at == input.address) {
            return input_levels(input, address, out);
        }
    }

    const Mapped& entry = found->second;
    if (!entry.readable) {
        // The architecture's answer and not an absence: a W1TS register reads
        // as zero on the part. See `map_alias`.
        out = 0;
        return true;
    }
    if (entry.target == (address & ~3u)) {
        out = entry.value;
        return true;
    }
    // An alias reaches the stored word and nothing the target does, so an
    // alias onto a FIFO or a doorbell -- mapped before either was -- would
    // answer a zero that is neither's. It faults instead.
    if (fifos_.count(entry.target) != 0 || is_doorbell(entry.target)) {
        note_fault(address, false, FaultReason::AliasOntoBehaviour);
        return false;
    }
    // A readable alias is a second view of its target, so it answers what the
    // target holds. One hop only -- an alias of an alias would need a loop,
    // and a loop needs a cycle check that nothing has asked for.
    const auto origin = mmio_.find(entry.target);
    if (origin == mmio_.end()) {
        // An alias whose target was never mapped is a mistake in the board
        // description. Faulting says so; answering zero would be the silent
        // hang this whole design refuses.
        note_fault(address, false);
        return false;
    }
    out = origin->second.value;
    return true;
}

bool Cpu::mmio_write(uint32_t address, uint32_t value, uint32_t byte_mask) {
    const uint32_t at = address & ~3u;
    const auto found = mmio_.find(at);
    if (found == mmio_.end()) {
        return false;
    }
    // **A FIFO is a stream with a read side**, and is asked first so a stream
    // left at the same address could never capture its write.
    const auto fifo = fifos_.find(at);
    if (fifo != fifos_.end()) {
        uint32_t gate_bits = 0;
        if (!mmio_read(fifo->second.enable, gate_bits)) {
            // An unmapped gate, named at the FIFO the instruction used, as a
            // stream's is: `mmio_read` does not note a miss of its own.
            note_fault(address, false, FaultReason::FifoGateUnmapped);
            return false;
        }
        // The low byte only, and only when the access carries byte 0; see
        // `map_stream` for why.
        if ((byte_mask & 0xFFu) != 0 &&
            (gate_bits & fifo->second.enable_mask) != 0) {
            fifo->second.written.push_back(static_cast<uint8_t>(value));
        }
        return true;
    }

    // **Before the word behaviours, because a stream is not one**: its write
    // appends rather than stores, and falling through would latch the byte
    // into a register nobody reads.
    const auto stream = streams_.find(at);
    if (stream != streams_.end()) {
        uint32_t gate_bits = 0;
        if (!mmio_read(stream->second.enable, gate_bits)) {
            // The gate register was never mapped: a board description
            // mistake, and faulting says so. Capturing regardless would
            // print bytes a real part would have discarded.
            //
            // **`note_fault` explicitly, and it was dropped once.** The
            // first version of this branch said `mmio_read` had already
            // recorded the address; it has not, and cannot -- its
            // `mmio_.find` miss returns false WITHOUT noting, because every
            // other caller falls through to the region lookup after it. So
            // the fault kept its reset value and an executed store reported
            // `access at 0x00000000` instead of naming the FIFO, which is a
            // wrong address rather than a missing one. Found by review;
            // `test_an_executed_store_through_an_unmapped_gate_names_the_fifo`
            // is what holds it, and it has to go through `step()` because
            // `write_word` formats the address the caller passed rather than
            // the one the core recorded.
            //
            // **Through `mmio_read` rather than off `Mapped::value`**, which
            // is what this did until the OH-161 review: reading the stored
            // word directly ignores `Mapped::target`, so a gate mapped as a
            // readable ALIAS answered its own zero forever and the stream
            // went silent while `read_word` on the same address gave the bit
            // correctly. No board here aliases a clock register, so nothing
            // was wrong on the three described parts -- and the next board
            // that does would have found a peripheral that reads right and
            // transmits nothing.
            note_fault(address, false);
            return false;
        }
        // **The access must actually carry byte 0.** A FIFO's data field is
        // `[7:0]` on all three parts described here, so a byte store to
        // FIFO+1 lands in a reserved lane and transmits nothing; taking the
        // low byte of that access regardless would append a zero the part
        // never sent. `byte_mask` is the one thing that can tell them apart,
        // because `at` has already been rounded to the word.
        const bool carries_data = (byte_mask & 0xFFu) != 0;
        if (carries_data && (gate_bits & stream->second.enable_mask) != 0) {
            // The low byte only, whatever the width of the access. See
            // `map_stream`.
            stream->second.bytes.push_back(static_cast<uint8_t>(value));
        }
        return true;
    }

    // **Before the word behaviours too**: a write to a snapshot counter's
    // operation register takes a copy or does nothing, and falling through
    // would store it in a word nobody reads. A write to one of its value
    // registers does fall through, into a word `mmio_read` never answers
    // from -- which is how a read-only register ignores it.
    for (Snapshot& counter : snapshots_) {
        if (at != counter.op) {
            continue;
        }
        // `value` arrives positioned in its lane by the sub-word paths, so a
        // byte store to the register's top byte carries the bit and one to
        // its bottom byte cannot.
        if ((value & counter.update_mask) == 0) {
            return true;
        }
        uint32_t gate = 0;
        if (!mmio_read(counter.enable, gate)) {
            // The board named an enable register it never mapped: a counter
            // that could never have counted. Faulting here names the unit
            // where the reader is looking, which a zero copy would not.
            //
            // **Through `mmio_read`, the read `note_executed` counts by**,
            // and not `is_mapped`, which is what this was until the OH-161
            // review: a gate mapped as a readable alias onto nothing IS
            // mapped, so the old check let the copy through while counting
            // read the gate, failed, and never counted -- a timer reading
            // zero forever with no fault anywhere. The two must ask the same
            // question or they answer it differently.
            note_fault(address, false);
            return false;
        }
        counter.latched = counter.instructions / counter.instructions_per_tick;
        counter.valid = true;
        return true;
    }

    // **Before the word behaviours too**: a write to a doorbell stores with
    // its trigger bits cleared, and rings when it carries a ring bit. The
    // ring is noted after the store, so the store has retired by the time
    // anything hears of it.
    for (const Doorbell& bell : doorbells_) {
        if (at == bell.address) {
            uint32_t& stored = found->second.value;
            stored = ((stored & ~byte_mask) | (value & byte_mask)) &
                     ~bell.write_trigger;
            if ((value & byte_mask & bell.ring_mask) != 0) {
                rung_ = at;
            }
            return true;
        }
    }

    // **Before the word behaviours too**: a write to a sampler's control
    // register may convert, which a plain store would not.
    for (Sampler& sampler : samplers_) {
        if (at == sampler.control) {
            return sampler_write(sampler, found->second, address, value,
                                 byte_mask);
        }
    }

    const Mapped& entry = found->second;
    if (entry.target != at &&
        (fifos_.count(entry.target) != 0 || is_doorbell(entry.target))) {
        // As for the read: an alias would store a trigger bit, or a byte no
        // FIFO took.
        note_fault(address, false, FaultReason::AliasOntoBehaviour);
        return false;
    }
    const auto target = mmio_.find(entry.target);
    if (target == mmio_.end()) {
        note_fault(address, false);
        return false;
    }

    uint32_t& stored = target->second.value;
    switch (entry.op) {
    case WriteOp::Store:
        // The byte mask applies to a store and to nothing else. For the other
        // three the value has already been positioned by the caller, and
        // masking again would clear bits the write never named.
        stored = (stored & ~byte_mask) | (value & byte_mask);
        break;
    case WriteOp::Set:
        stored |= value;
        break;
    case WriteOp::Clear:
        stored &= ~value;
        break;
    case WriteOp::Xor:
        stored ^= value;
        break;
    }
    return true;
}

}  // namespace riscv32
