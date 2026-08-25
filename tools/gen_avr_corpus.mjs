// OpenHardware — capture what avr8js does with each AVR encoding.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## Why a corpus and not a live lockstep
//
// `tools/lockstep_armv6m.mjs` runs a whole image beside rp2040js and compares
// each step. That works because an Armv6-M image runs to completion in both.
// Here the thing under test is *incomplete* — the point of OH-58 is that
// `core/avr` refuses 132 of the 246 encodings a real Arduino sketch uses — so a
// whole-image lockstep would stop on the first missing one and say nothing
// about the other 131.
//
// So this captures the oracle's answer for each encoding **separately**, into
// a committed JSON corpus, and `tests/avr/test_conformance.py` checks the core
// against it. The same arrangement `tests/rv32/corpus/` uses, and for the same
// reason `tools/gen_rv32_tests.py` gives: a corpus that needs the oracle
// present at test time is a corpus that stops running.
//
// ## The oracle
//
// avr8js 0.21.0, MIT, by the author of rp2040js — which this repository
// already drives for Armv6-M. Hand-written from Microchip's datasheet, so it
// is independent of anything `core/avr/exec.cc` was written from, which is the
// property `docs/architectures.md` 4.2 says agreement actually needs.
//
// **What it cannot tell us**, and the same limit `gen_rv32_tests.py` records
// for rvcpp: avr8js does not refuse. An encoding it does not know advances the
// PC and changes nothing, which is indistinguishable from a `nop` it does
// know. So this file never treats "the oracle did nothing" as "the instruction
// is illegal" — every case here is an encoding read from the AVR Instruction
// Set Manual's own tables, and the oracle is asked only what the *result* is.
//
// ## And one thing it gets wrong: the half-carry
//
// **Measured 2026-08-26 against avr8js 0.21.0.** Every one of its eleven H
// computations masks the boolean with `1` where the datasheet's formula reads
// bit **3**:
//
//     dist/cjs/cpu/instruction.js:32
//       sreg |= 1 & ((d & r) | (r & ~R) | (~R & d)) ? 0x20 : 0;
//
// `d` and `r` there are raw register bytes, never shifted, so it reads bit 0.
// The clearest case needs no formula at all: `add 0x08, 0x08` is 0x10, which
// plainly carries out of bit 3, and avr8js reports H = 0.
//
// `core/avr/exec.cc` is **right** here and the oracle is wrong. Worth saying
// twice, because the reflex on a differential failure is to change the thing
// under test — and doing that would have broken working code to match a bug.
//
// So a case carries **two sources and never blends them**, the arrangement
// `tools/gen_rv32_tests.py` reaches for on a different question:
//
//   * `avr8js` — registers, PC, SP, memory, and SREG *without* H.
//   * `manual` — H alone, from the AVR Instruction Set Manual's own boolean
//                expression, computed here and stored with the expression it
//                came from.
//
// If avr8js ever fixes this, the two agree and
// `test_the_oracle_half_carry_is_still_wrong` says so rather than passing
// quietly on an exclusion that has become dead.
//
// ## Determinism
//
// Register and flag seeds come from a fixed LCG, never from Math.random. A
// corpus that changed between runs would make a failing case unreproducible,
// which is exactly when reproducibility matters.

import { createRequire } from "node:module";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

const require = createRequire(import.meta.url);

const SEARCH = [
  process.env.AVR8JS_ROOT,
  resolve(process.cwd(), "third_party", "avr8js", "node_modules", "avr8js"),
  resolve(process.cwd(), "..", "avr8js"),
].filter(Boolean);

function findOracle() {
  for (const root of SEARCH) {
    if (root && existsSync(join(root, "dist", "cjs", "index.js"))) return root;
  }
  return null;
}

