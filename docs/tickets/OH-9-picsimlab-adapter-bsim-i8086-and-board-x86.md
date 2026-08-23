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

**Note 2026-08-24:** 2026-08-24, verified locally while scoping ESP support.

The ESP route runs through this ticket. PICSimLab ships an ESP32-C3-DevKitC-02 backed by an in-process QEMU fork (lcgamboa/qemu, branch picsimlab-esp32) built as shared libraries -- libqemu-riscv32 and libqemu-xtensa -- with a callback ABI for pins, UART, I2C, SPI and RMT. A XIAO ESP32-C3 is the same die on a different breakout, so on a WORKING PICSimLab it is board artwork plus an eleven-pin table.

Three things stand between here and that, and only the last is small:

1. No PICSimLab binary exists on this machine, and ../picsimlab-reference is source only. It carries share/ with 23 boards, which is all install_root() needs, but nothing executable.
2. The QEMU shared libraries are NOT in that tree -- src/sim_backend/bsim_qemu.cc is the consumer, and the libs it dlopens come from a separate fork that must also be built. Same for the ESP ROM images (esp32c3-rom.bin) it loads, which are a redistribution question of their own.
3. Only then is the XIAO board definition days of work.

Also: 4a.6 records that the NOGUI build fails to link but 'the WX GUI build is unaffected and works'. So the blocker is narrower than this ticket implies -- it is the NOGUI build specifically. Worth re-testing the GUI build, and worth checking whether upstream publishes prebuilt releases at all, since install_root() accepts a binary install and that would sidestep the compiler problem entirely.

**Note 2026-08-24:** 2026-08-24, correction. This ticket is NARROWER-BLOCKED than recorded, on two counts.

1. known-issues 4a.6 asserted that GCC 11.4 on Ubuntu 22.04 cannot link the NOGUI build. Upstream's own CI disproves it: .github/workflows/linux-release.yml runs a [ubuntu-22.04, ubuntu-24.04] matrix, gates the appimage step to 22.04, and that step performs the NOGUI link on every master push. The published AppImage was built from 62e8b5b -- the commit this reference clone is on. The local ICE is environmental, not inherent. 4a.6 now says so.

2. Nothing in this ticket needs NOGUI. The adapter work (bsim_i8086, board_x86) compiles into PICSimLab either way, and 4a.6 records that the WX GUI build works on this machine. So development can proceed against the GUI build now; NOGUI is a packaging concern for spec section 8.4 only.

And for the ESP route specifically: the prebuilt NOGUI AppImage bundles lib/qemu -- libqemu-riscv32, libqemu-xtensa and the ESP ROM images -- because build_appimage.sh copies it into the AppDir. That is exactly the stack the ESP path needs, with no build at all. Verified: the asset is 16,435,704 bytes and returns HTTP 200.
