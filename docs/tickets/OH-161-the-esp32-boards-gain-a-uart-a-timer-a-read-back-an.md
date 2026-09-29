---
id: OH-161
title: The ESP32 boards gain a UART, a timer, a read-back, an ADC and one bus part,
  so a sketch can print, time, read and talk
status: open
priority: P1
created: '2026-09-04'
touches:
- webui/arduino/**
- core/riscv32/**
- tests/riscv32/**
- webui/boards/esp32c3.py
- webui/boards/esp32c5.py
- webui/boards/esp32c6.py
- tests/webui/test_board_run.py
- core/cortexm0/abi.py
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

**Note 2026-09-04:** STEP 1 ONLY, and the ticket stays open for steps 2-5. A sketch on any of the three ESP32 boards can now print, and the bytes reach the console pane; the timer, GPIO_IN, the ADC and the I2C part are untouched, and their hints still stand with their reasons.



WHAT STEP 1 NEEDED THAT THE TICKET DID NOT SAY: a third mapping behaviour in core/riscv32. A transmit FIFO is a queue, and a `map_register` at it keeps the last byte -- so a program printing `hello` would leave an `o` behind, which reads as a plausible letter rather than as a wrong answer. `core/cortexm0` grew `map_stream` for the RP2040's PL011 and `core/riscv32/cpu.h` said in its own comment that the other three behaviours "arrive when an image here faults without them"; this is the first of them arriving on exactly that trigger, and the comment now records it. cpu.h, cpu.cc, abi.h, abi.cc and abi.py mirror the cortexm0 shapes so a board module reads the same either side. One rule the cortexm0 version does not have: a store that does not carry byte 0 transmits NOTHING, because every one of these parts documents the FIFO's data field as `[7:0]` -- taking the low byte of a store to a reserved lane would append a zero the part never sent. That rule is only reachable from executed code, so its test runs an `sb` to FIFO+1 and asserts the output is `H!` and not `HI!`.



THE THREE BOARDS, each citing its own header and none importing a neighbour's constants. UART0 is 0x60000000 on all three. The C3's FIFO and gate come from framework-arduinoespressif32's uart_reg.h (:22 the FIFO, :1160 UART_CLK_CONF at +0x78, :1181 UART_TX_SCLK_EN at BIT(24), `default: 1'b1`) and the C5's and C6's from the esp-idf-reference tree (:17, :1548 and :1477 at +0x88, :1554 and :1481). **The offset differs and the bit does not**, which is the same trap the GPIO block already carries. A test asserts that a correctly installed C5 leaves +0x78 unmapped -- and that is all it can assert: a board copied from a C3 would `map_register` its own gate address, so it would map +0x78 itself, run silently wrong, and fail later when firmware touched the real +0x88. UART_CLK_CONF_AT_RESET is composed from every field default the header states, not from the one bit this model reads: 0x03701000 on the C3 (SCLK_SEL 3, SCLK_DIV_NUM 1, SCLK_EN, RX and TX_SCLK_EN) and (1<<24)|(1<<25) on the C5 and C6, whose divider fields moved to the PCR block -- so firmware reading the register back gets what the part gives it. Each module publishes uart0_output, the name webui/api.py already finds by getattr, so the console pane needed no change at all: measured, 18 bytes through `session.state()["uart"]` on each of the three boards.



WHAT IS DELIBERATELY NOT MODELLED, and it is unmapped rather than hinted: the receive half, the baud divisors, and UART_TXFIFO_CNT in UART_STATUS_REG (+0x1c). Firmware that waits for room in the FIFO faults at a named address instead of spinning on a zero that never changes, which is the failure mode `docs/research/peripheral-layer/design.md` states and `core/cortexm0/cpu.h:246-249` cites; a test asserts that fault. Nothing here has a wire or a bit rate, so bytes appear in the console the instant they are written, at every baud rate -- the same fidelity gap rp2040.py's UARTFR records, and what it cannot show is backpressure.



THE ARDUINO SIDE. webui/arduino/cores/openhardware/serial.cpp and an OhSerial class in Arduino.h: begin, end, write, print and println over char*, char, int, long and their unsigned forms. Not Arduino's HardwareSerial, which inherits Print and Stream and brings String, virtual dispatch and a receive path this model has nowhere to put. Integers are formatted by hand because -nostdlib has no itoa; the negative path negates as unsigned so LONG_MIN cannot overflow on the way. No read, available or peek: a read answering zero would be a wrong value, so it is a missing symbol at the moment gcc says so, and a test holds that. begin ignores the baud rate and the file says why. Each variant's oh_board.h gained OH_UART_FIFO, OH_UART_CLK_CONF and OH_UART_TX_SCLK_EN, held equal to the description's constants by the header test that already does this for GPIO -- the gate is written as a hex literal rather than `(1u << 24)` because that test's parser takes one whitespace-separated token and read `(1u`, so a shift would have compared nothing.



WATCHED, which is what rules/board-claims.md requires: a compiled sketch printing a string, a negative number, a char and an unsigned reaches the console byte for byte on all three boards -- `hello\r\nn=-42\r\nx7\r\n`, identical on each. A sketch that never calls begin still prints, because the vendor sets the gate at reset and this model must not require what the silicon does not. A sketch that calls end goes quiet, and one that calls begin afterwards prints again.



TWENTY-FOUR MUTATIONS, each failing the test named for it, and THREE that proved nothing and were replaced or discarded. `if (false)` on the stream's gate lookup left an end iterator to dereference, so the process crashed and pytest printed no summary -- a crash is not a test catching anything. Clearing the gate at the top of begin() changed nothing because the next line set it again; that survivor is why test_begin_reopens_a_port_that_end_closed exists, and it is the only test that can see what begin does at all. The third was mine on the formatter: negating LONG_MIN a different correct way is not a defect, so it proved nothing; dropping the negation altogether fails both print tests.



THREE PRE-EXISTING TESTS CHANGED, each because the model changed under them and not to make anything pass. test_an_undescribed_peripheral_faults_rather_than_reading_zero used UART0 as its undescribed example on the C3 and the C6; both now name a block that really is undescribed -- RTC_CNTL (soc.h:48) and PCR (reg_base.h:53) -- and the C3's cited address was never UART0 in the first place, which is recorded there. test_each_absence_hints_the_model_decision_it_stands_on asserted that a Serial sketch FAILS to build; it now asserts it builds, with analogRead taking the place of the absent example, because a test holding the model to a gap it no longer has is a test of the past.



REVIEWED, TWELVE FINDINGS, and the first is the one that matters. This file's own comment claimed UART0 "is the one a XIAO's USB bridge is wired to and the one a `Serial.print` reaches", and the repository had recorded the opposite twice before I wrote it: `docs/research/peripheral-layer/esp32c3/uart-contract.json` (verified 2026-08-24) says the XIAO ESP32-C3 has NO UART-to-USB bridge and that Arduino's `Serial` lands on USB_SERIAL_JTAG at 0x60043000, and Seeed's own `XIAO_ESP32C3_Pin_Multiplexing.md:112-126` says USB serial is the default and UART0 needs `D6`/`D7` wired to a USB-serial adapter with USB CDC On Boot disabled. The decision to model UART0 survives on the reasons that research file actually gives -- it is the ROM console and the target of `esp_rom_printf`, and non-XIAO C3 devkits do bridge it -- and all three modules plus serial.cpp now say that, and say that a sketch printing here models the vendor's documented alternative wiring. 0x60043000 is unmapped, so a program reaching for the default path faults at a named address.



One finding was a live code defect: the stream's write path read the gate's word straight off its `Mapped` entry, ignoring `target`, so a gate mapped as a readable ALIAS answered its own zero and the peripheral read right while transmitting nothing. No board here aliases a clock register, so nothing was wrong on the three described parts; it now reads through `mmio_read` like everything else, with two tests and a mutation.



The other ten were false or unsourced claims, every one of them mine: four line numbers taken from the ESP-IDF tree while naming the framework tree (the modules had them right, the test did not); a miscount of `core/cortexm0`'s behaviours as five when it declares six, which also dropped `map_counter` -- the one step 2 will want; a docstring in BOTH cores' `abi.py` claiming a truncation check the code does not perform; a document section citation pointing at Arm Cortex-M for a failure mode stated in `docs/research/peripheral-layer/design.md`; a comment saying 25 of 26 boards model no UART, which was 23 before this ticket and is 16 after; two stated measurements that were guesses (the sketch prints 18 bytes not 22, its largest inter-byte gap is 29 steps not "a few hundred", and that guess was the stated justification for `STALL_STEPS`); a causal story that does not happen (a board copied from the C3 would MAP +0x78 itself and run silently wrong, not fault); a line range excluding one of the ten fields it summed; and the watched test asserting one layer below the pane the ticket names.



That last one is now through `session.state()["uart"]`, which is the precedent `tests/webui/test_board_run.py:936` set for the RP2040 in its own words -- "because the browser has no other way to reach it" -- so the `getattr` seam all three module docstrings claim, the byte cap and the decode are all exercised. Mutating `uart_view`'s byte count fails it.



Two gaps closed that the review found without a defect behind them: the integer formatter was tested at two values, so its bounds are now their own test (LONG_MIN, ULONG_MAX, both zeros, LONG_MAX, -1, all measured on the C3), and `LONG_MIN` cannot be written as a literal in a sketch at all -- it does not fit a 32-bit `long`, so C++ types it `long long` and the call is ambiguous -- which serial.cpp now records beside the negation.



AUDITED AS A CLASS, not as instances: all 16 file-and-line citations this change adds were re-read against the files they name and every one checks out, and two claims that were true but unsourced now carry citations -- the divider fields at `pcr_reg.h:58` and `:51`, and Arduino's CR LF at both vendor cores' `Print.cpp`.



SCOPE, measured by the reviewer rather than asserted here: step 1 did not do part of a later step. Every `map_*` line added is one `map_register` and one `map_stream` per board; GPIO_IN, SYSTIMER (0x60023000), the SAR ADC (0x60040000) and I2C (0x60013000) are all still unmapped; every hint but `Serial`'s still stands; and `delay` is untouched, so it is still the counted loop step 2 exists to replace.



Gate: all 12 checks pass, run clean with nothing else building or editing (three earlier runs were green over a tree that was still changing under them, which proves less than it looks). Build note carried from US-1: build/lib/riscv32.dll was locked by the user's own webui/emulator_server.py (pid 44724, running since 2026-08-31), so the file was renamed aside rather than that process killed; build/lib/riscv32.dll.locked-by-pid44724 is left for it to release and is git-ignored.

**Note 2026-09-29:** 2026-09-29: webui/compile.py and tests/webui/test_compile.py lent to OH-176 and then OH-179, nobody holding this ticket. OH-176's review found recipe_for builds the SparkFun Thing Plus ESP32-C6 against the XIAO ESP32-C6 variant, because it keys on chip; the gate that refuses that, and OH-179's per-board recipe that replaces the gate, both live in recipe_for. Add both paths back with tickets set OH-161 --touch when OH-179 closes.

**Note 2026-09-29:** 2026-09-29, held for one line by the OH-174 orchestrator: test_an_unknown_board_says_what_there_is asserted the literal 'XIAO' in runtime_for's refusal, which lists the first three sorted board names. OH-177's 'Adafruit QT Py ESP32-C3' sorts first, so the test failed on sort order, not on the refusal. It now asserts the first sorted catalogue board name appears. Made to fail once with a name no board has.

**Note 2026-09-29:** Correction to the note above: at a3cac44 the first sorted board is 'Adafruit Feather ESP32-C6', not the QT Py. The test computes the name, so it is unaffected.

**Note 2026-09-29:** 2026-09-29 from OH-179: (1) webui/compile.py and tests/webui/test_compile.py are unclaimed while OH-183 finishes buildability work in compile.py; add both back to this ticket when OH-183 closes. (2) The Adafruit Feather ESP32-C6 now builds with -I webui/arduino/variants/xiao_esp32c6 for its chip-level files (link script, oh_board.h, soc/soc_caps.h), not for pins; soc_caps.h's comment speaks only of Seeed's table. Consider naming that folder for the chip. (3) The SparkFun Thing Plus ESP32-C6 and Adafruit QT Py ESP32-C3 are refused a build because their own pins_arduino.h use SOC_GPIO_PIN_COUNT, which nothing here defines, and the QT Py's includes soc/soc_caps.h, absent from the C3 build's include path. Both live in webui/arduino/**, this ticket's.
