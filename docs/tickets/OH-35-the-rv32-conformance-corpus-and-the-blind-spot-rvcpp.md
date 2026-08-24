---
id: OH-35
title: The RV32 conformance corpus, and the blind spot rvcpp has at the illegal-instruction
  edge
status: open
priority: P2
created: '2026-08-25'
touches:
- tools/gen_rv32_tests.py
- tests/rv32/**
parent: OH-34
---

catalogue.py's ORACLES entry for riscv32 states the problem exactly: rvcpp 'builds here, but has no extension gating at all -- right on the legal space, wrong at the illegal-instruction edge.' An oracle that executes every extension is a perfect reference for legal code and silently wrong about what an RV32IMC part must refuse.

That matters concretely. The C3 is RV32IMC and must trap an A-extension instruction; the C6 is RV32IMAC and must execute it. Lockstep against rvcpp cannot tell those apart, because rvcpp runs both. A core built only against it will happily execute atomics on a C3 and the test suite will agree.

So the corpus carries the gating that the oracle lacks. Build it the way OH-17 built the Armv6-M one -- generated from a source, not hand-written -- and mark each case with which of the two the verdict comes from: rvcpp, or the ISA manual's encoding tables. Those are different evidence classes and docs/architectures.md's habit is to keep them apart rather than average them.

The Xtensa entry is the cautionary tale: two oracles that look independent and share one Tensilica archive, so their agreement proves nothing. rvcpp's failure is narrower and known, which makes it usable -- as long as it is written down.

Done when an A-extension instruction is refused on a C3 target and executed on a C6 target, with the verdict for each traced to its source.
