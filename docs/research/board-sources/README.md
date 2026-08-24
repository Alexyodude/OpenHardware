# Board-source survey — NOT adopted

Everything in this directory is **research output from a single session, not
repository policy.** Nothing here is loaded by any code, checked by any
checker, or referenced by any rule. Turning it into a vendor registry is
OH-24's decision, not this ticket's.

It is here because OH-23 asked what the market actually publishes, and the
answer is a set of dated claims about sixteen other people's servers. Those
claims rot, so they are recorded with the evidence that produced them and a
script that re-checks them.

## What is here

| Path | What |
|---|---|
| `sources.json` | The survey. One entry per source, every cell carrying its own evidence class and citation. The only file anyone edits by hand. |
| `survey.md` | **Generated.** The table and the per-source detail. `render.py` writes it; do not edit it. |
| `render.py` | `sources.json` → `survey.md`. No network. |
| `probe.py` | Re-fetches the machine-checkable cells and prints what no longer matches. Never edits `sources.json`. |

A row is identified by its `url`, which is unique. `vendor` is not — Raspberry
Pi has two rows — and neither is the shape a row publishes in, since three
vendors ship one repository per board. Anything reading `sources.json` should
key on the URL.

```bash
python docs/research/board-sources/render.py   # rebuild the table
python docs/research/board-sources/probe.py    # re-check it against the sources
```

## The entry point is sources, not boards

"Every MCU development board" is thousands of boards, and CLAUDE.md forbids
the artefact that would list them, because an inventory is the document that
rots fastest. A survey of *sources* is smaller, changes far more slowly, and
answers the question that actually decides work: given a board, can its
geometry be obtained, in what format, and on what terms.

Sixteen source rows cover fifteen vendors. Raspberry Pi has two rows because
it publishes two incompatible things and merging them would have destroyed the
most useful fact in the survey.

## How to read the evidence classes

`docs/architectures.md` marks every claim for how it was established, and its
value is that it does not average contradictions away. The same idea applies
here, one class per cell rather than per row — because within a single source
they genuinely differ. Nordic's schematic source was opened here; the absence
of a 3D model was inferred from a listing; the scope of its licence is
contested and stays that way.

| Class | Means |
|---|---|
| `O` opened | the artefact was fetched here and its contents listed or read |
| `L` listed | the host's own file listing was read; the filenames are real, the files were not opened |
| `S` stated | a vendor page or README asserts it; nobody opened the artefact |
| `A` absent | a complete listing was searched and it is not there |
| `U` unreachable | the source could not be reached from here; what was tried is recorded |

`A` and `U` are not the same and the difference matters. `A` is a finding —
we looked at the whole tree and the file is not in it. `U` is a gap, and the
row records what was tried so the next person does not repeat it.

## What this survey found that changes the shape of the problem

**Size decides vendoring, not licence.** `tools/get_seeed_hardware.sh`
established that on one vendor; it holds across the rest. Seeed's repository is
MIT and 196,037 KiB, and nearly all of that is marketing PNGs. Espressif's
`esp-dev-kits` is Apache-2.0 and 827,468 KiB and contains no board hardware
files at all. Olimex's ESP32-POE is Apache-2.0, 36,801 KiB, and holds every
artefact class this ticket asks about. Permission and usefulness are
uncorrelated; only fetching sparsely makes any of them affordable.

**A licence covering a repository does not cover the design files, because the
design files are often not in it.** Espressif is the clean case: the Apache-2.0
grant is over example code and documentation, and the schematics live on
`dl.espressif.com` under no stated terms whatsoever. Nordic is the messy one:
its five-clause licence says "software" in every clause and is shipped inside
an Altium PCB project.

**The licence is a property of a download, not of a vendor.** Raspberry Pi's
Pico zip ships a permissive grant; the Pico W zip, same vendor and adjacent
board, ships none. One SparkFun board repository tells you to read a
`LICENSE.md` that is not in it, while three sibling repositories have one. Any
registry keyed on vendor will be wrong about specific boards on its first day.

**Schematic *source* is common; schematic source in a format anything here can
read is not.** Most of what is published as schematic source is EagleCAD,
Altium or Cadence OrCAD binary. The exceptions — KiCad text that
can be walked to a netlist — are Olimex, M5Stack in part, and Raspberry Pi's
CM5 IO board.

**The vendor this project already imports from publishes the least.** Seeed
ships footprints and symbols and no schematic and no PCB layout at all. That
is why the boards in `webui/boards/` are pad maps rather than netlists, and it
means OH-28 cannot be satisfied from the source that produced the current
board set.

## What to distrust

**The two rows that are gaps, not findings.** ST could not be reached from this
network at all — every attempt is recorded in its notes — and ST is
the vendor `docs/architectures.md` most depends on, since it picks STM32 C0/G0
as "build our own" and names a $12 Nucleo-C031C6 as the oracle. TI's row is
thin because two tool pages were read and neither offered a design-file
package; that is what was found, not proof of what TI publishes.

**Every row is one board, sampled.** Adafruit has 634 repositories matching
"PCB" and one was opened. SparkFun has 1,413 repositories and four were
touched. A row says what that sample held; it does not say the vendor is
uniform, and Olimex and SparkFun both demonstrate within-vendor variance in
the sample already taken.

**One cell is deliberately left unresolved.** TI's schematic-PDF cell reads
`unknown` over evidence class `O`, which looks like a contradiction and is not:
the user guide was downloaded and is a real PDF, and no text extractor was
available here to confirm the schematic is inside it. Recording "probably" as
"yes" is exactly the failure this survey is shaped to avoid.

**Filenames are not artefacts.** Waveshare's `WAVESHARE-RP2040-Board.zip` reads
like board files and contains two MicroPython firmware images. Espressif's
`esp-dev-kits` really does contain STEP files, and all four are 3D-printed
enclosure parts. Both would have been recorded wrongly by any pass that
tallied extensions without opening anything, and the `O` class exists to mark
where that did not happen.
