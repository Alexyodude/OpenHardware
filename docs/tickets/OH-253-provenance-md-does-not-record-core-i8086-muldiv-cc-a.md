---
id: OH-253
title: PROVENANCE.md does not record core/i8086/muldiv.cc as a port of MartyPC
status: open
priority: P2
created: '2026-11-05'
touches: []
---

OH-11 replaced the host multiply and divide in core/i8086/muldiv.cc with a step-by-step port of the 8088's CORX, CORD, NEGATE, PREIMUL, IMULCOF, MULCOF, PREIDIV and POSTIDIV microcode routines as MartyPC models them in its muldiv.rs (MIT, Copyright Daniel Balsom, github.com/dbalsom/martypc at commit f0ebca4e411e55685b661e9efe1d136a9c727a7c). The file carries MartyPC's full MIT notice beside this repository's, which is all the licence asks, and check_licenses passes.

What is missing is the record. PROVENANCE.md says what in this tree came from somewhere else and on what terms, and its §4 lists third-party code kept verbatim; a port from Rust to C++ is not verbatim but is derived, and nothing there says so. OH-11 could not add it: PROVENANCE.md is claimed by OH-244, which was in progress at the time.

Add an entry (under §4, or §2 if a translation reads as a grey area) naming the file, the upstream file and commit, the licence, and that the notice is kept in the header. Filed by OH-11.

This ticket claims no file yet, because two open tickets may not claim one (rules/ticket-claims.md §2). Whoever takes it adds PROVENANCE.md with `tickets set --touch` once OH-244 is done or has released it.
