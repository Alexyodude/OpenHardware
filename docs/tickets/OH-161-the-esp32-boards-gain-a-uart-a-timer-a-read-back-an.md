---
id: OH-161
title: The ESP32 boards gain a UART, a timer, a read-back, an ADC and one bus part,
  so a sketch can print, time, read and talk
status: open
priority: P1
created: '2026-09-04'
touches:
- webui/arduino/**
- webui/compile.py
- tests/webui/test_compile.py
---

A sketch on an ESP32 board here can set a pin high and wait; it cannot print, time, read a pin, or talk to anything. That is the whole API, and it is honest about it -- every absence carries a hint naming the modelling decision (OH-138) -- but the decisions are now the gap.

Measured 2026-09-04:

    webui/arduino/cores/openhardware/Arduino.h     pinMode, digitalWrite, delay. Nothing else.
    webui/compile.py hints                         millis, micros, Serial, analogWrite,
                                                   analogRead, attachInterrupt, digitalRead
                                                   are each refused with a reason.
    webui/boards/esp32c3.py / esp32c5.py / esp32c6.py   8 map calls each: GPIO OUT and
                                                   ENABLE with their W1TS/W1TC aliases. No
                                                   UART, no timer, no ADC, GPIO_IN unmapped
                                                   on purpose (its comment says why).
    webui/boards/rp2040.py                         22 map calls, UART0 among them.
    webui/boards/samd21.py                         30 map calls, the peripherals a real
                                                   Arduino image asks for before setup.
    bench parts (import_3d_model.PARTS)            three LEDs, one axial resistor, one
                                                   buzzer, one trimmer. circuit.js solves
                                                   resistor / diode / source / current
                                                   elements by nodal analysis.

What the two products the user pointed at do here, read from their pages 2026-09-04, so the gap is stated against something concrete rather than a wish:

  * sim86.com (Simulator86): per board, a support table per peripheral. For its XIAO ESP32-C3: GPIO, UART (uart0/uart1), I2C master and slave "validated against real hardware", SPI register behaviour modelled but external transfers "not bridged yet", Wi-Fi at packet level, systimer driving the FreeRTOS tick, "all 31" interrupt-matrix sources, flash with QIO. Parts: MCP9808, BMP280, MPU-6050, MMA8451Q, SSD1306, LCD1602, APA102, RGB LED, 7-segment, SG90, buzzer, button. It runs unmodified vendor firmware (ELF, or a merged .bin for the C3) -- so its bar is "the real ESP-IDF image boots", which this repository chose NOT to meet (Arduino.h's header: the vendor core needs FreeRTOS and a mask ROM nothing here models).
  * Xplora3D (xplora.phinalabs.com/3d): an education breadboard with a generic "programmable MCU with GPIO", sensors (LDR, temperature, ultrasonic, PIR, DHT11, gas), displays (OLED, LCD, LED matrix, 7-segment), motors and servos, logic ICs, op-amps, a 555, shift registers, a scope and a logic analyser, and an "Environment" panel (light, temperature, humidity) that sensors read. Its MCU is not a named chip; its value is the part library and the environment.

This repository's rule (rules/board-claims.md, rules/conformance-fixtures.md) is stricter than either: a peripheral exists when a cited register map is modelled and a named test watched an image use it. So the order below is by what is CITABLE today, not by what looks best:

1. UART TX on the three ESP32 boards. ESP-IDF's uart_reg.h is in the same headers esp32c6.py already cites line by line; the console pane already shows a modelled UART's bytes (the "Show a board's UART output" ticket, done, for the boards that map one). Then Serial.print in the openhardware core, and the Serial hint retires. Watched test: a sketch's bytes arrive in the pane.
2. One timer per ESP32 part -- the systimer, which is what ESP-IDF itself uses for the tick -- so millis()/micros() are a register read and delay() stops being a counted loop whose cost is a judgement (each variant's oh_board.h says so today).
3. GPIO_IN with an electrical model, not a stored zero: the description's own comment says why IN cannot be a register that reads back OUT; digitalRead needs the bench's solved node voltage (circuit.js already computes it for the Uno's pins). That closes the loop a button needs.
4. ADC on the C3/C5/C6 (adc_reg.h) reading the same solved voltage -- then a potentiometer on the bench means something.
5. The first bus part: an I2C master (i2c_reg.h) and ONE device on the bench with a public datasheet register map -- SSD1306 or MCP9808, both of which sim86 also chose. A display is the more visible; a temperature sensor is the smaller model. Decide by which datasheet is fully citable.

Each step lands only with: the header lines cited, a board module test, a compile test that builds a sketch using the API and watches the effect (OH-148's shape), and the corresponding hint removed from compile.py. Nothing is claimed for the Xtensa or Cortex-M33 boards, which have no core.

NOT this ticket: Wi-Fi, USB, interrupts (the core executes straight-line code), or running a vendor image -- that is a different product decision, stated in Arduino.h, and this ticket does not reopen it.