const root = findOracle();
if (!root) {
  console.error(
    "gen_avr_corpus: SKIPPED - no avr8js. Install it with:\n" +
      "  npm install --prefix third_party/avr8js avr8js@0.21.0"
  );
  process.exit(3);
}
const { CPU, avrInstruction } = require(join(root, "dist", "cjs", "index.js"));

// --- where the machine keeps things ----------------------------------------
//
// avr8js exposes one flat `data` array: the 32 registers, then the IO space,
// then SRAM. These are the ATmega328P's own addresses, not avr8js's invention.

const SREG = 0x5f;
const SPL = 0x5d;
const SPH = 0x5e;
const SRAM_START = 0x100;
const SRAM_BYTES = 2048;

/// What `ret` and `reti` find on the stack, as a WORD address.
///
/// **It has to be small, and 0x3400 is why.** avr8js ends every instruction
/// with `cpu.pc = (cpu.pc + 1) % cpu.progMem.length` (`instruction.js:860`),
/// and `progMem` here is 512 words. The first version of this file left
/// 0x34/0x00 on the stack, which is the word address 0x3400 -- an exact
/// multiple of 512, so the oracle wrapped it to **0** and the corpus recorded
/// `ret` as a jump to the reset vector. `core/avr` has 16,384 words and does
/// not wrap, so it would have returned to 0x3400 and been called wrong for
/// being right.
///
/// A return address inside 512 words never meets that modulus, so both
/// machines answer the same thing for the same reason.
const RETURN_ADDRESS = 0x0134;

// --- deterministic seeds ----------------------------------------------------

function lcg(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state >>> 24;
  };
}

/// One starting machine state. `variant` picks a different draw so each
/// encoding is tried against several operand pairs -- a flag rule that is only
/// wrong for negative operands is invisible if every operand is small.
function seedState(variant) {
  const next = lcg(0x5eed0000 + variant * 7919);
  const regs = new Array(32).fill(0).map(() => next());
  // Flags: cycle through the interesting carry/zero combinations rather than
  // drawing them, because `adc`, `sbc` and `cpc` all read C and `cpc` reads Z.
  const sreg = [0x00, 0x01, 0x02, 0x03, 0x21, 0x1f][variant % 6];
  return { regs, sreg };
}

// --- the encodings, read from the AVR Instruction Set Manual ---------------
//
// Each entry names the mnemonic, the encoding, and the fields it varies. The
// `words` are what actually goes into program memory; a 32-bit instruction is
// two of them.

function reg2(base, rd, rr) {
  // 0000 00rd dddd rrrr with r's high bit at position 9.
  return (
    base | ((rr & 0x10) << 5) | ((rd & 0x1f) << 4) | (rr & 0x0f)
  );
}

function immediate(base, rd, k) {
  // 0000 KKKK dddd KKKK, d in 16..31.
  return base | ((k & 0xf0) << 4) | (((rd - 16) & 0x0f) << 4) | (k & 0x0f);
}

const CASES = [];

function add(mnemonic, words, options = {}) {
  CASES.push({ mnemonic, words, ...options });
}

// --- the half-carry, from the manual rather than from the oracle -----------
//
// See the header. avr8js computes this from bit 0; the datasheet computes it
// from bit 3, which is what "carry out of the low nibble" means.

/// Which H rule a mnemonic follows, and the manual's expression for it. Three
/// rules cover everything here; every other instruction leaves H alone.
const HALF_CARRY = {
  add: "Rd3.Rr3 + Rr3./R3 + /R3.Rd3",
  adc: "Rd3.Rr3 + Rr3./R3 + /R3.Rd3",
  sub: "/Rd3.Rr3 + Rr3.R3 + R3./Rd3",
  subi: "/Rd3.Rr3 + Rr3.R3 + R3./Rd3",
  sbc: "/Rd3.Rr3 + Rr3.R3 + R3./Rd3",
  sbci: "/Rd3.Rr3 + Rr3.R3 + R3./Rd3",
  cp: "/Rd3.Rr3 + Rr3.R3 + R3./Rd3",
  cpc: "/Rd3.Rr3 + Rr3.R3 + R3./Rd3",
  cpi: "/Rd3.Rr3 + Rr3.R3 + R3./Rd3",
  neg: "R3 + Rd3",
};

