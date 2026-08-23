---
id: OH-9
title: 'PICSimLab adapter: bsim_i8086 and board_x86'
status: blocked
priority: P3
owner: session/adapter
created: '2026-08-23'
touches:
- core/picsimlab/**
- patches/0002-*.patch
---

Slices 2a and 2f. BLOCKED: needs a working PICSimLab build, and known-issues 4a.6 records that the NOGUI build cannot link (LTO ICE, GCC 11.4).
