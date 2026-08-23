---
id: OH-1
title: Core skeleton, CMake build and the C ABI
status: in-review
priority: P0
owner: session/core
created: '2026-08-23'
touches:
- core/i8086/CMakeLists.txt
- core/i8086/abi.*
- core/i8086/cpu.h
- CMakeLists.txt
- tests/i8086/conftest.py
- core/i8086/cpu.cc
- core/i8086/abi.cc
- tests/i8086/test_abi.py
- tools/build_core.py
---

The C++ core's build and the flat C ABI pytest drives through ctypes. Must compile with MSVC and g++. Proves the pipeline before any CPU logic.

**Note 2026-08-23:** Builds and passes on Windows/MSVC. Held at in-review until CI proves the g++ path -- this code has never been seen by GCC.