/// The four mnemonics that read C as an *input*. Everything else in
/// `HALF_CARRY` computes its result from the two operands alone.
///
/// **This list is why `sub r5, r5` was reported wrong.** Feeding the seeded
/// carry to every arithmetic mnemonic made the manual expect `x - x - 1`,
/// whose bit 3 is set, where the machine computes `x - x` and clears it. The
/// oracle agreed with the core and only the second source was wrong -- which
/// is the failure a two-source arrangement is *supposed* to make visible, so
/// it is named here rather than folded into the expression above.
const READS_CARRY = new Set(["adc", "sbc", "sbci", "cpc"]);

/// H per the manual, or null when the instruction does not touch it -- and
/// null is a real answer, not a gap: SREG's H must then be unchanged, which
/// the test checks against the seed rather than against the oracle.
function manualHalfCarry(mnemonic, left, right, carryIn) {
  const name = mnemonic.split(" ")[0];
  const rule = HALF_CARRY[name];
  if (!rule) return null;

  const bit = (value, index) => (value >> index) & 1;
  if (name === "neg") {
    const result = (0 - left) & 0xff;
    return { h: bit(result, 3) | bit(left, 3), expression: rule };
  }
  const carry = READS_CARRY.has(name) ? carryIn : 0;
  const adding = name === "add" || name === "adc";
  const result = adding
    ? (left + right + carry) & 0xff
    : (left - right - carry) & 0xff;
  const d3 = bit(left, 3);
  const r3 = bit(right, 3);
  const s3 = bit(result, 3);
  const h = adding
    ? (d3 & r3) | (r3 & (1 - s3)) | ((1 - s3) & d3)
    : ((1 - d3) & r3) | (r3 & s3) | (s3 & (1 - d3));
  return { h, expression: rule };
}

/// The two register values a case's H depends on, dug out of its own encoding
/// so the generator does not need a second table saying which fields matter.
function operands(mnemonic, words, regs) {
  const name = mnemonic.split(" ")[0];
  const word = words[0];
  if (["add", "adc", "sub", "sbc", "cp", "cpc"].includes(name)) {
    const rd = (word >> 4) & 0x1f;
    const rr = (word & 0x0f) | ((word & 0x200) >> 5);
    return [regs[rd], regs[rr]];
  }
  if (["subi", "sbci", "cpi"].includes(name)) {
    const rd = 16 + ((word >> 4) & 0x0f);
    return [regs[rd], ((word & 0xf00) >> 4) | (word & 0x0f)];
  }
  if (name === "neg") {
    return [regs[(word >> 4) & 0x1f], 0];
  }
  return [0, 0];
}

// Register-register arithmetic and logic, the 0x0000-0x2FFF block.
for (const [name, base] of [
  ["add", 0x0c00], ["adc", 0x1c00], ["sub", 0x1800], ["sbc", 0x0800],
  ["and", 0x2000], ["or", 0x2800], ["eor", 0x2400], ["mov", 0x2c00],
  ["cp", 0x1400], ["cpc", 0x0400], ["cpse", 0x1000],
]) {
  for (const [rd, rr] of [[0, 1], [16, 17], [24, 25], [31, 30], [5, 5]]) {
    add(`${name} r${rd}, r${rr}`, [reg2(base, rd, rr), 0x0000]);
  }
}

// Register-immediate, d in 16..31.
for (const [name, base] of [
  ["subi", 0x5000], ["sbci", 0x4000], ["andi", 0x7000], ["ori", 0x6000],
  ["cpi", 0x3000], ["ldi", 0xe000],
]) {
  for (const [rd, k] of [[16, 0x00], [20, 0x01], [24, 0x7f], [31, 0xff], [17, 0x80]]) {
    add(`${name} r${rd}, ${k}`, [immediate(base, rd, k), 0x0000]);
  }
}

