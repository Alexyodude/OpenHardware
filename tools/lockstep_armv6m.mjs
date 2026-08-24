// OpenHardware — run real firmware in lockstep against rp2040js.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## Why this exists alongside the corpus
//
// `tools/gen_armv6m_tests.mjs` samples random encodings with random operands.
// That is the right shape for arithmetic and flags, and it is a poor shape for
// everything a program actually does: it never builds a stack frame, never
// takes a branch it computed, never loads a literal it just stored. A core can
// pass 13,500 random cases and fail on the first function call.
//
// This runs the *same firmware image* through both models and compares all
// sixteen registers and the flags after every instruction, stopping at the
// first disagreement. Where the corpus asks "is this encoding right", this
// asks "does this program do the same thing", and the second question is the
// one that decides whether a board works.
//
// It is also the honest progress meter. "Instructions executed before
// diverging" is a number that cannot be argued with, and it goes up as the
// core gets better.
//
// ## What it is not
//
// rp2040js models the RP2040's peripherals and this core does not. So a run
// ends at the first peripheral access no matter how correct the instruction
// set is, and **that ending is expected, not a failure**. The output
// distinguishes the two: a mismatch in registers is a bug in this core, and a
// fault at 0x4xxxxxxx is a missing peripheral.

import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

const require = createRequire(import.meta.url);

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

// --- UF2, only enough of it to get bytes into flash --------------------------
//
// The full reader is `webui/firmware.py`, which is where the rules live. This
// is the same three rules in twenty lines because this script cannot import
// Python: filter by family, ignore the block's own counters when the family
// does not match, and place each payload at its own targetAddr.

const UF2_BLOCK = 512;
const RP2040_FAMILY = 0xe48bff56;

function readUf2(path) {
  const data = readFileSync(path);
  const segments = [];
  for (let offset = 0; offset + UF2_BLOCK <= data.length; offset += UF2_BLOCK) {
    const block = data.subarray(offset, offset + UF2_BLOCK);
    if (block.readUInt32LE(0) !== 0x0a324655) continue;
    const flags = block.readUInt32LE(8);
    const target = block.readUInt32LE(12);
    const size = block.readUInt32LE(16);
    const family = block.readUInt32LE(28);
    if ((flags & 0x00002000) !== 0 && family !== RP2040_FAMILY) continue;
    if ((flags & 0x00000001) !== 0) continue; // not-main-flash
    segments.push([target, Uint8Array.from(block.subarray(32, 32 + size))]);
  }
  return segments;
}

// --- main --------------------------------------------------------------------

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : fallback;
};

const image = opt("--image", null);
const limit = Number(opt("--limit", "200000"));
const dump = args.includes("--dump-trace");
const profile = args.includes("--profile-peripherals");

if (!image) {
  console.error("usage: node tools/lockstep_armv6m.mjs --image <firmware.uf2> [--limit N]");
  process.exit(2);
}

const root = findOracle();
if (!root) {
  console.error(
    "lockstep_armv6m: no built rp2040js found. SKIPPED.\n" +
      "  Looked in: " + SEARCH.join(", ") + "\n" +
      "  Fix: git clone https://github.com/wokwi/rp2040js ../rp2040js && " +
      "(cd ../rp2040js && npm install && npm run build)"
  );
  process.exit(3);
}

const { RP2040 } = require(join(root, "dist", "cjs", "rp2040.js"));

const segments = readUf2(image);
if (segments.length === 0) {
  console.error(`lockstep_armv6m: ${image} yielded no RP2040 blocks`);
  process.exit(2);
}

const rp2040 = new RP2040();
const core = rp2040.core;
for (const [address, bytes] of segments) {
  for (let i = 0; i < bytes.length; i++) {
    rp2040.flash[address - 0x10000000 + i] = bytes[i];
  }
}

// Start where the image's vector table says, skipping boot2. The first 256
// bytes of a Pico image are the flash-XIP setup blob, which programs the SSI
// -- a peripheral. Executing it is not the instruction set's job and both
// models would need the same SSI to agree about it.
const VECTORS = 0x10000100;
const sp = rp2040.readUint32(VECTORS);
const entry = rp2040.readUint32(VECTORS + 4);
core.SP = sp;
core.PC = entry & ~1;

// --- what does this firmware actually touch? --------------------------------
//
// The instruction set stops mattering the moment firmware reads a peripheral,
// and on a Pico that is the *second* instruction. So the oracle's bus is
// wrapped to record every access outside flash and SRAM, which turns "add
// peripherals" from an open-ended task into a measured list in the order the
// firmware needs them.
//
// Wrapping rather than reading rp2040js's own tables: what matters is which
// addresses this image reaches, not which the part has.

const peripheralHits = new Map();
const REGION_NAMES = [
  [0x40000000, 0x40010000, "SYSINFO/SYSCFG/CLOCKS/RESETS/PSM"],
  [0x40010000, 0x40020000, "IO_BANK0/IO_QSPI/PADS"],
  [0x40020000, 0x40030000, "XOSC/PLL_SYS/PLL_USB"],
  [0x40030000, 0x40040000, "BUSCTRL/UART/SPI/I2C/ADC/PWM"],
  [0x40040000, 0x40060000, "TIMER/WATCHDOG/RTC/ROSC"],
  [0x50000000, 0x50400000, "DMA"],
  [0xd0000000, 0xd0001000, "SIO (GPIO, spinlocks, divider)"],
  [0xe0000000, 0xe0100000, "PPB (SysTick, NVIC, SCB)"],
];

