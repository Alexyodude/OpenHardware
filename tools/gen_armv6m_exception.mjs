// OpenHardware — ask rp2040js what an Armv6-M exception does to the machine.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## Why this is separate from the corpus and from the lockstep
//
// `gen_armv6m_tests.mjs` samples encodings, and an exception is not one: no
// instruction takes it, so no encoding can be sampled to provoke it.
// `lockstep_armv6m.mjs` runs firmware and compares registers, and it stops at
// the first peripheral access -- which for any image that enables SysTick is
// before the first tick.
//
// So the one thing neither can answer is the thing this answers: **when a
// SysTick exception is taken, what exactly is on the stack, and what is in the
// registers on the way out.** Eight words whose *locations* are architected
// and whose order is not, plus an alignment bit that only matters when SP
// happens to sit at an odd word. That is precisely the shape of thing to check
// against an independent implementation rather than against one reading of
// DDI0419.
//
// ## The one thing this deliberately does not compare
//
// **When the tick arrives.** rp2040js drives SysTick from simulated clock
// cycles; `core/cortexm0` has no cycle model and counts retired instructions.
// The two therefore cannot agree on the rate and there is no point pretending
// otherwise -- so each case here *forces* the exception pending and asks only
// what happens next. See `Cpu::tick_systick` in cpu.h, which states the same
// approximation at the place it is made.
//
// Prints JSON on stdout. `tests/cortexm0/test_exceptions.py` runs it wherever
// rp2040js exists and compares; where it does not, that one test skips and the
// values stay asserted from the copy recorded in the test file.
//
//   node tools/gen_armv6m_exception.mjs

import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

const require = createRequire(import.meta.url);

// Same resolution order as the other two tools, and the same contract: a
// generator that cannot find its oracle exits 3 and says SKIPPED.
const SEARCH = [
  process.env.RP2040JS_ROOT,
  resolve(process.cwd(), "..", "rp2040js"),
  resolve(process.cwd(), "third_party", "rp2040js"),
].filter(Boolean);

function findOracle() {
  for (const root of SEARCH) {
    if (root && existsSync(join(root, "dist", "cjs", "rp2040.js"))) return root;
  }
  return null;
}

const root = findOracle();
if (!root) {
  console.error(
    "gen_armv6m_exception: no built rp2040js found. SKIPPED.\n" +
      "  Looked in: " + SEARCH.join(", ") + "\n" +
      "  Fix: git clone https://github.com/wokwi/rp2040js ../rp2040js && " +
      "(cd ../rp2040js && npm install && npm run build)\n" +
      "  or set RP2040JS_ROOT."
  );
  process.exit(3);
}

const { RP2040, RAM_START_ADDRESS } = require(join(root, "dist", "cjs", "rp2040.js"));

// The vector table, the handler and the interrupted code all live in RAM, so
// this says nothing about where an RP2040 puts its flash -- the point is the
// mechanism, and VTOR is what makes the table's address the caller's choice.
const VECTORS = RAM_START_ADDRESS;
const HANDLER = RAM_START_ADDRESS + 0x1000;
const RESUME = RAM_START_ADDRESS + 0x2000;
const STACK_TOP = RAM_START_ADDRESS + 0x3000;
const EXC_SYSTICK = 15;

/// Sentinels, so a word that ends up in the wrong slot names the slot it came
/// from. Deliberately not sequential: 0,1,2,3 would let an off-by-one frame
/// still look plausible.
const SENTINEL = {
  r0: 0xa0a00000, r1: 0xa1a10001, r2: 0xa2a20002, r3: 0xa3a30003,
  r4: 0x44444444, r12: 0xacacacac, lr: 0x1eeeeeef,
};

const B_SELF = 0xe7fe;   // b .
const BX_LR = 0x4770;    // bx lr
const POP_R4_PC = 0xbd10; // pop {r4, pc}
const PUSH_R4_LR = 0xb510; // push {r4, lr}