// One-operand, the 1001 010d dddd ____ block.
for (const [name, tail] of [
  ["com", 0x0], ["neg", 0x1], ["swap", 0x2], ["inc", 0x3], ["asr", 0x5],
  ["lsr", 0x6], ["ror", 0x7], ["dec", 0xa],
]) {
  for (const rd of [0, 16, 24, 31]) {
    add(`${name} r${rd}`, [0x9400 | ((rd & 0x1f) << 4) | tail, 0x0000]);
  }
}

// movw, which moves a pair and touches no flag.
for (const [rd, rr] of [[0, 2], [24, 30], [30, 24], [16, 18]]) {
  add(`movw r${rd}, r${rr}`, [0x0100 | ((rd >> 1) << 4) | (rr >> 1), 0x0000]);
}

// push and pop.
for (const rr of [0, 16, 28, 31]) {
  add(`push r${rr}`, [0x920f | ((rr & 0x1f) << 4), 0x0000]);
  add(`pop r${rr}`, [0x900f | ((rr & 0x1f) << 4), 0x0000]);
}

// nop, ret, reti, and the SREG bit setters.
add("nop", [0x0000, 0x0000]);
add("ret", [0x9508, 0x0000], { needsStack: true });
add("reti", [0x9518, 0x0000], { needsStack: true });
for (const [name, word] of [["sei", 0x9478], ["cli", 0x94f8], ["sec", 0x9408],
                            ["clc", 0x9488], ["sez", 0x9418], ["clz", 0x9498]]) {
  add(name, [word, 0x0000]);
}

// sbiw, the 16-bit immediate subtract adiw already has a partner for.
for (const [pair, k] of [[24, 0], [26, 1], [28, 0x3f], [30, 0x20]]) {
  add(`sbiw r${pair}, ${k}`,
      [0x9700 | ((k & 0x30) << 2) | (((pair - 24) / 2) << 4) | (k & 0x0f), 0x0000]);
}

// lds and sts: 32-bit, the second word is the address.
for (const rd of [0, 16, 31]) {
  add(`lds r${rd}, 0x0140`, [0x9000 | ((rd & 0x1f) << 4), 0x0140]);
  add(`sts 0x0150, r${rd}`, [0x9200 | ((rd & 0x1f) << 4), 0x0150]);
}

// jmp and call: 32-bit, the target is a word address split across both words.
for (const target of [0x0004, 0x0020, 0x00dc]) {
  add(`jmp 0x${target.toString(16)}`,
      [0x940c | ((target >> 17) << 4) | ((target >> 16) & 1), target & 0xffff]);
  add(`call 0x${target.toString(16)}`,
      [0x940e | ((target >> 17) << 4) | ((target >> 16) & 1), target & 0xffff]);
}

// The pointer loads and stores. X is r26, Y r28, Z r30.
for (const [name, word] of [
  ["ld r16, X", 0x910c], ["ld r16, X+", 0x910d], ["ld r16, -X", 0x910e],
  ["ld r16, Y", 0x8108], ["ld r16, Y+", 0x9109], ["ld r16, -Y", 0x910a],
  ["ld r16, Z", 0x8100], ["ld r16, Z+", 0x9101], ["ld r16, -Z", 0x9102],
  ["st X, r16", 0x930c], ["st X+, r16", 0x930d], ["st -X, r16", 0x930e],
  ["st Y, r16", 0x8308], ["st Y+, r16", 0x9309], ["st -Y, r16", 0x930a],
  ["st Z, r16", 0x8300], ["st Z+, r16", 0x9301], ["st -Z, r16", 0x9302],
]) {
  add(name, [word, 0x0000], { pointerIntoSram: true });
}

