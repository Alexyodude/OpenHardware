# Compiling a sketch in the browser tab: what it costs, measured

OH-244. Measured 2026-10-16 on the Windows 11 PC this repository is developed
on, over loopback. Every number here is a measurement of one build at one
commit, and says so; `python tools/build_compiler.py` prints the bundle's
current size, and the console line `OpenHardware compiler for ATmega328P:
fetched N MB in S s and kept it` prints a first build's.

## The Arduino Uno: built, and the same bytes as the server

What the page fetches the first time Build is pressed, from the site itself:

```text
                                            raw        gzip -6
avr/tools/cc1plus.wasm   GCC 7.3.0's C++     11.21 MB    4.02 MB
avr/fs/opt/avr/lib/      GCC's headers,       6.07 MB    0.68 MB   (libgcc.a keeps its debug info)
                         libgcc.a
avr/tools/avr-{ld,objcopy,as}.wasm            2.36 MB    0.87 MB
avr/fs/opt/avr/avr/      avr-libc             0.95 MB    0.22 MB
avr/tools/*.mjs          Emscripten glue      0.32 MB    0.09 MB
avr/fs/arduino-avr/, avr/fs/objects/          0.21 MB    0.07 MB
total, ATmega328P        131 files           21.12 MB    5.95 MB
+ plan.json, manifest.json, boards.json, worker.js, build.js
```

Whether a host sends the gzip column is the host's choice; the page asks for
nothing compressed and Cache Storage keeps what arrived.

**A first build**, Blink, from pressing Build to the board loaded:

```text
Chrome, headed, with the GPU          6.3 s   fetch 21.1 MB 5.1 s, compile 0.18 s
  a second build                      0.1 s   nothing fetched
  after a reload                              the compiler read from Cache Storage
Chromium headless, --enable-gpu      8.9 s   fetch 5.4 s, compile 1.7 s
Chromium headless (SwiftShader)     83-224 s  fetch 63-164 s; 224 s was with the machine busy
  a second build                      5.0 s
```

The software-rendered figure is the test machine and not the compiler: the
same headless Chromium told it may use the GPU (`--enable-gpu`, or
`--use-angle=d3d11` on Windows) builds in seconds, and that is how
`tests/webui/test_compiler_page.py` launches it. The page's 3D view renders in
software otherwise, and it starves everything else in the tab: the
board ran Blink 30 to 60 times slower than headed in the same runs (between
8.1 and 16.1 million instructions in 241 s, against 24.2 million in 12 s). The
server is not it either: curl took 0.16 s for `cc1plus.wasm`, and a Python
file server's five-deep listen queue, which on Windows makes a refused
connection retry after seconds, was ruled out by making it 128 deep.

Over a network, the fetch is the size over the bandwidth: 21.1 MB is about
3.4 s at 50 Mbit/s and 17 s at 10 Mbit/s, or a quarter of that where the host
compresses.

**Verified in the page** (`tests/webui/test_compiler_page.py` holds each):

```text
Blink, delay(500)    PB5 changes every  8,000,000 instructions  (500 ms of 16 MHz)
Blink, delay(250)    PB5 changes every  4,000,000 instructions  (250 ms)
int x = ;  line 2    sketch.cpp:2:23: error: expected primary-expression before ';' token
                     the line quoted under it; the board's state unchanged
XIAO-SAMD21-DIP      Build disabled; "Build it with the local server: python
                     webui/emulator_server.py from a checkout."
requests             the site's own files, and blob: URLs of its own origin; nothing else
```