function fresh() {
  const rp2040 = new RP2040();
  const core = rp2040.core;
  core.VTOR = VECTORS;
  rp2040.writeUint32(VECTORS + 4 * EXC_SYSTICK, HANDLER | 1);
  rp2040.writeUint16(RESUME, B_SELF);
  core.registers[0] = SENTINEL.r0;
  core.registers[1] = SENTINEL.r1;
  core.registers[2] = SENTINEL.r2;
  core.registers[3] = SENTINEL.r3;
  core.registers[4] = SENTINEL.r4;
  core.registers[12] = SENTINEL.r12;
  core.LR = SENTINEL.lr;
  core.PC = RESUME;
  core.N = true;
  core.Z = false;
  core.C = true;
  core.V = false;
  return { rp2040, core };
}

const flags = (core) =>
  ((core.N ? 0x80000000 : 0) | (core.Z ? 0x40000000 : 0) |
   (core.C ? 0x20000000 : 0) | (core.V ? 0x10000000 : 0)) >>> 0;

function raise(core) {
  core.pendingSystick = true;
  core.interruptsUpdated = true;
}

/// The entry frame, for a given starting SP.
///
/// **rp2040js takes the exception at the top of `executeInstruction` and then
/// executes an instruction in the same call**, where this core makes entry its
/// own step. That is a difference in step *accounting*, not in the machine --
/// but it is why the handler here is `b .` and not `bx lr`: with `bx lr` the
/// oracle enters and returns inside one call, and everything read afterwards
/// is the state it came back to. That cost a debugging round, so it is written
/// down rather than left as a magic constant.
function entry(sp) {
  const { rp2040, core } = fresh();
  core.SP = sp;
  rp2040.writeUint16(HANDLER, B_SELF);
  raise(core);
  core.executeInstruction();
  const frame = core.SP;
  return {
    sp_before: sp >>> 0,
    frame: frame >>> 0,
    stacked: Array.from({ length: 8 }, (_, i) => rp2040.readUint32(frame + 4 * i) >>> 0),
    lr: core.LR >>> 0,
    ipsr: core.IPSR >>> 0,
  };
}

/// A full round trip: enter, run the handler, come back.
///
/// `handler` is the sequence of halfwords the handler is built from. Both
/// forms a compiler emits are exercised -- a leaf handler returning through
/// `bx lr`, and one that pushed a frame returning through `pop {r4, pc}` --
/// because the second one writes PC from memory rather than from a register
/// and is the path that gets missed.
function roundTrip(sp, handler) {
  const { rp2040, core } = fresh();
  core.SP = sp;
  handler.forEach((halfword, i) => rp2040.writeUint16(HANDLER + 2 * i, halfword));
  raise(core);
  // Generous: the longest handler here is two instructions plus the entry that
  // shares a call with the first of them.
  for (let i = 0; i < 8; i++) {
    core.executeInstruction();
    if ((core.PC & ~1) === RESUME) break;
  }
  return {
    sp_before: sp >>> 0,
    sp_after: core.SP >>> 0,
    pc: (core.PC & ~1) >>> 0,
    regs: [0, 1, 2, 3, 4, 12].map((n) => core.registers[n] >>> 0),
    lr: core.LR >>> 0,
    flags: flags(core),
    ipsr: core.IPSR >>> 0,
  };
}

/// PRIMASK set: the request stays pending and no frame is stacked.
function masked(sp) {
  const { rp2040, core } = fresh();
  core.SP = sp;
  rp2040.writeUint16(HANDLER, BX_LR);
  core.PM = true;
  raise(core);
  core.executeInstruction();
  return {
    sp_after: core.SP >>> 0,
    pc: (core.PC & ~1) >>> 0,
    ipsr: core.IPSR >>> 0,
    still_pending: Boolean(core.pendingSystick),
  };
}

console.log(JSON.stringify({
  oracle: "rp2040js",
  root,
  addresses: { vectors: VECTORS, handler: HANDLER, resume: RESUME, stack_top: STACK_TOP },
  sentinel: SENTINEL,
  // An eight-byte-aligned SP, and one four bytes below it. The second is the
  // only case in which the alignment bit is set, and it is the case a model
  // built from the first alone gets wrong.
  entry_aligned: entry(STACK_TOP),
  entry_misaligned: entry(STACK_TOP - 4),
  return_bx_lr: roundTrip(STACK_TOP, [BX_LR]),
  return_bx_lr_misaligned: roundTrip(STACK_TOP - 4, [BX_LR]),
  return_pop_pc: roundTrip(STACK_TOP, [PUSH_R4_LR, POP_R4_PC]),
  masked: masked(STACK_TOP),
}, null, 2));
