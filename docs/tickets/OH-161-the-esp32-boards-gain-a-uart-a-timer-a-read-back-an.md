---
id: OH-161
title: The ESP32 boards gain a UART, a timer, a read-back, an ADC and one bus part,
  so a sketch can print, time, read and talk
status: in-progress
priority: P1
created: '2026-09-04'
touches:
- webui/boards/esp32c3.py
- tests/webui/test_board_run.py
- core/cortexm0/abi.py
- webui/arduino/**
- webui/compile.py
- tests/webui/test_compile.py
- webui/boards/esp32c5.py
- webui/boards/esp32c6.py
- core/riscv32/**
- tests/riscv32/**
- tests/webui/test_feather_esp32c6_board.py
- tests/webui/feather_esp32c6/blink.bin
- tests/webui/feather_esp32c6/blink.ino
- tests/webui/test_olimex_esp32c3_devkit_lipo_board.py
- tests/webui/olimex_esp32c3_devkit_lipo/lipo_blink.bin
- tests/webui/olimex_esp32c3_devkit_lipo/lipo_blink.ino
- tests/webui/test_olimex_esp32c6_evb_board.py
- tests/webui/olimex_esp32c6_evb/evb_blink.bin
- tests/webui/olimex_esp32c6_evb/evb_blink.ino
- tests/webui/test_pcbcupid_glyph_c3_board.py
- tests/webui/pcbcupid_glyph_c3/glyph_c3_blink.bin
- tests/webui/pcbcupid_glyph_c3/glyph_c3_blink.ino
- tests/webui/test_pcbcupid_glyph_c6_board.py
- tests/webui/pcbcupid_glyph_c6/glyph_c6_blink.bin
- tests/webui/pcbcupid_glyph_c6/glyph_c6_blink.ino
- tests/webui/test_qtpy_esp32c3_board.py
- tests/webui/qtpy_esp32c3/qtpy_blink.bin
- tests/webui/qtpy_esp32c3/qtpy_blink.ino
- tests/webui/test_sparkfun_esp32c5_board.py
- tests/webui/sparkfun_esp32c5/sparkfun_c5_blink.bin
- tests/webui/sparkfun_esp32c5/sparkfun_c5_blink.ino
- tests/webui/test_sparkfun_esp32c6_board.py
- tests/webui/sparkfun_esp32c6/sparkfun_blink.bin
- tests/webui/sparkfun_esp32c6/sparkfun_blink.ino
- tests/webui/test_sparkfun_pro_micro_esp32c3_board.py
- tests/webui/sparkfun_pro_micro_esp32c3/promicro_blink.bin
- tests/webui/sparkfun_pro_micro_esp32c3/promicro_blink.ino
- tests/webui/test_sparkfun_qwiic_pocket_esp32c6_board.py
- tests/webui/sparkfun_qwiic_pocket_esp32c6/pocket_blink.bin
- tests/webui/sparkfun_qwiic_pocket_esp32c6/pocket_blink.ino
- tests/webui/esp32_timing.py
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

**Note 2026-09-29:** 2026-09-29: webui/compile.py and tests/webui/test_compile.py returned to this ticket; OH-179 and OH-183 are done.

**Note 2026-09-29:** 2026-09-29: webui/arduino/** lent to OH-185 (SOC_GPIO_PIN_COUNT and a C3 soc/soc_caps.h, read from the ESP-IDF v5.5 reference, so the SparkFun Thing Plus ESP32-C6 and QT Py ESP32-C3 build against their own variants). Add it back with tickets set OH-161 --touch when OH-185 closes.

**Note 2026-09-29:** 2026-09-29: webui/compile.py and tests/webui/test_compile.py lent again, to OH-185: its SoC definitions make the SparkFun Thing Plus ESP32-C6 and QT Py ESP32-C3 build, so the tests asserting their refusals and the ESP32-C6 recipe comment about an empty soc_caps.h change. Add both back with the webui/arduino/** loan when OH-185 closes.

**Note 2026-09-30:** 2026-09-30: webui/arduino/**, webui/compile.py and tests/webui/test_compile.py returned to this ticket; OH-185 is done. What it changed on these paths: SOC_GPIO_PIN_COUNT for the C3, C5 and C6 read from ESP-IDF v5.5 with citations; per-chip OH_GPIO_PIN_COUNT in each ESP32 oh_board.h; mask_of writes no bit at or past it; inline pinMode/digitalWrite refuse a compile-time out-of-range pin; a hint for LED_BUILTIN on RGB boards. Left, LOW, from its review: the editor's clickable-diagnostic regex (webui/static/emulator.js ~711, ^sketch\.cpp:) misses the 'inlined from ... at sketch.cpp:L:C' location that pin refusal prints.

**Note 2026-10-08:** 2026-10-08, 68a7fbe, committed under this ticket because tests/riscv32/** is its: test_the_chip_is_described_and_the_watching_is_named in tests/riscv32/test_esp32c5_board.py asserted two boards on the ESP32-C5. OH-194 adds a third, the SparkFun Thing Plus ESP32-C5, a manifest row with its own run evidence. The test now names the two XIAOs (boards board_manifest.find does not know) and still holds every C5 board, the row included, to described, runnable and firmware_verified. Seen red with a third name added to the expected list.

**Note 2026-10-08:** 2026-10-08: webui/boards/esp32c5.py and webui/boards/esp32c6.py lent to OH-200, whose XIAO C5 and C6 SMD back pads change the generated HEADER blocks in both (OH-170 left them for this ticket's release). Return both here when OH-200 closes.

**Note 2026-10-08:** 2026-10-08: webui/boards/esp32c5.py and esp32c6.py return here; OH-200 is done (merged at 90eed1f). Their HEADER blocks now carry the SMD boards' MTMS, MTDI, MTDO, MTCK and BOOT rows, read from Seeed's board files.

**Note 2026-10-08:** 2026-10-08: test_each_refusal_arrives_as_itself (tests/webui/test_board_run.py) now uses XIAO-MG24-DIP, not XIAO-RP2350-DIP, as its board whose core is not built: OH-157 runs the RP2350 on its Hazard3 half through core/riscv32, which is built. The MG24 is on cortexm33, which is not (OH-36).

**Note 2026-10-09:** 2026-10-09: core/riscv32/** and tests/riscv32/** lent to OH-208 (Zbb and Zbkb on the RP2350's Hazard3, under lockstep with rvcpp). Return both when OH-208 closes.

**Note 2026-10-09:** 2026-10-09: core/riscv32/** and tests/riscv32/** return from OH-208 (done, d6a8b9c): the core now executes RV32 Zbb and Zbkb, gated per part; only the RP2350 enables them.

**Note 2026-10-09:** STEP 2 ONLY, and NOT ALL OF IT: steps 3-5 remain, and so does moving delay(), which is blocked on files this ticket does not claim. A sketch on any of the three ESP32 boards can now read the time -- millis() and micros() read SYSTIMER's unit 0 -- and their two hints are gone from compile.py. delay() is still the counted loop.



THE MECHANISM (eab655c). core/riscv32 gained `map_snapshot_counter`, the fourth of cortexm0's six behaviours and not in cortexm0's shape: an ESP32's SYSTIMER is read by writing UPDATE, spinning on VALUE_VALID and reading two registers that hold a COPY taken at the write, so cortexm0's live `map_counter` would answer the right number at the wrong moment. The unit counts once per `instructions_per_tick` retired instructions while its enable bit is set and holds its count while it is clear; `step()` calls `note_executed` only on Ok, in exec.cc rather than abi.cc, so a C++ caller ages the machine the way the ABI does. A snapshot through an unmapped enable register faults naming the unit. ABI version 3 (step 1's stream entry points arrived without a bump and are counted in this one). rvcpp models no peripheral at these addresses, so the counter is held by the header lines the boards cite and by the tests, not by an oracle; lockstep is unaffected, since a counter changes no architectural register.



THE BOARDS (7e8e301), one slice for all three because the block is one shape. CONF (+0x0), UNIT0_OP (+0x4: UPDATE bit 30, VALUE_VALID bit 29), VALUE_HI (+0x40, [19:0]) and VALUE_LO (+0x44); WORK_EN is CONF bit 30, default 1, so the unit counts out of reset. Base 0x60023000 on the C3 (framework-arduinoespressif32 soc.h:61; systimer_reg.h :26, :108, :344, :356) and 0x6000A000 on the C5 and C6 (v5.5 reg_base.h:23; C5 systimer_reg.h :17, :121, :370, :382; C6 :17, :106, :342, :354). CONF's reset word, 0x46000000 on all three, is composed from every field default the header states, and a test per part recomposes it from the header's own field comments. Unmapped on purpose: the LOAD registers, unit 1, the comparators and their interrupts. Unit 0 is the counter esp_timer reads (v5.5 esp_private/systimer.h:30, SYSTIMER_COUNTER_ESPTIMER 0), which is what arduino-esp32's own millis() and micros() return (cores/esp32/esp32-hal-misc.c:204-210 @ 2787dab). The ticket's handover said unit 0 is also "the one ESP-IDF's tick reads"; it is not -- the OS tick counts on unit 1 (:31) with alarm 0 -- and the modules say so.



THE RATE. SYSTIMER counts at 16 MHz: the C3's own tree states it as a value (soc_caps.h:250, SOC_SYSTIMER_FIXED_TICKS_US (16)); the C6's is XTAL_CLK_FREQ 40 MHz (soc.h:145) over the fixed 2.5 (soc_caps.h:446); and the C5's is a SENTENCE, components/esp_hw_support/port/esp32c5/systimer.c:12-13 at 8c750b0, because the C5's soc_caps.h:493 still says 2.5 and the XIAO ESP32-C5 carries a 48 MHz crystal (Seeed's board file, X1, line 7943), so the C6's sum would give 19.2 MHz. systimer.c is outside the sparse checkout docs/esp-idf-reference.md describes, so no test reads it; test_the_c5_divider_comment_would_time_this_board_wrongly holds the two facts that make the comment the wrong source. Adding components/esp_hw_support/port/<chip>/systimer.c to that sparse set (docs/esp-idf-reference.md, not this ticket's) would let a test read the statement itself. The instruction-to-time step is a JUDGEMENT, the one rp2040.py's TIMER made: one retired instruction stands for one cycle at the board's own Arduino clock, boards.txt build.f_cpu -- 160 MHz on every C3 and C6 row (XIAO_ESP32C3 :37756, XIAO_ESP32C6 :38098) and 240 MHz on the C5s (:37911). Ten instructions a tick, fifteen on a C5: a millisecond is 160,000 steps on a C3 or C6 and 240,000 on a C5. A test per part holds every manifest row's f_cpu to the module's CPU_HZ.



THE ARDUINO SIDE. wiring.c reads unit 0 the way systimer_hal.c:46-62 does, less the second LO read only an interrupt needs. micros() is a shift (sixteen ticks a microsecond); millis() divides in two 32-bit halves because a -nostdlib image has no __udivdi3. Both wrap at 2^32 as Arduino's do. Each variant's oh_board.h gained OH_SYSTIMER_* constants, held to the description's by the header test.



WATCHED, per board, the OH-148 way: a sketch compiled for the board by name, toggling D10 once a millisecond by millis(), moves it every 159,998 steps on the C3 and C6 and 240,008 / 239,973 on the C5 (measured 2026-10-09), first toggle one millisecond after install; by micros() every hundred microseconds, 16,005 / 15,979 and 24,013 / 23,987. The tests assert each period within 100 steps (three poll loops) of the description's own rate. millis() and micros() at counts stepping cannot reach (one tick under a millisecond, 2^32 us and over, a remainder carried between the halves, the 52-bit top) are checked on the C3 with its SYSTIMER replaced by one holding a chosen count. The committed sketch images all still rebuild byte for byte: with --gc-sections an image that does not call millis() carries none of it.



MUTATIONS: twenty-nine, each failing the test named for it -- twelve in the core, ten in the board modules (a base, a reset word, a bit, a clock, the C5 taking the 19.2 MHz sum, the gate on a stall bit, CONF unmapped, one instruction a tick, a LOAD register mapped, the C3 at 8 MHz), seven on the Arduino side. ONE SURVIVOR, recorded rather than hidden: deleting the VALUE_VALID spin from wiring.c passes everything, because the model takes the copy at the write; on silicon the halves take a few clock edges. The high half's 20-bit mask is applied and not exercised by any test, since no test can step 2^32 ticks and no LOAD register is modelled.



TWO PRE-EXISTING TESTS CHANGED, because the model changed under them: test_each_absence_hints_its_own_variant_header reached for millis() as its absence and now reaches for a pin past the GPIO count, the other hint that names the header; test_the_serial_hint_is_gone_where_the_uart_is_modelled asserted the millis hint still stood.



DELAY() IS NOT MOVED, AND WHY. Measured with it moved (delay waiting ms*16,000 ticks; reverted): a HIGH/delay(1)/LOW/delay(1) blink's period becomes 320,102 steps on the C3 and C6 and 480,089 on the C5, against ~48,000 today. That changes the bytes of every committed ESP32 sketch image, and 22 tests fail: the ten `test_the_image_is_this_sketch_built_for_this_board_against_its_own_variant` in tests/webui/test_{feather_esp32c6,olimex_esp32c3_devkit_lipo,olimex_esp32c6_evb,pcbcupid_glyph_c3,pcbcupid_glyph_c6,qtpy_esp32c3,sparkfun_esp32c5,sparkfun_esp32c6,sparkfun_pro_micro_esp32c3,sparkfun_qwiic_pocket_esp32c6}_board.py; the Feather's stock-blink test on its BUDGET; eight delay-budgeted test items in tests/webui/test_compile.py and one in tests/riscv32/test_esp32c3_board.py (both this ticket's); and two in tests/webui/test_board3d.py that fail without the change too. To land it: lend this ticket those ten board test files and their ten images under tests/webui/<board>/ -- the images rebuilt with webui.compile.build, each file's BUDGET raised and its "~24,000 steps a millisecond" comment replaced -- then move delay() and retire OH_DELAY_LOOPS_PER_MS. Until then a delay(1) is ~24,000 steps and a millisecond of millis() is 160,000 (240,000 on a C5), so a sketch timing one with the other reads about 0.15 of what it asked for, and the variant headers say so. In the browser a delay(500) on the moved delay() would be 80,000,000 instructions, about 30 s at the ~2.6 M steps/s clock.js measured: the cited clock's cost, as the SAMD21's 48 MHz already is.

**Note 2026-10-09:** REVIEW OF STEP 2, AND ITS FIX ROUND. An independent review of eab655c, 7e8e301 and 4712021 said MERGE AFTER FIXES, with eight findings. Seven are fixed, the code in da66359 and finding 1 in this note; finding 4 is left, and why is below.

FINDING 1, CORRECTED HERE: the step-2 note above, which stays as written, says a sketch timing a delay() with millis() "reads about 0.15 of what it asked for" as if every board did. That holds on the C3 and the C6, where a delay(1) is ~24,000 steps and a millisecond of millis() is 160,000. On the C5 the delay(1) is the same ~24,000 steps (its oh_board.h measured a HIGH/LOW/delay(1) sketch's rises 24,043 steps apart) and the millisecond is 240,000, so it reads about 0.10. The variant headers were right: the C3's states 0.15 of its own part, and the C5's and C6's give their two step counts and no ratio.

FINDING 3, FIXED: UPDATE checked the enable register with is_mapped while counting read it with mmio_read. A gate mapped as a readable alias onto nothing is mapped and cannot be read, so UPDATE handed out copies of a count that never moved, nothing faulted, and note_executed's failed read rewrote the fault record after every retired instruction. UPDATE now reads the gate through mmio_read and faults naming UNIT0_OP; note_executed puts the record back as it found it; cpu.h's contract now says "cannot be read -- unmapped, or a readable alias onto nothing". Held by test_a_snapshot_through_an_alias_gate_onto_nothing_faults_naming_the_unit and test_a_gate_that_cannot_be_read_leaves_no_fault_behind_between_instructions. With cpu.cc as at 4712021 both fail: DID NOT RAISE MemoryFault, and a record of 1610756096 (0x60023000, CONF) after forty NOPs. Each half reverted alone fails its own test and only it: UPDATE back on is_mapped fails the first, note_executed without the restore fails the second.

FINDING 5, FIXED: abi.py refuses an instructions_per_tick past 0xFFFFFFFF, naming the value; ctypes would pass 2**32 as 0, which the core turns into 1. Held by test_a_rate_past_32_bits_is_refused_with_the_value, which fails with the guard made `if False:` (DID NOT RAISE AbiError). The C++ correction of 0 to 1 in map_snapshot_counter stays: riscv32_map_snapshot_counter returns void, as every riscv32_map_* does, so a refusal the caller could see needs a return value -- a change to the C signature, which is an ABI change, and this round makes none. abi.py refuses both ends before the call.

FINDING 6, FIXED: test_mapping_the_same_unit_twice_replaces_it maps the unit at four instructions a tick (the fixture), again at eight, retires 40 and expects 5. With the remove_if in map_snapshot_counter deleted it fails, 10 == 5: the first counter answers.

FINDING 2, FIXED, step 2's one surviving mutant: test_millis_waits_for_value_valid_before_it_reads_the_copy builds `Serial.println(millis())` for the C3, maps UNIT0_OP as a plain register (UPDATE is stored, VALUE_VALID never reads back), VALUE_HI 0 and VALUE_LO 16,000 * 7, and runs HELD_BUDGET, 5,000 steps: nothing printed and still running. With wiring.c's two spin lines deleted it prints b'7\r\n' and fails.

FINDING 7, FIXED: HELD_COUNTS' comment said reaching those counts would take years of emulated time and put a count past 2^16 us among them. 2^16 us is 65.5 ms, 10,485,760 steps on a C3, so it is reachable; 2^32 us is about 71.6 minutes, 687,194,767,360 steps on a C3; only the 52-bit top, 2^48 us, is years, about 8.9. Comment only.

FINDING 8, FIXED: esp32c3.py, esp32c5.py and esp32c6.py each raise ValueError at import when CPU_HZ is not a multiple of SYSTIMER_HZ, with both values, since CPU_HZ // SYSTIMER_HZ floors without a word. Seen with CPU_HZ set to 170_000_000 in each in turn: "CPU_HZ 170000000 is not a multiple of SYSTIMER_HZ 16000000: SYSTIMER_INSTRUCTIONS_PER_TICK would be 10, rounded down from 10.625, and every tick would come early". wiring.c gains a _Static_assert that OH_SYSTIMER_TICKS_PER_US is a power of two, placed at micros(), whose comment already gives the reason. Seen with the C3 header's rate set to 3u: the build stops at wiring.c:64, "static assertion failed"; with the assert removed as well, the link fails with "undefined reference to `__udivdi3'" in .text.micros and .text.millis, the failure the message names. It emits no code: a sketch calling micros() and millis() built for the XIAO C3, C5 and C6 is 276 bytes on each, sha256 a34f3dc0, 105fef40 and 46d26a9d, with and without it.

FINDING 4, LEFT: once a snapshot counter is mapped, every retired instruction pays a hash lookup -- note_executed's mmio_read of the gate goes through mmio_.find -- which the review measured at about 4.5% on a Release core and 21% on the Debug build that build/ holds today. Those figures are the review's and were not re-measured here. Removing the lookup means caching where the gate's word lives, a cache every map_*, clear_mmio and clear_regions would then have to keep true: a design change with its own tests rather than a review fix, and the cost falls only on a board that maps a counter.

OUTSIDE THIS CHANGE: build/CMakeCache.txt says CMAKE_BUILD_TYPE:STRING=Debug in both the main worktree and lane2, so a timing taken from build/lib in either today is a Debug core's.

A TRAP MET WHILE MUTATING: a Python mutation that keeps the file's size and is restored within the same second leaves the mutated bytecode in __pycache__, because a .pyc is checked against the source's whole-second mtime and its size. After 160_000_000 was put back over 170_000_000 the module still raised until its .pyc was deleted. Delete __pycache__ after a same-size mutation.

VERIFIED at da66359, after python tools/build_core.py: tests/riscv32 and tests/webui/test_compile.py, 340 passed and 1 skipped (every_upstream_variants, which wants OH_SLOW=1); the ten ESP32 manifest board test files with tests/webui/test_board_run.py, 71 passed, so every committed ESP32 image still rebuilds byte for byte; check_ticket_claims OK (216 tickets against OH-161); check_banned_symbols OK (69 C/C++ files).

**Note 2026-10-09:** CONFIRM REVIEW OF THE FIX ROUND: confirmed for merge. It re-ran five of the breaks above, each failing its own test and no other, and found three LOWs, fixed here. (1) test_a_gate_that_cannot_be_read_leaves_no_fault_behind_between_instructions primed the record with an access fault at zero, which is also the reset value and what a mutant clearing the record instead of restoring it writes, so that mutant passed all 47; it now primes a fetch fault at 0x60023F00 and holds the address and the fetch flag both. Seen: the record cleared to 0/false fails it, and the fetch flag alone not put back fails it, each 1 failed, 46 passed; restored, 47 passed. (2) The note above says the review had eight findings and seven fixed. It had nine, one informational (finding 9: the HI mask unexercised, VALUE_VALID's write-to-clear unmodelled, both already disclosed); six were fixed in da66359; finding 1's 0.15 was corrected in that note, and the mismatch itself -- delay() and millis() on two scales -- stays open as the delay() work; finding 4 is left. (3) The three board modules' import-time refusal ended 'and every tick would come early', which is false below 16 MHz, where the count is 0 and abi.py refuses the board; the clause is gone and the two numbers say what is wrong.

**Note 2026-10-09:** STEP 2 MERGED to master by fast-forward at 1573738 (lane2): SYSTIMER unit 0 on the C3, C5 and C6, millis() and micros() reading it, the core's snapshot counter at ABI 3. REVIEW: an independent review (MERGE AFTER FIXES), its fix round (da66359, b3d6df8), and a confirm review (CONFIRMED FOR MERGE) whose three LOWs are 1573738. VERIFIED on master at 1573738, core rebuilt with tools/build_core.py: full suite 2 failed (the OCP pair, test_a_part_that_names_a_lens_it_has_lost_still_refuses_to_convert and test_the_tessellator_welds_what_it_meshes, under a python without OCP), 2650 passed, 41 skipped. NEXT, still step 2: delay(). The ten ESP32 manifest board tests and their images under tests/webui/<board>/ are claimed by no ticket (tickets.py owner says unclaimed for each), so this ticket takes them rather than borrowing them. Steps 3-5 remain.

**Note 2026-10-09:** Claimed for delay(): the ten ESP32 manifest board tests tests/webui/test_{feather_esp32c6,olimex_esp32c3_devkit_lipo,olimex_esp32c6_evb,pcbcupid_glyph_c3,pcbcupid_glyph_c6,qtpy_esp32c3,sparkfun_esp32c5,sparkfun_esp32c6,sparkfun_pro_micro_esp32c3,sparkfun_qwiic_pocket_esp32c6}_board.py and their sketch folders tests/webui/<board>/**, which no ticket claimed (tickets.py owner: unclaimed for each test file). Moving delay() onto the systimer changes every committed image's bytes and every BUDGET they run under.

**Note 2026-10-09:** STEP 2 IS DONE: delay() waits on SYSTIMER (57e2183). Steps 3-5 remain, and this ticket stays in-progress.

WHAT MOVED. wiring.c's delay(ms) returns once ms * 16,000 ticks of SYSTIMER unit 0 have passed since the call, read through the snapshot millis() reads. It waits a millisecond at a time in the count's low 32 bits, so the -nostdlib link needs no 64-bit multiply and no __udivdi3 or __umoddi3, and unsigned subtraction is right across the low word's wrap at 2^32 ticks and the counter's own at 2^52; `start` advances by whole milliseconds, so a late poll does not push the next one later. OH_DELAY_LOOPS_PER_MS is gone from xiao_esp32c3, c5 and c6's oh_board.h, and with it each header's text about delay() and millis() counting on two scales (the C3's "about 0.15"); Arduino.h's and compile.py's comments follow. Only those three variants build the openhardware core: the SAMD21 builds Seeed's core and the RP2040 has no recipe, so no other board's image or behaviour changed. delayMicroseconds is not declared in Arduino.h and compile.py has no hint for it; it is left so, a missing symbol at link time.

MEASURED 2026-10-09: on every committed board image a HIGH/delay(1)/LOW/delay(1) blink moves its pin at steps 38, 160,081, 320,130, 480,173 and 640,222 on the C3 and C6 boards and 38, 240,085, 480,126, 720,173 and 960,214 on the SparkFun C5; periods 320,092 and 480,088. delay() returns at the first twelve-instruction poll that sees its tick, so a later period is one poll longer: the fifth, 320,104, on every C3 and C6 image, and the third, 480,100, on the C5. These replace the step-2 note's 320,102 and 480,089, which were measured on a delay() that was reverted, not this one. test_compile's HIGH/LOW/delay(n) sketch rises every 160,061 and 480,061 steps on the C3 and C6, 720,061 at the C5's delay(3), and 240,053 and 240,065 by turns at its delay(1).

IMAGES REBUILT with webui.compile.build, each 206 -> 258 bytes, sha256 prefix old -> new: feather_esp32c6/blink.bin ef52fbc0 -> 4ea32c83; olimex_esp32c3_devkit_lipo/lipo_blink.bin f66382d8 -> a71cc92f; olimex_esp32c6_evb/evb_blink.bin 7b8ecc3c -> db894040; pcbcupid_glyph_c3/glyph_c3_blink.bin 678563d5 -> 8a5e4fe8; pcbcupid_glyph_c6/glyph_c6_blink.bin eb09d14e -> bc9a31c2; qtpy_esp32c3/qtpy_blink.bin 04dd8914 -> 938dafad; sparkfun_esp32c5/sparkfun_c5_blink.bin b789c3d6 -> c694c558; sparkfun_esp32c6/sparkfun_blink.bin b0be9351 -> b9c92cf3; sparkfun_pro_micro_esp32c3/promicro_blink.bin 7fc812a9 -> e9443c9b; sparkfun_qwiic_pocket_esp32c6/pocket_blink.bin 662dd0b1 -> e3e666b3. No other committed image comes from this core: tests/riscv32/c3blink, c5blink and c6blink are bare-metal blink.c, and the SAMD21, RP2040 and RP2350 images belong to other cores. No .ino changed.

BUDGETS, old -> new, each beside its measured steps: the ten board tests' BUDGET 110,000 -> 650,000 on the C3 and C6 boards and 970,000 on the C5, about 9,800 past the fifth change. tests/webui/test_compile.py: c3_transitions' default and the C5/C6 run test 60,000 -> FOUR_CHANGES, 250,000 (fourth change at 160,111 and 240,115); the globals and constructor tests 200,000 -> THREE_RISES, 650,000 (third rise at 640,234 and 640,264); the two scaling tests 200,000 -> two periods' milliseconds plus THIRD_RISE, 1,000 (the third rise lands 156 to 160 past). tests/riscv32/test_esp32c3_board.py SKETCH_BUDGET 80,000 -> 330,000 (second high at 320,130). Each "~24,000 steps a millisecond" comment is replaced by the measured figure and its cause.

TESTS CHANGED, because the model changed under them: test_delay_scales_with_its_argument_and_the_period_is_steady and test_the_c5_and_c6_delay_is_steady_and_scales hold every period to n of the description's milliseconds within POLL, counting the first rise, where they asked for one exact period: on the C5 the timer's period alternates, so `len(gaps) == 1` fails there. Their docstrings no longer cite OH_DELAY_LOOPS_PER_MS. The ten board tests keep `len(gaps) == 1`: over the window their budget watches both periods are equal, and each BUDGET comment says the later one is a poll longer.

NEW: test_a_delay_timed_by_millis_lasts_the_milliseconds_it_asked_for. delay(5) timed by millis() prints exactly 5 on the C3 and the C5, whose milliseconds are 160,000 and 240,000 steps. Not 5 or 6: t's copy is taken at tick 2 on the C3 and tick 1 on the C5 and the closing copy at tick 80,008 and 80,005, nearly a millisecond short of 96,000, where 6 begins. The last byte lands at step 800,145 and 1,200,141; the budget is five milliseconds and 1,000 steps.

BREAKS, each run and each restored (wiring.c's sha256 checked equal before committing): HEAD's counted loop and headers put back -> the new test fails, C3 printed b'0\r\n' (the C5 prints b'0\r\n' too, run alone); both scaling tests fail on the C3, C5 and C6 (rose 72,053 apart at delay(3)); all ten image tests fail, "not this sketch's build". `ticks_per_ms` a fifth short (OH_SYSTIMER_TICKS_PER_US * 800u) -> b'4\r\n', and the scaling tests see 384,061 and 576,061; a fifth long (* 1200u) -> b'' within its budget, and 576,061 and 864,061; `start += ticks_per_ms` deleted -> b'1\r\n', and delay(3) rises every 160,087 or so. Each of the four fails the new test and all three scaling items.

RUNTIMES, pytest's own, before -> after, on build/'s Debug core: tests/webui/test_compile.py 59.13 -> 70.54 s; tests/webui/test_board_run.py 7.43 -> 6.28; tests/riscv32/test_esp32c3_board.py 1.28 -> 2.19, c5 0.53 -> 0.41, c6 0.62 -> 0.61; feather 1.14 -> 3.24; olimex C3 0.78 -> 1.88; olimex C6 0.74 -> 1.74; glyph C3 0.97 -> 1.75; glyph C6 0.83 -> 1.77; QT Py 0.64 -> 1.61; SparkFun C5 0.79 -> 2.32; SparkFun C6 0.65 -> 1.61; Pro Micro 0.63 -> 1.63; Qwiic Pocket 0.63 -> 1.63.

VERIFIED on the tree committed as 57e2183, after python tools/build_core.py: tests/riscv32, tests/webui/test_compile.py, tests/webui/test_board_run.py and the ten board test files, 412 passed, 1 skipped (every_upstream_variants, OH_SLOW) in 102.33s; tests/cortexm0, tests/avr, test_pin_view, test_editor, test_artefacts, test_glyph_mini_rp2040_board, test_kb2040_board, test_xiao_rp2350_board and tests/rules/test_import_pindefs.py, 541 passed, 2 skipped, no SAMD21 or RP2040 image changed. Full suite twice: 2 failed (the OCP pair, test_a_part_that_names_a_lens_it_has_lost_still_refuses_to_convert and test_the_tessellator_welds_what_it_meshes, no OCP here), 2650 passed, 42 skipped. The 42nd skip against master's 41 is test_every_number_this_board_carries_is_the_one_in_pico_sdks_header, because lane2 has no third_party/bsp/arduino-pico/pico-sdk checkout; the new test's pass takes its place in the same 2650. tools/checkall.py: all eleven checker rows PASS, and the suite row FAILS on that OCP pair.

**Note 2026-10-09:** REVIEW OF THE delay() MOVE (57e2183, b67d575), AND ITS FIX ROUND. An independent review said MERGE AFTER FIXES: one MEDIUM, three LOWs and a cost to record. All five are answered here; the code is 6d7c3ba, 740a016 and 22b2d7f. Steps 3-5 remain, and this ticket stays in-progress.

FINDING 1, MEDIUM, FIXED (6d7c3ba). The ten board tests' period check, `len(gaps) == 1` over rise-to-rise gaps, held only because each budget ended before the first longer period, and it never asked for the rate. Run past their budgets the committed images' periods go 320,092 four times and then 320,104 on the C3 and C6, and 480,088, 480,088, 480,100 on the C5. Each of the ten files, and the Feather's stock Blink, now holds EVERY MOVE of the pin within POLL of the board's own millisecond: MILLISECOND = SYSTIMER_INSTRUCTIONS_PER_TICK * (SYSTIMER_HZ // 1000), read from the description, and POLL imported from tests/webui/test_compile.py, where it lives and the scaling tests already use it; no new helper. NOT the form the fix round was asked for, and why: every rise-to-rise gap within POLL of two milliseconds fails these images, because a period holds two delays and two overruns, and 320,104 is 104 steps past two milliseconds and 480,100 is 100, with POLL 100 and a strict `<`. A move-to-move gap holds one delay(1) and one write, which is the scaling tests' unit. Measured 2026-10-09 over fifty moves of every image and of the stock Blink, those gaps take three lengths on the C3 and C6, 160,043, 160,049 and 160,055, and four on the C5, 240,035, 240,041, 240,047 and 240,053: all within 55 steps of the millisecond. Each BUDGET now watches a gap of every length: 1,450,000 on the C3 and C6, where 160,055 first ends at step 1,440,461, the tenth move; 1,690,000 on the C5, where 240,035 first ends at 1,680,349, the eighth (the 480,100 period ends at the seventh). They were 650,000 and 970,000. That is more than one more rise: on the C3 and C6 one more rise reaches no new length, since the longer period is the fifth. COST, pytest's own on build/'s Debug core: each blink test 2.67 to 3.13 s, and the ten files 34.38 s together, against 19.18 s summed from the step-2 note's per-file runtimes, which were taken file by file.

BREAKS for finding 1, each run and restored. MILLISECOND at 0.9x in test_qtpy_esp32c3_board.py: its blink test fails, "a delay(1) is 144000 steps here, and SDA moved [160043, 160049, ...] apart", 1 failed, 1 passed; restored, 2 passed. delay() at 0.9x in wiring.c (OH_SYSTIMER_TICKS_PER_US * 900u) with the ten images rebuilt from it by webui.compile.build: all eleven blink tests fail on the new assertion, moves 144,047 and 144,053 apart on the C3 and C6 and 216,035 to 216,053 on the C5, while the ten image tests pass, so the new assertion is what catches it: 11 failed, 14 passed. The old check passed that break, both of its periods 288,100. wiring.c and the ten images were put back, and every committed image's sha256 checked equal to the one before.

FINDING 2, LOW, CORRECTED HERE. The note above (b67d575) says delayMicroseconds was left "a missing symbol at link time". It was a compile error, not a link error: with Arduino.h and wiring.c as at b67d575, `void setup(){ delayMicroseconds(10); }` built for the C3 stops at "sketch.cpp:1:15: error: 'delayMicroseconds' was not declared in this scope" (reproduced 2026-10-09), because Arduino.h declared nothing by that name. Finding 3 declares and defines it.

FINDING 3, LOW, FIXED (740a016). delayMicroseconds(uint32_t us) on SYSTIMER unit 0, declared in Arduino.h beside delay() and as arduino-esp32 declares it (cores/esp32/esp32-hal.h:170 at 2787dab, read through gh api), under Arduino.h's own rule that a function is present when every register it needs is mapped. wiring.c waits on delay()'s terms -- the same copy, the count's low 32 bits, `start` advanced by what was waited -- us / 1000 milliseconds of ticks one at a time, then (us % 1000) * OH_SYSTIMER_TICKS_PER_US ticks, so no piece nears 32 bits. Disassembled for the C3, C5 and C6 it is divu, remu and mul and calls nothing but the snapshot read. No committed image changed: every one's sha256 is the one before, and the ten board images still rebuild byte for byte. NEW: test_a_delay_in_microseconds_timed_by_micros_lasts_what_it_asked_for: delayMicroseconds(1250) timed by micros() prints exactly 1250 on the C3 and the C5, 1250 so that both waits run. Not 1251: t's copy is taken at tick 2 on the C3 and tick 1 on the C5, the closing copy at tick 20,007 and 20,004, short of 20,016. Not less: the wait is 20,000 ticks from a copy taken after t's. BREAKS, each run and restored: the rest dropped prints b'1000\r\n' (the C5 prints 1000 too, run alone); the whole milliseconds dropped, b'250\r\n'; `start` not advanced after a millisecond, b'1000\r\n'; the rest at fifteen ticks a microsecond, b'1234\r\n'. compile.py's F_CPU comment names it with the other three.

FINDING 4, LOW, FIXED (22b2d7f). The mutant that reads `start` again after each millisecond instead of advancing it loses a tick or so a millisecond. Measured with it, delay(N) timed by micros() prints: delay(10) 10001 on the C3 and C6 and 10000 on the C5; delay(20) 20001 on all three; delay(50) 50003, 50003 and 50002. Without it every one of those prints exactly N thousand. test_a_late_poll_does_not_push_the_next_millisecond_later times delay(50) on the C3 and asks for exactly 50000 (t's copy at tick 2, the closing copy at 800,007, short of 800,016). Under the mutant, tests/webui/test_compile.py, tests/riscv32/test_esp32c3_board.py and tests/webui/test_board_run.py give 2 failed, 162 passed, 1 skipped: this test (b'50003\r\n') and test_the_c5_and_c6_delay_is_steady_and_scales[XIAO-ESP32-C5-DIP]. Of those files, then, only this test sees the mutant on the C3 and C6. The ten board files were not run under it: their blink tests step the committed images, which the mutant does not change, and their image tests fail on any change to delay()'s bytes. Both bars are met: it kills the mutant, and it ran in 6.93 s by pytest's clock, 8,000,000 steps on the Debug core. The C3 alone, since the C6 counts at its rate.

FINDING 5, RECORDED: WHAT THE BROWSER PAYS. Measured 2026-10-09 22:38 on this machine and build/'s Debug core: session.run(200,000), the page's TICK_STEPS and api.MAX_RUN_STEPS, fifty times on the committed images, twice each: 1,233,998 and 1,248,843 steps/s on the QT Py ESP32-C3, 1,242,096 and 1,234,980 on the SparkFun Thing Plus ESP32-C5. The page's default Blink waits delay(500) (webui/static/emulator.js:700-702): 80,000,000 steps on a C3 or C6 and 120,000,000 on a C5, so 64 to 65 s per half period on a C3 or C6 and about 97 s on a C5. The step-2 note's "about 30 s at ~2.6 M steps/s" used clock.js's figure, 2,625,923 steps/s measured 2026-08-27 on an Arduino Uno, which is another core. The Debug build is OH-220 and the page's prose is OH-221, both filed on master. The owner may want to weigh in on an ESP32 default Blink taking a minute or more per half period. delay() stays on SYSTIMER, the orchestrator's decision: the step's own definition and clock.js's stated design, emulate the cited clock and show the rate, both call for it.

VERIFIED on the tree committed as 22b2d7f, after python tools/build_core.py: tests/riscv32, tests/webui/test_compile.py, tests/webui/test_board_run.py and the ten board test files, 414 passed, 1 skipped (every_upstream_variants, OH_SLOW) in 127.53 s, the two new tests among them. tools/checkall.py: all eleven checker rows PASS, and the suite row FAILS. The full suite run alone: 2 failed, 2652 passed, 42 skipped in 556.28 s. The two failures are the OCP pair, test_a_part_that_names_a_lens_it_has_lost_still_refuses_to_convert and test_the_tessellator_welds_what_it_meshes, under a python without OCP, as at 57e2183; 2652 is 57e2183's 2650 and the two new tests.