// lpm, which reads PROGRAM memory through Z -- the one instruction whose
// source is the other address space, and the reason `core/avr/cpu.h` keeps
// them apart at all.
for (const [name, word] of [["lpm", 0x95c8], ["lpm r16, Z", 0x9104],
                            ["lpm r16, Z+", 0x9105]]) {
  add(name, [word, 0x0000], { lpm: true });
}
// Z odd, which selects the HIGH byte of the word. Every case above has Z even,
// so a core that had the two halves the wrong way round would agree with all
// of them -- the seeded word is 0xbead and both halves are distinctive.
add("lpm r16, Z odd", [0x9104, 0x0000], { lpm: true, z: 0x0081 });

// The multiplies gcc emits for 16-bit arithmetic.
add("mul r16, r17", [0x9f01 | 0, 0x0000]);
add("muls r16, r17", [0x0201, 0x0000]);
add("mulsu r16, r17", [0x0301, 0x0000]);

// sbis / sbic, which skip on an IO bit.
for (const [name, base] of [["sbic", 0x9900], ["sbis", 0x9b00]]) {
  for (const [a, bit] of [[0x05, 0], [0x09, 5], [0x1f, 7]]) {
    add(`${name} 0x${a.toString(16)}, ${bit}`,
        [base | (a << 3) | bit, 0x0000, 0x0000]);
  }
}

// --- skipping OVER a 32-bit instruction ------------------------------------
//
// **How far a skip goes is a property of the instruction being skipped**, and
// every case above has a `nop` in the next slot, so all of them are one word
// and none of them test the rule. Land one word short of a `jmp` and the PC
// sits on a bare 16-bit target address, which decodes as whatever it happens
// to look like -- the machine keeps running, executing a program nobody wrote.
//
// avr8js has `isTwoWordInstruction` for exactly this. All four wide encodings
// an ATmega328P has appear below as the thing being skipped.
//
// IO address 0x1f is data 0x3f, which is zero here -- so `sbic` skips and
// `sbis` does not. The last case is the one that matters in the other
// direction: a core that read the width and skipped two words *regardless* of
// the condition would pass every case above it.
add("cpse r5, r5 skipping jmp", [reg2(0x1000, 5, 5), 0x940c, 0x0020]);
add("cpse r5, r5 skipping lds", [reg2(0x1000, 5, 5), 0x9000, 0x0140]);
add("sbic 0x1f, 7 skipping call", [0x9900 | (0x1f << 3) | 7, 0x940e, 0x0020]);
add("sbic 0x1f, 7 skipping sts", [0x9900 | (0x1f << 3) | 7, 0x9200, 0x0150]);
add("sbis 0x1f, 7 not skipping jmp", [0x9b00 | (0x1f << 3) | 7, 0x940c, 0x0020]);

// --- run each case against the oracle --------------------------------------

const VARIANTS = 3;
const out = [];

