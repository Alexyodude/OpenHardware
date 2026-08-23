// OpenHardware - flat C ABI over the i8086 core.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "abi.h"

#include <new>

#include "cpu.h"
#include "decode.h"
#include "exec_core.h"

namespace {

// The opaque handle Python holds. A struct rather than a bare `Cpu*` so the
// header can forward-declare it without exposing any C++.
struct Handle {
    i8086::Cpu cpu;
};

inline i8086::Cpu* Of(I8086Cpu* p) { return &reinterpret_cast<Handle*>(p)->cpu; }
inline const i8086::Cpu* Of(const I8086Cpu* p) {
    return &reinterpret_cast<const Handle*>(p)->cpu;
}

}  // namespace

extern "C" {

int i8086_abi_version(void) { return I8086_ABI_VERSION; }
uint32_t i8086_regs_size(void) { return static_cast<uint32_t>(sizeof(I8086Registers)); }
uint32_t i8086_memory_size(void) { return i8086::kMemorySize; }

I8086Cpu* i8086_new(void) {
    // nothrow: an exception crossing a C ABI boundary is undefined, and a
    // null return is something ctypes can actually check.
    return reinterpret_cast<I8086Cpu*>(new (std::nothrow) Handle());
}

void i8086_free(I8086Cpu* cpu) {
    if (cpu != nullptr) {
        delete reinterpret_cast<Handle*>(cpu);
    }
}

void i8086_reset(I8086Cpu* cpu) {
    if (cpu != nullptr) {
        Of(cpu)->Reset();
    }
}

void i8086_get_regs(const I8086Cpu* cpu, I8086Registers* out) {
    if (cpu == nullptr || out == nullptr) {
        return;
    }
    const i8086::Registers& r = Of(cpu)->regs();
    out->ax = r.ax;
    out->bx = r.bx;
    out->cx = r.cx;
    out->dx = r.dx;
    out->si = r.si;
    out->di = r.di;
    out->bp = r.bp;
    out->sp = r.sp;
    out->cs = r.cs;
    out->ds = r.ds;
    out->es = r.es;
    out->ss = r.ss;
    out->ip = r.ip;
    out->flags = r.flags;
}

void i8086_set_regs(I8086Cpu* cpu, const I8086Registers* in) {
    if (cpu == nullptr || in == nullptr) {
        return;
    }
    i8086::Registers r;
    r.ax = in->ax;
    r.bx = in->bx;
    r.cx = in->cx;
    r.dx = in->dx;
    r.si = in->si;
    r.di = in->di;
    r.bp = in->bp;
    r.sp = in->sp;
    r.cs = in->cs;
    r.ds = in->ds;
    r.es = in->es;
    r.ss = in->ss;
    r.ip = in->ip;
    r.flags = in->flags;
    Of(cpu)->set_regs(r);
}

uint8_t i8086_read_byte(const I8086Cpu* cpu, uint32_t address) {
    return cpu == nullptr ? 0u : Of(cpu)->ReadByte(address);
}

void i8086_write_byte(I8086Cpu* cpu, uint32_t address, uint8_t value) {
    if (cpu != nullptr) {
        Of(cpu)->WriteByte(address, value);
    }
}

uint16_t i8086_read_word(const I8086Cpu* cpu, uint32_t address) {
    return cpu == nullptr ? 0u : Of(cpu)->ReadWord(address);
}

void i8086_write_word(I8086Cpu* cpu, uint32_t address, uint16_t value) {
    if (cpu != nullptr) {
        Of(cpu)->WriteWord(address, value);
    }
}

void i8086_write_block(I8086Cpu* cpu, uint32_t address, const uint8_t* data, uint32_t length) {
    if (cpu == nullptr || data == nullptr) {
        return;
    }
    // Byte at a time rather than memcpy: the address wraps at 1 MB, and a
    // memcpy of a block straddling the top would run off the end of the
    // buffer instead of wrapping to zero.
    for (uint32_t i = 0; i < length; ++i) {
        Of(cpu)->WriteByte(address + i, data[i]);
    }
}

void i8086_read_block(const I8086Cpu* cpu, uint32_t address, uint8_t* out, uint32_t length) {
    if (cpu == nullptr || out == nullptr) {
        return;
    }
    for (uint32_t i = 0; i < length; ++i) {
        out[i] = Of(cpu)->ReadByte(address + i);
    }
}

void i8086_clear_memory(I8086Cpu* cpu) {
    if (cpu != nullptr) {
        Of(cpu)->ClearMemory();
    }
}

uint32_t i8086_physical(uint16_t segment, uint16_t offset) {
    return i8086::Physical(segment, offset);
}

int i8086_step(I8086Cpu* cpu) {
    if (cpu == nullptr) {
        return 1;
    }
    return static_cast<int>(i8086::Step(*Of(cpu)));
}

int i8086_opcode_info(uint8_t opcode) {
    const i8086::OpcodeInfo info = i8086::Lookup(opcode);
    return (info.implemented ? 1 : 0) | (info.has_modrm() ? 2 : 0) |
           (info.wide ? 4 : 0);
}

uint32_t i8086_decoded_size(void) { return static_cast<uint32_t>(sizeof(I8086Decoded)); }

void i8086_decode(const I8086Cpu* cpu, uint16_t cs, uint16_t ip, I8086Decoded* out) {
    if (cpu == nullptr || out == nullptr) {
        return;
    }
    const i8086::Instruction decoded = i8086::Decode(*Of(cpu), cs, ip);
    *out = I8086Decoded{};
    out->opcode = decoded.opcode;
    out->has_modrm = decoded.has_modrm ? 1u : 0u;
    out->mod = decoded.modrm.mod;
    out->reg = decoded.modrm.reg;
    out->rm = decoded.modrm.rm;
    out->displacement = decoded.displacement;
    out->segment_override = static_cast<uint8_t>(decoded.segment_override);
    out->length = decoded.length;
    out->valid = decoded.valid ? 1u : 0u;
    out->immediate = decoded.immediate;
    out->form = static_cast<uint8_t>(i8086::Lookup(decoded.opcode).form);
    out->repeat = static_cast<uint8_t>(decoded.repeat);
    out->reg_in_opcode = decoded.reg_in_opcode;
    out->wide = decoded.wide ? 1u : 0u;

    if (decoded.has_modrm && !decoded.modrm.is_register()) {
        const i8086::Address address = i8086::EffectiveAddress(
            Of(cpu)->regs(), decoded.modrm, decoded.displacement, decoded.segment_override);
        out->has_memory_operand = 1u;
        out->ea_segment = static_cast<uint8_t>(address.segment);
        out->ea_offset = address.offset;
        out->ea_physical =
            i8086::Physical(i8086::SegmentValue(Of(cpu)->regs(), address.segment), address.offset);
    }
}

}  // extern "C"
