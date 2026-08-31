---
id: OH-151
title: A global constructor is collected by --gc-sections and never runs, and the
  build says nothing
status: done
priority: P1
created: '2026-08-31'
touches:
- webui/arduino/variants/xiao_esp32c3/link.ld
- webui/arduino/cores/openhardware/main.c
- webui/compile.py
- tests/webui/test_compile.py
---

A sketch with a global C++ constructor builds for the XIAO ESP32-C3 and the
constructor never runs. Nothing says so: the build reports ok, the image is
the usual size, and the only symptom is that the object was never
initialised.

Measured 2026-08-31 at 4d2ace5, with

    struct Marker { int v; Marker() { v = 5; } };
    Marker m;
    void setup() { pinMode(D10, OUTPUT); if (m.v == 5) digitalWrite(D10, HIGH); }

built and stepped: ok=True, 148 bytes, and GPIO10 rose zero times where at
least three were expected.

The mechanism is not simply that link.ld forgets .init_array. It is that
--gc-sections COLLECTS it. The linker map shows the input section present and
four bytes long, contributed by the sketch object, while readelf on the linked
ELF lists no .init_array output section at all -- the constructor and its
pointer are both garbage, because nothing in the image references
__init_array_start and nothing KEEPs the section. So the constructor is not
merely unreached; its code is not in the image.

This is the only absence in the openhardware core that fails quietly. Every
other one -- digitalRead, millis, Serial, analogWrite, attachInterrupt -- is a
compile error carrying a Recipe.hints row that names the modelling decision it
stands on. A hints row cannot cover this one, because hints are matched
against the diagnostics of a build that FAILED and this build succeeds.

The fix is to place .init_array in irom under KEEP with start and end symbols,
and to walk it from oh_run before setup(), which is the part of crt0 that
cannot be argued away the way the .data copy and the .bss zero were. Placing
it explicitly also retires an untested tail risk a review raised: as an orphan
the section had no stated home, and had ld ever placed it after .bss in dram
the flat image would have spanned the roughly 37 MB gap between the two
regions.

A global with a non-trivial DESTRUCTOR needs deciding in the same pass. Today
it also builds at the same 148 bytes, but only because the __cxa_atexit
registration lives inside the same collected fragment. Once the section is
kept, that reference survives, and with -nostdlib there is nothing to resolve
it. A link error is the honest outcome -- on a board whose loop() never
returns, a destructor can never run, so a build that silently accepted one
would be lying in the same way. Making that readable means the hint pass has
to apply to link diagnostics, which today it does not: build() runs _hinted on
the compile failure path only.

**Note 2026-08-31:** CLOSED 2026-08-31. `.init_array` is placed in irom under KEEP with
PROVIDE_HIDDEN bounds, and `oh_init_array` in the core walks it from
`oh_run` before `setup()`. The constructor sketch that reported ok at 148
bytes and rose zero times now links at 196 bytes with the section at
0x420000c0, contiguous after `.text`, and the pin rises.

`tests/webui/test_compile.py::test_a_global_constructor_runs_and_runs_before_setup`
holds it, and was mutation-proved rather than trusted: deleting the
`oh_init_array()` call, dropping KEEP from either line, deleting the output
section outright, and moving the walk to after `setup()` are 4 of 4 caught.
The witness is volatile because at -Os gcc will otherwise prove the
constructor set it and fold the comparison away, which is the failure the
neighbouring `.data`/`.bss` test already recorded.

**This ticket's own prediction about destructors was wrong, and the file
now says so where it would be read.** The body above expected that keeping
the section would leave an unresolved `__cxa_atexit` and a loud link
failure, and that `_hinted` would have to be extended to link diagnostics
so the failure was readable. None of that happened. Measured after the fix:
a sketch whose global has a destructor still builds, at the same 196 bytes,
because the compiler emits no destructor at all -- `readelf -S` of the
sketch object lists `.text`, `.text.setup`, `.text.loop`,
`.text.startup._GLOBAL__sub_I_*` and `.init_array`, with no `.fini_array`
and no destructor body, and `nm -u` on it names only `pinMode` and
`digitalWrite`, so there is no `__cxa_atexit` or `atexit` reference either.
Nothing reaches the linker to be dropped. `webui/compile.py` is therefore
untouched: no hint row, no change to the hint pass, and the ticket keeps
its claim on the path only so the record of why it was expected survives.
A global destructor never running is what every Arduino target does on real
silicon, because `loop()` never returns.

Verified: `python tools/checkall.py` -> all 12 checks pass, 2,006 passed /
17 skipped in one clean run with none of the load-flakiness the previous
handoff recorded.

Noted, NOT fixed, because it is adjacent work in a docstring this ticket
only happened to be next to: in
`test_a_sketch_s_globals_survive_the_linker_script_having_no_crt0`, the
second bullet of a two-bullet list ("a zero-initialised global that is
incremented goes high exactly ONCE") sits AFTER the "what this test does
and does not catch" paragraph instead of beside its sibling, so the list
reads as though it were part of the mutation discussion. A prose move of
five lines, worth its own ticket.
