---
id: OH-264
title: A core library older than its sources is loaded without a word, and its tests
  fail as wrong answers
status: open
priority: P3
created: '2026-11-05'
touches:
- tools/build_core.py
- tests/rules/test_build_core.py
---

Found 2026-11-05 landing OH-162. After OH-11 landed core/i8086/muldiv.cc, a worktree whose build/lib/i8086.dll predated it ran tests/i8086/test_muldiv.py and six tests failed as wrong results -- 'IDIV BX of FFFE:8000 by 3 stored 8000', flags off, traps missing -- and nothing said the library was stale. python tools/build_core.py fixed all six (tests/i8086: 232 passed).

ensure_built in tools/build_core.py returns a library that exists as it is, on purpose (OH-220): rebuilding from inside a load would relink a DLL the server or another test session may hold open. That stays. What is missing is the same treatment the Debug build gets: tests/rules/test_build_core.py fails on a build/ that is not Release and names the fix, and nothing fails on a library older than the sources it is built from. A test there that compares each built library's mtime with the newest of its core's sources (core/<arch>/**, and the shared headers), and fails naming the newer source and 'python tools/build_core.py', would turn six misleading failures into one that says what to do. The ABI-version check in core/i8086/abi.py does not catch it: OH-11 changed behaviour and not the ABI.

Check that it fails on a fresh build/ with one source touched afterwards, and passes after a rebuild.
