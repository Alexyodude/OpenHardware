---
id: OH-15
title: Land the verified corrections into docs/architectures.md
status: open
priority: P2
created: '2026-08-24'
touches:
- docs/architectures.md
---

Nine verification lanes produced roughly a dozen corrections to the survey, tiered by evidence class: datasheet-backed or verified-by-execution; toolchain-sourced only; and unresolved conflicts to record rather than settle. Two of the survey's cells were challenged and survived -- ESP32-C2 does have atomics, and the vendor extension names are the datasheets' own spellings -- so those retractions must NOT land. The tiering is the point: a correction sourced from IDF and LLVM headers is not the same claim as one read off a datasheet, and flattening them is what produced the wrong C2 'correction' in the first place.
