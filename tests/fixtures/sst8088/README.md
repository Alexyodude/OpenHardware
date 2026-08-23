# SST8088 sample cases

Eleven test cases excerpted from
[`SingleStepTests/8088`](https://github.com/SingleStepTests/8088) v2.0.1,
**MIT licensed**, © Daniel Balsom. The full `LICENSE` text travels with the
upstream repository; this directory is an excerpt for testing the reader, not a
redistribution of the suite.

Those tests were produced by running a physical **AMD D8088 (8441DMA), dated
1982, in Maximum Mode** on the
[Arduino8088](https://github.com/dbalsom/arduino_8088) interface. That is what
makes them hardware ground truth rather than another emulator's opinion — and
they are the only such corpus this project has.

## Why an excerpt is committed at all

The full corpus is **≈2 GB**, so `rules/licence-hygiene.md` §5 and plain
sense both say fetch it, do not vendor it: `tools/get_8088_tests.sh` does
that.

But a conformance harness needs tests of its own, and those must not reach the
network — a suite that fails when GitHub is slow is a suite people learn to
ignore, and `rules/determinism.md` wants the same input to give the
same result every run. So the reader is tested against these eleven cases,
offline and deterministically, while real conformance runs use the fetched
corpus.

| file | opcode | why this one |
|---|---|---|
| `90.json` | `0x90` NOP | the trivial case, and it carries a segment-override prefix (`2E`) so prefix handling is exercised from the start |
| `88.json` | `0x88` MOV r/m8, r8 | modrm decoding with a register destination |
| `00.json` | `0x00` ADD r/m8, r8 | memory operand, displacement, and arithmetic flags |

Each case is verbatim from the corpus, including `hash` and `idx`, so any of
them can be located in the upstream file it came from.
