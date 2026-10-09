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
