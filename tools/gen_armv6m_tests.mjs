// OpenHardware — generate an Armv6-M conformance corpus from rp2040js.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## Why this exists
//
// No Armv6-M single-step corpus exists anywhere. SingleStepTests has 22
// repositories and not one is M-profile — and "SST-shaped" does not imply
// hardware capture either: only the x86 family there claims it, while
// ARM7TDMI came from NanoBoyAdvance and m68000 from MAME. So a Cortex-M0+
// core has nothing to be checked against, and this project does not ship a
// core without an oracle.
//
// **rp2040js is the oracle that exists today.** MIT, hand-written from
// DDI0419 — so genuinely independent of QEMU, unlike Unicorn (QEMU's TCG) and
// Renode (tlib, also QEMU-derived). It models Cortex-M0**+**, which QEMU
// cannot do at all: QEMU's `arm_v7m_cpus[]` has m0, m3, m4, m7, m33, m55 and
// no m0plus. And it runs here at ~1.19 M cases/sec, three orders of magnitude
// faster than the ~300/sec a real SWD rig manages.
//
// ## What it is NOT
//
// **This is a simulator oracle, not silicon.** rp2040js's instructions were
// silicon-diffed once, via gdbdiff in lockstep against a real RP2040, and that
// caught genuine bugs in ADCS overflow, CMP carry and LSRS edges. But that was
// a one-off, not a continuously-checked claim, and it is exactly the gap this
// corpus is meant to start closing. A case here means "agrees with rp2040js",
// which is weaker than the 8088 corpus's "agrees with an AMD D8088". Anything
// built on it must say so.
//
// A second limit worth stating before anyone trusts a green run: **rp2040js
// does not model faults.** It never calls `exceptionEntry(EXC_HARDFAULT)`; an
// unrecognised opcode reaches `logger.warn('… not implemented yet!')` and
// execution continues. So this generator restricts itself to encodings that
// are unambiguously defined, and the corpus says nothing about what the
// hardware *refuses*. That boundary is where a conformance corpus earns its
// keep, and it needs silicon or a configurable model.
//
// ## One deliberate divergence from the 8088 format
//
// SST8088's `final` is a **delta** — it records only what changed, and
// `tools/sst8088.py` calls that "the one thing that will bite a harness
// author", because a naive comparison checks one register and declares a pass.
// This corpus emits the **complete** final state instead. There is no reason
// to reproduce a known hazard in a format we control, and the space saved is
// not worth a class of silent false pass.

import { createRequire } from "node:module";
import { gzipSync } from "node:zlib";
import { writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

const require = createRequire(import.meta.url);

// --- locating rp2040js -------------------------------------------------------
//
// Same resolution order as webui/picsimlab.py uses for PICSimLab: an explicit
// environment variable first, then siblings of the repository. A generator
// that cannot find its oracle **exits 3 and says SKIPPED**, exactly as the
// rule checkers do — it never emits an empty corpus and reports success.

const SEARCH = [
  process.env.RP2040JS_ROOT,
  resolve(process.cwd(), "..", "rp2040js"),
  resolve(process.cwd(), "third_party", "rp2040js"),
].filter(Boolean);

// rp2040js publishes CommonJS under dist/cjs and ES modules under dist/esm;
// there is no flat dist/rp2040.js. Probe both rather than assume, so a layout
// change is a clear error instead of a confusing MODULE_NOT_FOUND.
const ENTRIES = [
  join("dist", "cjs", "rp2040.js"),
  join("dist", "rp2040.js"),
  join("dist", "cjs", "index.js"),
];

function findOracle() {
  for (const root of SEARCH) {
    if (!root || !existsSync(join(root, "src", "cortex-m0-core.ts"))) continue;
    for (const entry of ENTRIES) {
      if (existsSync(join(root, entry))) return { root, entry };
    }
    return { root, entry: null }; // found the source but not a build
  }
  return null;
}

// --- the encodings this generator covers -------------------------------------
//
// Formats 1–4 of the 16-bit Thumb map: everything from 0x0000 to 0x43FF that
// is register-only. Chosen as the first slice deliberately — no memory, no
// branches, no exceptions, and *all* of it sets flags. Flags are where an
// Armv6-M core is hardest to get right and where an oracle pays for itself:
// the shift-by-zero carry rules and ADCS/SBCS overflow are the classic
// silent-wrong cases, and are three of the four bugs gdbdiff found in
// rp2040js itself.

const R = (n) => n & 7;

/** Each family builds one random valid encoding from a random source. */
const FAMILIES = {
  // Format 1 — shift by immediate. imm5 == 0 is the special case: for LSL it
  // means "shift by zero, leave C alone", for LSR and ASR it means 32.
  lsls_imm: (r) => (0b000 << 13) | (0 << 11) | ((r() & 31) << 6) | (R(r()) << 3) | R(r()),
  lsrs_imm: (r) => (0b000 << 13) | (1 << 11) | ((r() & 31) << 6) | (R(r()) << 3) | R(r()),
  asrs_imm: (r) => (0b000 << 13) | (2 << 11) | ((r() & 31) << 6) | (R(r()) << 3) | R(r()),

  // Format 2 — add/subtract, register and 3-bit immediate.
  adds_reg: (r) => 0x1800 | (R(r()) << 6) | (R(r()) << 3) | R(r()),
  subs_reg: (r) => 0x1a00 | (R(r()) << 6) | (R(r()) << 3) | R(r()),
  adds_imm3: (r) => 0x1c00 | (R(r()) << 6) | (R(r()) << 3) | R(r()),
  subs_imm3: (r) => 0x1e00 | (R(r()) << 6) | (R(r()) << 3) | R(r()),

  // Format 3 — mov/cmp/add/sub with an 8-bit immediate.
  movs_imm8: (r) => 0x2000 | (R(r()) << 8) | (r() & 0xff),
  cmp_imm8: (r) => 0x2800 | (R(r()) << 8) | (r() & 0xff),
  adds_imm8: (r) => 0x3000 | (R(r()) << 8) | (r() & 0xff),
  subs_imm8: (r) => 0x3800 | (R(r()) << 8) | (r() & 0xff),
};

// Format 4 — the ALU group, one entry per opcode so a failure names the
// mnemonic rather than a bit pattern.
const ALU = {
  ands: 0, eors: 1, lsls_reg: 2, lsrs_reg: 3, asrs_reg: 4, adcs: 5, sbcs: 6,
  rors: 7, tst: 8, negs: 9, cmp_reg: 10, cmn: 11, orrs: 12, muls: 13,
  bics: 14, mvns: 15,
};
for (const [name, op] of Object.entries(ALU)) {
  FAMILIES[name] = (r) => 0x4000 | (op << 6) | (R(r()) << 3) | R(r());
}

// --- deterministic randomness -----------------------------------------------
//
// xorshift32, seeded from the command line. `rules/determinism.md` forbids
// nondeterministic calls in new code, and a corpus that cannot be regenerated
// byte-for-byte is not a fixture — it is a snapshot nobody can audit.

function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => {
    s ^= s << 13; s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5; s >>>= 0;
    return s;
  };
}

