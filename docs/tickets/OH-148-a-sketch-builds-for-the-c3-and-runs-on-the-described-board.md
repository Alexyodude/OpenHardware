---
id: OH-148
title: 'A sketch builds for the C3 and runs on the described board: the openhardware
  core'
status: done
priority: P2
created: '2026-08-31'
touches:
- webui/arduino/cores/openhardware/Arduino.h
- webui/arduino/cores/openhardware/main.c
- webui/arduino/cores/openhardware/wiring.c
- webui/arduino/variants/xiao_esp32c3/oh_board.h
- webui/arduino/variants/xiao_esp32c3/link.ld
- webui/compile.py
- tests/webui/test_compile.py
- tests/webui/test_editor.py
---

From "find a way to make it possible" (2026-08-31). The Build button
stays greyed for nine runnable boards because their vendors' Arduino
cores cannot execute on the described models: ESP-IDF wants FreeRTOS and
a mask ROM, mbed wants its scheduler, and a Build whose output does not
run is the false affordance OH-140 killed.

The way that IS possible is the one this repository already uses for
meshes nobody publishes: **write the thing, cite every number, and say
what it is on the page.** `webui/arduino/` becomes a framework the
compile service can name — an Arduino-compatible core whose entire API
surface is exactly what the board descriptions model, compiled bare-metal
the way the blink fixtures are. The vendor still supplies what a vendor
honestly can: the XIAO's own `pins_arduino.h` (freestanding constants,
`#include <stdint.h>` and nothing else) rides in from
`framework-arduinoespressif32` through `extra_includes`, so `D10` means
what Seeed says it means without a transcription to drift.

Vertical slice first, per the house build order: the ESP32-C3
end-to-end, which flips `buildable` for three boards. The C6/C5 and the
RP2040 widen it in their own tickets.

The layout and signatures:

    webui/arduino/                          framework="openhardware"
      cores/openhardware/
        Arduino.h      HIGH/LOW/OUTPUT/INPUT; setup(); loop();
                       void pinMode(uint8_t pin, uint8_t mode);
                       void digitalWrite(uint8_t pin, uint8_t value);
                       void delay(unsigned long ms);
        main.c         _start (naked, stack from OH_STACK_TOP) -> setup(),
                       then loop() forever
        wiring.c       pinMode/digitalWrite via the W1TS/W1TC aliases the
                       description maps; delay as a counted busy loop
      variants/xiao_esp32c3/
        oh_board.h     OH_GPIO_*_W1TS/W1TC, OH_STACK_TOP,
                       OH_DELAY_LOOPS_PER_MS — every address equal to
                       webui/boards/esp32c3.py's constants, asserted by a
                       test that parses this header
        link.ld        irom at the C3's own flash window; .bss NOLOAD into
                       dram, which the model zero-fills

What the core deliberately does NOT have is the point:

  * no digitalRead — the description leaves GPIO_IN unmapped on purpose,
    and the API surface equals the model. A `hints` row explains at the
    exact moment gcc says "undefined reference".
  * no millis, no Serial, no interrupts — nothing models a timer or a
    UART on this board; each absence gets its hint.
  * no clock claim. The model configures no PLL and has no cycle time,
    so OH_DELAY_LOOPS_PER_MS is a JUDGEMENT and says so: calibrated so a
    C3 millisecond costs about what the AVR's real timer-driven
    millisecond costs in emulator steps, so the two families blink at
    comparable page speeds.
  * .data links into the flash window uncopied, because there is no crt0
    and this model's flash region accepts stores — a stated liberty of
    the model, not a claim about XIP hardware.

DONE WHEN `compile.build("XIAO-ESP32-C3-DIP", sketch)` returns ok for a
sketch that names the vendor's `D10`; the built image, loaded at the
recipe's base by board name, is WATCHED toggling GPIO10 with a steady
period on the emulated board; a delay-bearing sketch's period scales
with the argument; the oh_board.h addresses are asserted equal to
`webui/boards/esp32c3.py`'s; `buildable` flips true for all three C3
boards; and the hints for digitalRead, millis and Serial each name the
model decision they stand on.

---

**CLOSED 2026-08-31.** Everything the DONE WHEN names, measured:

  * The 132-byte first build EXECUTES: loaded by board name at the C3's
    flash window, the sketch enables GPIO10 -- the vendor's own D10,
    straight from Seeed's `pins_arduino.h` on the include path -- and
    toggles it, HIGH at step 31, the HIGH/LOW pair 12 steps apart.
  * delay(1) measured at ~24,000 steps (the volatile spin is six
    instructions at this toolchain's -Os, and `oh_board.h`'s judgement
    comment carries the measurement); the delay-scaling test holds
    delay(3)/delay(1) between 2.5 and 3.5 and the period exactly steady.
  * Every absence hints its modelling decision at gcc's own error:
    digitalRead names the unmapped-GPIO_IN choice, Serial the absent
    UART, millis/micros the absent timer, analogWrite/analogRead/
    attachInterrupt the peripherals nothing maps.
  * `oh_board.h` and `link.ld` are held equal to
    `webui/boards/esp32c3.py`'s constants by a parsing test, so the two
    spellings of one register cannot drift.
  * `buildable` flips true for all three C3 boards through the existing
    `chip in RECIPES` rail; the no-recipe refusal test moved its example
    board to the RP2040 -- its own docstring notes that a chip gaining a
    row moves the example, which is the property working.
  * Two mutations killed: OH_GPIO_OUT_W1TS aimed at W1TC (the drift test
    AND the watch test), and the delay loop counting to one (the scaling
    test).

The C6, C5 and RP2040 recipes are the widening -- variants of this
mechanism, not new mechanisms -- and are their own tickets.
