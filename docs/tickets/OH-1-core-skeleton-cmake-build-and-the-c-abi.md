---
id: OH-1
title: Core skeleton, CMake build and the C ABI
status: open
priority: P0
owner: session/core
created: '2026-08-23'
touches:
- core/i8086/CMakeLists.txt
- core/i8086/abi.*
- core/i8086/cpu.h
- CMakeLists.txt
- tests/i8086/conftest.py
---

The C++ core's build and the flat C ABI pytest drives through ctypes. Must compile with MSVC and g++. Proves the pipeline before any CPU logic.
