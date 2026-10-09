---
id: OH-220
title: 'The cores build Debug on Windows: MSVC''s default build type beats CMakeLists''
  Release fallback, at about a quarter of the speed'
status: open
priority: P1
created: '2026-10-09'
touches:
- tools/build_core.py
- CMakeLists.txt
- tests/rules/test_build_core.py
---

Every core this repository builds on Windows is a Debug build: unoptimised, with runtime checks. `tools/build_core.py` configures with no build type and builds with `--config Release`, which a single-configuration generator (Ninja, which it prefers) ignores. `CMakeLists.txt` then means to default to Release:

    if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
      set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
    endif()

but that runs after `project()`, and on MSVC CMake has already set CMAKE_BUILD_TYPE from its platform default, `CMAKE_BUILD_TYPE_INIT` = Debug, so the condition is false and the fallback never fires.

Seen 2026-10-09: `lane3`'s build/ was deleted and configured fresh by `python tools/build_core.py --clean` with CMAKE_BUILD_TYPE unset in the environment, and its CMakeCache.txt says `CMAKE_BUILD_TYPE:STRING=Debug`, `CMAKE_CXX_FLAGS_DEBUG:STRING=/Zi /Ob0 /Od /RTC1`. The main checkout's and every lane's cache say the same.

What it costs, measured by OH-161's reviews on this machine: `riscv32_step` through ctypes ran at 1.89M steps/s on build/'s Debug core against 6.83M on a Release core built outside the repo (OH-161 step 2's review); `session.run` on a QT Py C3 and a SparkFun C5 ran at 1.23M steps/s on the Debug core (OH-161's delay() review). Since delay() waits on the SYSTIMER (OH-161), a delay(500) on a 160 MHz ESP32 is 80,000,000 instructions, which at the Debug rate is about a minute of wall clock per half period of the page's default Blink. clock.js's own figures (2.6M steps/s for an Uno) were taken on whatever core was built then.

STEPS:
1. Make a configure that names no build type produce a Release build on every generator: set the default before `project()`, or pass `-DCMAKE_BUILD_TYPE=Release` from build_core.py for single-config generators. Say which, and why, in the file. A build/ configured before the fix keeps its cached Debug, so build_core.py must detect a cached Debug (or any non-Release type it did not ask for) and either reconfigure or refuse with the value, not build Debug silently.
2. A test that holds it: the cache build_core.py writes says Release (or the multi-config build used Release), seen to fail on today's code.
3. Measure steps/s before and after on one AVR, one Cortex-M0 and one RISC-V board through `session.run`, dated, and correct any figure in the page or docs that the change makes wrong (clock.js's header measures an Uno; check it against the new core rather than assuming).
4. The full suite still passes on the Release core: tests that count steps are unaffected by speed, but a test that times anything is not.