// --- main --------------------------------------------------------------------

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : fallback;
};

const outDir = opt("--out", join("third_party", "armv6m", "v1"));
const count = Number(opt("--count", "1000"));
const seed = Number(opt("--seed", "1"));
const only = opt("--families", "");

const found = findOracle();
if (!found) {
  console.error(
    "gen_armv6m_tests: no rp2040js found. SKIPPED.\n" +
      "  Looked in: " + SEARCH.join(", ") + "\n" +
      "  Fix: git clone https://github.com/wokwi/rp2040js ../rp2040js && " +
      "(cd ../rp2040js && npm install && npm run build)\n" +
      "  or set RP2040JS_ROOT."
  );
  process.exit(3);
}
if (!found.entry) {
  console.error(
    `gen_armv6m_tests: found rp2040js at ${found.root} but it is not built. SKIPPED.\n` +
      "  Fix: (cd " + found.root + " && npm install && npm run build)"
  );
  process.exit(3);
}
const { root, entry } = found;

const { RP2040, RAM_START_ADDRESS } = require(join(root, entry));

const rp2040 = new RP2040();
const core = rp2040.core;

const PC = RAM_START_ADDRESS + 0x1000;
const SANDBOX = RAM_START_ADDRESS + 0x2000;
const MEMWORDS = 8;

const flagsWord = () =>
  (core.N ? 0x80000000 : 0) | (core.Z ? 0x40000000 : 0) |
  (core.C ? 0x20000000 : 0) | (core.V ? 0x10000000 : 0);

function oneCase(encoding, r, index) {
  const regs = [];
  for (let i = 0; i < 13; i++) { core.registers[i] = r(); regs.push(core.registers[i] >>> 0); }
  core.SP = (SANDBOX + 0x400) & ~3;
  core.LR = r() | 1;
  core.PC = PC;
  core.N = (r() & 1) === 1;
  core.Z = (r() & 1) === 1;
  core.C = (r() & 1) === 1;
  core.V = (r() & 1) === 1;

  const initial = {
    regs: Array.from({ length: 16 }, (_, i) => core.registers[i] >>> 0),
    flags: flagsWord() >>> 0,
  };

  rp2040.writeUint16(PC, encoding);
  rp2040.writeUint16(PC + 2, 0xbf00); // NOP guard, so a mis-sized fetch is visible
  const ram = [];
  for (let i = 0; i < MEMWORDS; i++) {
    const v = r() >>> 0;
    rp2040.writeUint32(SANDBOX + i * 4, v);
    ram.push(v);
  }
  initial.ram = ram;

  core.executeInstruction();

  return {
    name: `${encoding.toString(16).padStart(4, "0")} #${index}`,
    encoding,
    initial,
    // Complete, not a delta -- see the header.
    final: {
      regs: Array.from({ length: 16 }, (_, i) => core.registers[i] >>> 0),
      flags: flagsWord() >>> 0,
      ram: Array.from({ length: MEMWORDS }, (_, i) => rp2040.readUint32(SANDBOX + i * 4) >>> 0),
    },
  };
}

mkdirSync(outDir, { recursive: true });

const wanted = only
  ? only.split(",").map((s) => s.trim()).filter(Boolean)
  : Object.keys(FAMILIES);

let total = 0;
for (const family of wanted) {
  const build = FAMILIES[family];
  if (!build) {
    console.error(`gen_armv6m_tests: unknown family '${family}'`);
    process.exit(2);
  }
  // Each family gets its own stream, so adding a family never renumbers the
  // cases of one already generated.
  const r = rng(seed + family.split("").reduce((a, c) => a + c.charCodeAt(0), 0));
  const cases = [];
  for (let i = 0; i < count; i++) cases.push(oneCase(build(r), r, i));
  const path = join(outDir, `${family}.json.gz`);
  writeFileSync(path, gzipSync(Buffer.from(JSON.stringify(cases))));
  total += cases.length;
  console.log(`${family.padEnd(12)} ${String(cases.length).padStart(6)} cases  ->  ${path}`);
}

console.log(`\n${total} cases across ${wanted.length} families, seed ${seed}.`);
console.log("oracle: rp2040js at " + root + " -- a simulator, not silicon.");
