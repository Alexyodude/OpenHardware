# OpenHardware — what an ESP32 timing test expects: a millisecond in steps, and how far from it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The two numbers every ESP32 timing test asks for -- a millisecond of the
board's SYSTIMER in steps, and how far from the step it predicts a pin may
move -- in one place, so that a board's test does not import them out of
another test module.

Not a test module, as `stub_rcontrol.py` beside it is not, and imported as
that one is: by full package path, `tests.webui.esp32_timing`, from the
repository root `tests/conftest.py` puts on the path.
"""

from types import ModuleType


def steps_per_millisecond(description: ModuleType) -> int:
    """A millisecond of `description`'s SYSTIMER unit 0, in steps:
    `SYSTIMER_HZ // 1000` ticks of `SYSTIMER_INSTRUCTIONS_PER_TICK` retired
    instructions each, read from the description rather than written in a
    test -- 160,000 on a C3 or a C6 and 240,000 on a C5 -- so a description
    that changes its rate changes what every test expects."""
    return description.SYSTIMER_INSTRUCTIONS_PER_TICK * (description.SYSTIMER_HZ // 1000)


#: How far, in steps, a move of a pin may land from the step its clock
#: predicts: each ESP32 timing test holds every move, or every gap between
#: two, to strictly within this. **Measured, not chosen** -- first on
#: 2026-10-09, and again on 2026-10-12, after OH-161's step 3 gave
#: `pinMode` its pad writes and every sketch's first toggle moved -- on two
#: kinds of sketch, which land on different sides of the clock:
#:
#:   * toggled by `millis()` or `micros()`, test_compile's `BY_MILLIS` and
#:     `BY_MICROS`: the sketch polls the clock in a loop and moves the pin
#:     when it sees the time, so a toggle lands up to a loop late and the
#:     gap between two wanders either side of the rate -- 14 under to 27
#:     over a millisecond, 17 under to 15 over a hundred microseconds, over
#:     each test's own toggles -- and the first toggle, `setup()` and all,
#:     lands 43 to 67 past.
#:   * waited by `delay()`, test_compile's scaling tests and every ESP32
#:     board's blink test: each gap is the wait and then the write, the loop
#:     around it and the poll that sees the tick, so it lands over the
#:     milliseconds and never under. 35 to 61 over one between two moves of
#:     a board's committed blink, measured over fifty moves of the QT Py
#:     ESP32-C3's, the SparkFun Thing Plus C6's and the SparkFun Thing Plus
#:     C5's; 61 to 73 over n between two rises of the scaling tests' blink,
#:     61 then 73 on the C3 and the C6, and 65 and 61 at the C5's delay(1)
#:     and delay(3).
#:
#: The widest, 73, leaves 27 steps. A rate wrong by one instruction a tick
#: is off by 16,000 steps a millisecond.
POLL = 100