**The same bytes as the server** (`tests/webui/test_compile_wasm.py`): Blink at
500 and 250, OH-135's idioms with Wire, SPI and EEPROM, Serial with String and
placement new, and soft float with `sinf`, each built by `webui/compile.py`
with PlatformIO's avr-gcc and by `compiler/build.js` under node, image for
image. And the error messages: a syntax error, the same in a sketch that
includes `Arduino.h` itself, a note pointing into the core's `Arduino.h`, and
a link error, each in the server's words, with its labels for paths --
`<toolchain>/framework-arduino-avr/...`, `<build>/00.o` -- and two
differences, both explained in the tests: the server separates a path with
its host's separator, backslashes on Windows, and a link error there ends with
collect2's `ld returned 1 exit status`, because the server's driver runs ld
through collect2 and the browser runs ld itself.

Three things had to be found for that, and each is a comment where it lives:

- GCC's configure asks the TARGET assembler and linker what they support and
  generates different code by the answer, COMDAT groups and mergeable string
  sections among it. Cross-compiled for WebAssembly, the assembler it would
  ask is not runnable, so the answers came back "no" and the idioms and
  Serial samples differed from the server's. `build-avr.sh` builds a native
  avr-binutils first, for configure to ask, and refuses to go on unless
  `auto-host.h` says yes to both.
- A linker that can load plugins makes the driver add `-fuse-linker-plugin`,
  which then wants a `liblto_plugin.so` there is no way to load in a tab:
  `-fno-use-linker-plugin`, which removes only the plugin arguments.
- GCC quotes the line an error is on by reopening the file by name. The server
  compiles the sketch outside its working directory and so quotes nothing of
  its own; the bundle compiles `/sketch/sketch.cpp` from `/build` to match.

**The toolchain rebuilds from source, reproducibly.** `python
tools/build_compiler.py` builds it in Docker from Arduino's pinned sources
(emsdk 5.0.3 by digest) and lays out the bundle. From a new Docker volume,
toolchain and bundle took 616 s; two builds from nothing and one incremental
gave the same bytes for every tool.

`@horang-corp/avr-gcc-wasm` was not used, for the reasons
`PROVENANCE.md` §4 gives: no licence on its own code, no build scripts for its
WebAssembly, and binutils 2.42 against the server's 2.26.

## The SAMD21: next, the same way

The server builds it with PlatformIO's `toolchain-gccarmnoneeabi` 1.120301.0
and `framework-arduino-samd` 1.8.14. That toolchain is **xPack's** build of
GCC 12.3.1 (20230626), as its README and `gcc -v` say, and not Arm's own
12.3.Rel1 binaries: of the Cortex-M0+ files a link reads, Arm's Windows
release has `libc.a`, `libm.a`, `libnosys.a`, `crt0.o`, `crtbegin.o` and
`libgcc.a` different in bytes from PlatformIO's (measured 2026-10-16), so it
is xPack's that a browser build has to match.
Its native `cc1plus` is 26.5 MB against the AVR's 13.3 MB, whose WebAssembly
build is 11.2 MB; at the same ratio the SAMD21's would be about 22 MB, before
newlib-nano, libstdc++ and CMSIS. Not built in this change. Its boards say to
build them with the local server until it is.

## The RP2040: nothing to match

The server has no recipe for it: `webui/compile.py` says the RP2040 rows wait
on the repository's own `openhardware` core gaining a Cortex-M0+ start and
vector table. A browser build has no server image to be byte-identical to, so
there is nothing to build here yet, and the page's Build says "no compile
recipe", which is true in both places.

## The ESP32s: the framework costs almost nothing

The three ESP32 rows do not use Espressif's Arduino framework or ESP-IDF's
libraries. They build bare metal (`-nostdlib -nostartfiles`) against the
repository's own `openhardware` core, which is 128 KB of source in
`webui/arduino/`, with the vendor's pin header for each board. So the cost of
shipping them is one more compiler: PlatformIO's `toolchain-riscv32-esp`
8.4.0+2021r2-patch5, whose native `cc1plus` is 17.1 MB, about 14 MB as
WebAssembly at the AVR's ratio, plus whichever C headers the core includes
(`<stdint.h>` at least). **It fits**, as the Uno does. It is not built in this change. The boards say to build them with the
local server until it is.
