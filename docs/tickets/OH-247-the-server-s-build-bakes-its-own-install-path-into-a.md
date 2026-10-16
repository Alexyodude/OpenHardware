---
id: OH-247
title: The server's build bakes its own install path into a SAMD21 image and shows
  it, lowercased, in a link error
status: open
priority: P2
created: '2026-10-17'
---

Found in OH-244's review (2026-10-17). Two ways webui/compile.py lets the machine it runs on into what it returns. (1) __FILE__: SPI.cpp's SPIClassSAMD constructor asserts, so a sketch that builds an SPI bus of its own links the path compile.py compiled SPI.cpp at -- C:\Users\<name>\.platformio\packages\framework-arduino-samd\libraries\SPI\SPI.cpp on this machine -- into the image. That image differs from machine to machine, carries the user's name, and can never be the static page's bytes; tests/webui/test_compile_wasm.py holds the difference by name. Fix: -fmacro-prefix-map (GCC 8 and later; the AVR's 7.3.0 has only -fdebug-prefix-map, and the Uno core has no assert) mapping PACKAGES, BOARD_SUPPORT and ARDUINO_LITE each to one token, on both sides, the bundle's build_compiler.py mapping its own roots to the same tokens. (2) On Windows, binutils 2.40's ld prints paths lowercased, c:/users/..., so _diagnostics' <toolchain> label, matched case-sensitively against PACKAGES, misses a SAMD21 link error's every path. Fix: match case-insensitively on Windows. Needs webui/compile.py, which OH-161 holds; the same-bytes tests are OH-244's. Not started: compile.py stays as it is until then.