for (const testcase of CASES) {
  for (let variant = 0; variant < VARIANTS; variant++) {
    const { regs, sreg } = seedState(variant);

    // 512 words is enough for every target above and keeps the corpus small.
    const program = new Uint16Array(512);
    testcase.words.forEach((word, index) => (program[index] = word));
    // Something recognisable in program memory for `lpm` to find, at the Z the
    // seed sets below.
    program[0x40] = 0xbead;

    const cpu = new CPU(program, SRAM_BYTES);
    for (let i = 0; i < 32; i++) cpu.data[i] = regs[i];
    cpu.data[SREG] = sreg;

    // A stack with room to pop from, and a return address already on it.
    // `rcall` writes the low byte at SP and the high byte at SP-1, so after a
    // call SP+1 holds the high byte and SP+2 the low one -- which is the order
    // `ret` reads them back in.
    const sp = SRAM_START + SRAM_BYTES - 32;
    cpu.data[SPL] = sp & 0xff;
    cpu.data[SPH] = (sp >> 8) & 0xff;

    // **Every byte this generator writes into data memory, by address.** It
    // goes into the corpus, because `tests/avr/test_conformance.py` has to set
    // the machine up *identically* or the comparison is against a different
    // program: `ret` and `pop` read the stack, and a test that seeded nothing
    // would watch the core return to 0 while the oracle returned here.
    //
    // It is also what the write diff below subtracts. The first version kept
    // that list in a second place and got it wrong -- 0x200 and 0x220 counted
    // as seeded even for cases that never set them, so every non-pointer case
    // recorded two writes of 0x00 that never happened.
    const seeded = {
      [sp + 1]: (RETURN_ADDRESS >> 8) & 0xff,
      [sp + 2]: RETURN_ADDRESS & 0xff,
    };
    // X, Y and Z, pointed somewhere a store cannot overwrite the operands and
    // hide a bug.
    //
    // **Z is the exception and it needs one.** `lpm` reads PROGRAM memory
    // through Z by *byte* address, so its cases point Z at the word seeded
    // above; everything else points it into SRAM like X and Y. Z used to be
    // 0x0080 for both, which is extended IO rather than SRAM -- so every
    // `st Z` wrote below the range the diff below scans and no store through Z
    // was checked at all.
    if (testcase.pointerIntoSram || testcase.lpm) {
      const z = testcase.z ?? (testcase.lpm ? 0x0080 : 0x0240);
      for (const [low, high, at] of [[26, 27, 0x0200], [28, 29, 0x0220], [30, 31, z]]) {
        cpu.data[low] = at & 0xff;
        cpu.data[high] = (at >> 8) & 0xff;
      }
      seeded[0x0200] = 0xa5;
      seeded[0x0220] = 0x5a;
      seeded[0x0240] = 0x3c;
    }
    for (const [address, value] of Object.entries(seeded)) {
      cpu.data[Number(address)] = value;
    }

    const before = {
      regs: Array.from(cpu.data.slice(0, 32)),
      sreg: cpu.data[SREG],
      sp,
    };

    avrInstruction(cpu);

    // Every byte of the data space above the register file, minus the three
    // the test compares by name. **Not just SRAM**: the register file is
    // 0x00-0x1F, the IO window 0x20-0xFF and SRAM only starts at 0x100, so a
    // scan that began at SRAM would never see a store into the IO window --
    // which is exactly where a pointer set to 0x0080 used to land.
    const writes = {};
    for (let address = 0x20; address < cpu.data.length; address++) {
      if (address === SPL || address === SPH || address === SREG) continue;
      const original = address in seeded ? seeded[address] : 0;
      if (cpu.data[address] !== original) writes[address] = cpu.data[address];
    }

    const [left, right] = operands(testcase.mnemonic, testcase.words, before.regs);
    const manual = manualHalfCarry(
      testcase.mnemonic, left, right, before.sreg & 1
    );

    out.push({
      mnemonic: testcase.mnemonic,
      words: testcase.words.map((w) => `0x${w.toString(16).padStart(4, "0")}`),
      variant,
      manual,
      initial: {
        regs: before.regs,
        sreg: before.sreg,
        sp: before.sp,
        // Data memory, address -> byte. `before.regs` already holds the
        // pointer registers, so the test needs no second rule about which
        // cases set X, Y and Z: it writes these bytes and those registers.
        memory: seeded,
      },
      avr8js: {
        pc: cpu.pc,
        regs: Array.from(cpu.data.slice(0, 32)),
        sreg: cpu.data[SREG],
        sp: cpu.data[SPL] | (cpu.data[SPH] << 8),
        writes,
      },
    });
  }
}

const target = resolve(process.cwd(), "tests", "avr", "corpus", "isa.json");
mkdirSync(dirname(target), { recursive: true });
writeFileSync(target, JSON.stringify(out, null, 1) + "\n");
console.log(`gen_avr_corpus: ${out.length} cases from ${CASES.length} encodings -> ${target}`);
