---
id: OH-61
title: 'A compile service: sketch source and a board name in, a loadable image out'
status: done
priority: P1
created: '2026-08-26'
touches:
- webui/compile.py
- webui/emulator_server.py
- tests/webui/test_compile.py
avoid:
- webui/api.py
---

THE USER ASKED FOR THIS TWICE. 2026-08-25: 'can you get actual ide where code is runable in a main loop if wanted? support standard development workflows like platformio and arduino style'. Two options were measured and the user chose to finish the AVR core first so that VENDOR Arduino sketches run. OH-58 and OH-59 did that: a stock Blink now crosses its vector table, runs setup(), and toggles PB5 at 500.0 ms. This is the next piece, and it is the load-bearing one -- an editor with nothing to compile with is a text box.

WHAT EXISTS TODAY. Nothing compiles. webui/api.py takes BYTES and a board name; a person builds elsewhere and picks a file. tools/import_firmware.py FINDS built artefacts in .pio/build, arduino-cli and STM32CubeIDE trees (42 tests) and nothing under webui/ imports it -- that is OH-10 and it is a different question: OH-10 locates an image somebody else built, this one builds it.

THE TOOLCHAINS ARE ALREADY HERE, all under $USERPROFILE/.platformio/packages (NOT ~, which Git Bash resolves to a redirect that does not exist):

    toolchain-atmelavr           avr-gcc 7.3.0
    toolchain-gccarmnoneeabi     arm-none-eabi 12.3.1
    toolchain-riscv32-esp        riscv32-esp-elf 8.4.0
    framework-arduino-avr        the Uno's core -- proven, tests/avr/test_arduino_sketch.py builds against it
    framework-arduino-samd       the XIAO-SAMD21's
    framework-arduinoespressif32 the ESP32-C3's, and it has no esp32c5/esp32c6

SAFETY, ALREADY DECIDED by the user on 2026-08-25: loopback bind plus an Origin check, the same posture webui/emulator_server.py already keeps. The request carries SOURCE and a BOARD NAME. **The server picks the compiler, the flags and the linker script from the board description, never from the request.** A request that could name its own compiler or pass its own flags is a request that can run any program on the host, and the boundary that matters here is who can ask -- webui/bridge.py argues this at length and the argument is the same one.

BUILD IT VERTICALLY. One board end to end before any second one: Arduino Uno, one .cpp, compiled against framework-arduino-avr exactly as tests/avr/test_arduino_sketch.py's fixture already does -- that fixture is a working prototype of the compile half and should be read first, including the two things it got wrong (avr-gcc for .c and avr-g++ for .cpp are not interchangeable, and check=True hides the diagnostic that is the only useful part of a failure).

WHAT MUST BE LOUD. A compile error is the most common thing that will happen here and it is a NORMAL result, not a fault: the compiler's own stderr, with the line numbers, has to reach the caller intact. A service that answers 'build failed' is useless. Equally: a board with no toolchain installed must SKIP-and-say, never silently offer a build that cannot happen.

Done when a sketch typed as a string, plus the name 'Arduino Uno', comes back as bytes that webui/api.load_firmware accepts and that toggle PB5 at 500 ms; when a sketch with a deliberate syntax error comes back with avr-gcc's own message naming the line; and when a board whose toolchain is absent says which one it wanted.

**Note 2026-08-26:** CLOSED 2026-08-26.

DONE-WHEN, all four met. A sketch as a string plus 'Arduino Uno' returns bytes api.load_firmware accepts (1,946 bytes, starting 0c 94). Those bytes toggle PB5 at 8,000,095 instructions -- 500.0 ms. A deliberate syntax error returns avr-gcc's own message at sketch.cpp:2:22, which is the line the person typed. An absent toolchain names the PlatformIO package it wanted.

THE SAFETY SHAPE IS ASSERTED STRUCTURALLY, not by trying a payload. test_nothing_in_a_recipe_comes_from_a_request reads build()'s signature and fails if it ever takes more than a board name and source -- an attempted exploit proves one payload was handled; this proves the shape. The untrusted half reaches subprocess in exactly one place, as file CONTENTS in a per-build temporary directory.

TWO THINGS FOUND WHILE BUILDING IT.

(1) PlatformIO does not inject #include <Arduino.h> into a .cpp, only into a .ino -- OH-10's notes already recorded this and it is why the first good sketch failed to compile. The preamble is prepended, and it ENDS WITH #line 1 "sketch.cpp" because prepending shifts every diagnostic down one line. A line number that is confidently wrong is worse than none.

(2) The image this service builds links HardwareSerial, so Serial's global constructor runs before setup(): DDRB is set at step 941, against 116 for the four-source blink tests/avr/test_arduino_sketch.py builds. A step budget copied from that file fails here for a reason that has nothing to do with compiling. Recorded in the test.

/api/board/compile BUILDS AND LOADS in one step, so no image crosses the wire in either direction -- the only thing a client could do with one is post it straight back. A failed build leaves the board untouched, so a syntax error does not cost a person the program that was running.

SCOPE HELD: one board end to end, as the ticket asked. RECIPES has one row. The ESP32-C3, SAMD21 and RP2040 all have toolchains installed and none has a recipe, which is deliberate -- a second row is a second slice, and the refusal for a board without one names its chip.

Gate: 1,403 passed, 17 skipped; all eight checkers exit 0.
