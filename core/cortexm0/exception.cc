// OpenHardware — taking an Armv6-M exception, and coming back from one.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "exception.h"

namespace cortexm0 {
namespace {

/// Offsets of the eight stacked words from the frame pointer.
constexpr uint32_t kFrameBytes = 0x20;
constexpr uint32_t kFrameR0 = 0x00;
constexpr uint32_t kFrameR1 = 0x04;
constexpr uint32_t kFrameR2 = 0x08;
constexpr uint32_t kFrameR3 = 0x0C;
constexpr uint32_t kFrameR12 = 0x10;
constexpr uint32_t kFrameLr = 0x14;
constexpr uint32_t kFrameReturnAddress = 0x18;
constexpr uint32_t kFrameXpsr = 0x1C;

/// The bit of SP that an eight-byte alignment forces to zero.
constexpr uint32_t kFrameAlignBit = 4u;

}  // namespace

bool EnterException(Cpu& cpu, unsigned number) {
    const uint32_t sp = cpu.reg(kSp);
    // Whether SP has to move to reach an eight-byte boundary is decided from
    // where it is *now*, and recorded in the frame so return can undo exactly
    // this and not something that looks like it.
    const bool realigned = (sp & kFrameAlignBit) != 0;
    const uint32_t frame = (sp - kFrameBytes) & ~kFrameAlignBit;

    // xPSR as the architecture assembles it: the flags, EPSR.T -- always set,
    // because Armv6-M has no ARM state to return to -- the alignment bit, and
    // the exception number that was running.
    const uint32_t xpsr = cpu.apsr() | kEpsrThumb |
                          (realigned ? kXpsrFrameAlign : 0u) |
                          (cpu.scs().ipsr & kIcsrVectActive);

    // **Nothing is committed until all eight words are written.** A stack
    // pointing at a region that does not exist would otherwise leave the
    // machine half-entered: SP moved, some words stored, PC still in the
    // interrupted code. Writing to a local frame pointer and only then moving
    // SP keeps the failure a clean one.
    const bool stacked =
        cpu.write_word(frame + kFrameR0, cpu.reg(0)) &&
        cpu.write_word(frame + kFrameR1, cpu.reg(1)) &&
        cpu.write_word(frame + kFrameR2, cpu.reg(2)) &&
        cpu.write_word(frame + kFrameR3, cpu.reg(3)) &&
        cpu.write_word(frame + kFrameR12, cpu.reg(12)) &&
        cpu.write_word(frame + kFrameLr, cpu.reg(kLr)) &&
        cpu.write_word(frame + kFrameReturnAddress, cpu.reg(kPc) & ~1u) &&
        cpu.write_word(frame + kFrameXpsr, xpsr);
    if (!stacked) {
        return false;
    }

    uint32_t handler = 0;
    if (!cpu.read_word(cpu.scs().vector_table + 4u * number, handler)) {
        return false;
    }

    cpu.set_reg(kSp, frame);
    // Handler mode always runs on the main stack, so the EXC_RETURN a handler
    // sees says which mode it came *from*. The nested value is unreachable
    // with one exception source and is produced anyway, because it is what the
    // architecture puts there and a handler is entitled to read it.
    cpu.set_reg(kLr, cpu.scs().ipsr == 0 ? kExcReturnThread : kExcReturnHandler);
    cpu.scs().ipsr = number;
    // The vector's low bit is the Thumb bit and is not part of the address.
    // Armv6-M has no other state, so a vector with it clear is a fault on real
    // silicon; masking it here matches what the oracle does and keeps a badly
    // built vector table from becoming an unaligned fetch instead.
    cpu.set_reg(kPc, handler & ~1u);
    return true;
}

bool ReturnFromException(Cpu& cpu, uint32_t exc_return) {
    const uint32_t kind = exc_return & 0xFu;
    if (kind != (kExcReturnThread & 0xFu) && kind != (kExcReturnHandler & 0xFu)) {
        // 0b1101 is "return to Thread mode on the process stack", and this core
        // banks no process stack. Refusing is the loud answer; treating it as
        // the main stack would unstack a frame from somewhere nothing put one.
        return false;
    }

    const uint32_t frame = cpu.reg(kSp);
    uint32_t r0 = 0, r1 = 0, r2 = 0, r3 = 0, r12 = 0, lr = 0, pc = 0, xpsr = 0;
    const bool unstacked =
        cpu.read_word(frame + kFrameR0, r0) &&
        cpu.read_word(frame + kFrameR1, r1) &&
        cpu.read_word(frame + kFrameR2, r2) &&
        cpu.read_word(frame + kFrameR3, r3) &&
        cpu.read_word(frame + kFrameR12, r12) &&
        cpu.read_word(frame + kFrameLr, lr) &&
        cpu.read_word(frame + kFrameReturnAddress, pc) &&
        cpu.read_word(frame + kFrameXpsr, xpsr);
    if (!unstacked) {
        return false;
    }

    cpu.set_reg(0, r0);
    cpu.set_reg(1, r1);
    cpu.set_reg(2, r2);
    cpu.set_reg(3, r3);
    cpu.set_reg(12, r12);
    cpu.set_reg(kLr, lr);
    cpu.set_reg(kPc, pc & ~1u);
    cpu.set_apsr(xpsr);
    // Put back the four bytes entry took to align the frame, if it took them.
    cpu.set_reg(kSp, (frame + kFrameBytes) |
                         ((xpsr & kXpsrFrameAlign) ? kFrameAlignBit : 0u));
    // **IPSR comes from the frame, not from `exc_return`.** The two agree --
    // a frame stacked from Thread mode carries zero and its EXC_RETURN says
    // Thread -- and the frame is the one that keeps agreeing once exceptions
    // nest, because it names *which* exception was interrupted rather than
    // only whether one was.
    cpu.scs().ipsr = xpsr & kIcsrVectActive;
    return true;
}

bool ServicePending(Cpu& cpu) {
    const SystemControl& scs = cpu.scs();
    if (!scs.systick_pending || scs.primask) {
        return false;
    }
    if (scs.ipsr != 0) {
        // Already in a handler. SysTick cannot pre-empt itself, and the request
        // stays pending rather than being dropped, so it is taken the moment
        // the handler returns. Dropping it would lose a millisecond of
        // `millis()` every time a tick landed inside its own handler.
        return false;
    }
    if (!EnterException(cpu, kExceptionSysTick)) {
        return false;
    }
    // Cleared only once the frame is actually on the stack. Clearing first and
    // then failing to stack would lose the tick entirely.
    cpu.scs().systick_pending = false;
    return true;
}

}  // namespace cortexm0