function regionName(address) {
  for (const [lo, hi, name] of REGION_NAMES) {
    if (address >= lo && address < hi) return name;
  }
  return "unmapped";
}

function noteAccess(address, kind) {
  if (address >= 0x10000000 && address < 0x10200000) return;  // flash
  if (address >= 0x20000000 && address < 0x20042000) return;  // sram
  const key = `${address >>> 0}:${kind}`;
  const seen = peripheralHits.get(key);
  if (seen) { seen.count++; return; }
  peripheralHits.set(key, {
    address: address >>> 0, kind, count: 1,
    first: executedSoFar, region: regionName(address >>> 0),
  });
}

let executedSoFar = 0;
if (profile) {
  // Patched on the **core**, not on the RP2040. The core delegates to the
  // machine, but the instruction fetch does not go through either -- so
  // wrapping only the machine caught one access in 200,000 instructions and
  // made a busy firmware look idle.
  for (const name of ["readUint32", "readUint16", "readUint8"]) {
    const original = core[name].bind(core);
    core[name] = (address) => { noteAccess(address, "read"); return original(address); };
  }
  for (const name of ["writeUint32", "writeUint16", "writeUint8"]) {
    const original = core[name].bind(core);
    core[name] = (address, value) => { noteAccess(address, "write"); return original(address, value); };
  }
}

/// Where the program spends its time. A firmware that spins is not the same as
/// one that runs, and "200,000 instructions executed" hides the difference.
const pcHistogram = new Map();

const state = () => {
  const regs = [];
  for (let i = 0; i < 16; i++) regs.push(core.registers[i] >>> 0);
  const flags =
    (core.N ? 0x80000000 : 0) | (core.Z ? 0x40000000 : 0) |
    (core.C ? 0x20000000 : 0) | (core.V ? 0x10000000 : 0);
  return { regs, flags: flags >>> 0 };
};

// The trace is emitted as JSON on stdout so the Python side can replay it
// against this repository's core without needing to embed a JS runtime.
const trace = { image, sp, entry, start: core.PC >>> 0, steps: [] };
let executed = 0;
for (; executed < limit; executed++) {
  executedSoFar = executed;
  if (profile) pcHistogram.set(core.PC >>> 0, (pcHistogram.get(core.PC >>> 0) ?? 0) + 1);
  // rp2040js does not fault. It warns and carries on, so its instruction
  // count keeps rising long after the program has left anything executable.
  // The first PC outside flash and SRAM is where its numbers stop meaning
  // anything, and it is the honest end of a comparison run.
  {
    const here = core.PC >>> 0;
    const inFlash = here >= 0x10000000 && here < 0x10200000;
    const inSram = here >= 0x20000000 && here < 0x20042000;
    if (!inFlash && !inSram && trace.leftMemoryAt === undefined) {
      trace.leftMemoryAt = executed;
      trace.leftMemoryPc = here;
    }
  }
  const before = state();
  const pc = core.PC >>> 0;
  try {
    core.executeInstruction();
  } catch (error) {
    trace.stopped = `oracle threw at 0x${pc.toString(16)}: ${error.message}`;
    break;
  }
  trace.steps.push({ pc, before, after: state() });
  if ((core.PC >>> 0) === pc) {
    // A branch to itself. Real firmware ends in one of these when it faults,
    // and continuing would fill the trace with a million identical entries.
    trace.stopped = `self-branch at 0x${pc.toString(16)} after ${executed + 1} steps`;
    break;
  }
}
trace.executed = executed;

if (profile) {
  const hits = [...peripheralHits.values()].sort((a, b) => a.first - b.first);
  console.log(`executed ${executed} instructions; ${hits.length} distinct peripheral accesses`);
  console.log("");
  console.log("  step   address     kind   count  region");
  for (const h of hits.slice(0, 40)) {
    console.log(
      `  ${String(h.first).padStart(5)}  0x${h.address.toString(16).padStart(8, "0")}  ` +
      `${h.kind.padEnd(5)}  ${String(h.count).padStart(5)}  ${h.region}`);
  }
  const byRegion = new Map();
  for (const h of hits) byRegion.set(h.region, (byRegion.get(h.region) ?? 0) + h.count);
  const hot = [...pcHistogram.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  console.log("");
  console.log("  hottest addresses (a tight loop here means it is spinning):");
  for (const [pc, n] of hot) {
    console.log(`    0x${pc.toString(16).padStart(8, "0")}  visited ${n} times`);
  }
  console.log("");
  console.log("  accesses by region, most-used first:");
  for (const [name, count] of [...byRegion].sort((a, b) => b[1] - a[1])) {
    console.log(`    ${String(count).padStart(7)}  ${name}`);
  }
} else if (dump) {
  process.stdout.write(JSON.stringify(trace));
} else {
  console.log(`image      ${image}`);
  console.log(`vectors    SP 0x${sp.toString(16)}  entry 0x${entry.toString(16)}`);
  console.log(`executed   ${executed} instructions in the oracle`);
  console.log(`stopped    ${trace.stopped ?? "reached the limit"}`);
  console.log(
    trace.leftMemoryAt === undefined
      ? "in range   PC stayed in flash or SRAM for the whole run"
      : `LEFT MEMORY at step ${trace.leftMemoryAt}, PC 0x${trace.leftMemoryPc.toString(16)}` +
        " -- everything the oracle reports after this point is fiction");
}
