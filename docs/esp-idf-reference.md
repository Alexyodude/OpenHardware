# The ESP-IDF reference

`webui/boards/esp32c5.py` and `webui/boards/esp32c6.py` cite Espressif's SoC
headers by file and line, and so does each ESP32 variant's `soc/soc_caps.h`
under `webui/arduino/variants/`. This is how to get a copy of the tree those
lines point into, and why it is a second reference checkout rather than the one
this repository already had.

## Why a second tree

`webui/boards/esp32c3.py` reads its numbers from PlatformIO's
`framework-arduinoespressif32`, which is already installed for the toolchain
and ships ESP-IDF 4.4.7. That was enough for one chip and is enough for no
others. Measured 2026-08-25, its `tools/sdk/` holds exactly

```
esp32/  esp32c3/  esp32s2/  esp32s3/  versions.txt
```

— **no `esp32c6` and no `esp32c5`.** The PlatformIO registry's newest
`framework-arduinoespressif32` is 3.20017 (Arduino core 2.0.17, the same IDF
4.4.7), so there is no version of that package to upgrade to that carries them.
Describing those two parts meant reading a different tree.

A different tree is a different claim until something ties the two together, so
one thing had to be true before this one was admissible: **v5.5's own `esp32c3`
headers must reproduce every number `esp32c3.py` already carries.** They do,
and `test_the_new_header_tree_reproduces_the_board_this_repository_already_had`
in `tests/riscv32/test_esp32c6_board.py` is that check, run rather than
asserted here.

## Getting it

```bash
git clone --filter=blob:none --no-checkout --depth 1 --branch v5.5 \
    https://github.com/espressif/esp-idf ../esp-idf-reference
cd ../esp-idf-reference
git sparse-checkout init --cone
git sparse-checkout set components/soc/esp32c3 components/soc/esp32c5 \
    components/soc/esp32c6 tools/cmake examples/get-started/blink
git checkout
```

A full clone is well over a gigabyte and nothing here needs it. The five paths
above are what the board files and their tests cite:

| path | what is read from it |
|---|---|
| `components/soc/<chip>/include/soc/soc.h` | the memory map |
| `components/soc/<chip>/include/soc/soc_caps.h` | whether the busses share an address, whether the MMU page size is a build option, and `SOC_GPIO_PIN_COUNT`, which each ESP32 variant's `soc/soc_caps.h` restates |
| `components/soc/<chip>/include/soc/ext_mem_defs.h` | the MMU page size and entry count the C6's flash window is computed from |
| `components/soc/<chip>/register/soc/reg_base.h` | `DR_REG_GPIO_BASE` |
| `components/soc/<chip>/register/soc/gpio_reg.h` | the GPIO register offsets |
| `tools/cmake/toolchain-<chip>.cmake` | the `-march` string ESP-IDF compiles each part with |
| `examples/get-started/blink/main/Kconfig.projbuild` | `BLINK_GPIO`, the pin the fixtures watch |

`esp32c3` is in that list on purpose. It was not needed to describe anything —
it is the control, and the reason this tree is trusted at all. Since OH-185 the
C3 build's `soc/soc_caps.h` reads its GPIO count from it too.

**Note the layout moved.** In IDF 4.4.7 the register bases and the GPIO
register file were inside `include/soc/soc.h` and `include/soc/gpio_reg.h`; in
5.x they are under `register/soc/`. That is why `esp32c3.py`'s citations read
`soc.h:45` and this page's read `register/soc/reg_base.h:48`, and neither is
stale.

## Which revision

**v5.5.0, commit `8c750b0`**, and unlike the PICSimLab reference this one *is*
pinned in prose, because the citations are line numbers. `soc.h:154` is not a
fact about the ESP32-C6; it is a fact about one file at one revision. A reader
on a different tag will find the same defines at different lines.

Nothing enforces the pin, and that is deliberate: the tests read the headers by
**define name**, not by line, so a newer tag that moved a line still passes and
a newer tag that changed a *number* fails loudly with both values. The line
numbers in the board files are there to make a value findable by a human, and
the tests are what make it correct. `tests/webui/test_soc_caps.py` keeps its
citations findable as well: a separate test holds each one to the line that
defines its name, so a tag that moved a line fails that test alone.

## How the code finds it

Nothing in `webui/` or `core/` looks for this tree at all — the board files
carry the numbers and cite where they came from. Only the tests read it, in
this order:

| order | location |
|---|---|
| 1 | `$ESP_IDF_ROOT` |
| 2 | `../esp-idf-reference/` |
| 3 | `../esp-idf/` |

That is the resolution `webui/picsimlab.py` uses for the other reference tree,
kept the same so there is one habit rather than two.

## When it is missing

The tests that read it **skip**, naming the clone command. Never pass quietly —
the same contract the rule checkers keep when they cannot find a PICSimLab
source tree, and for the same reason: a check that silently became a no-op is
worse than one that says it did not run.

The rest of the suite is unaffected. The board descriptions are plain Python
constants, so every board test but the header cross-checks runs with no ESP-IDF
anywhere.

## Licence

ESP-IDF is Apache-2.0. Nothing from it is vendored here: what this repository
contains is a set of integers read out of it and the citations saying where.
`rules/licence-hygiene.md` governs vendored trees, and this is not one — the
checkout is a sibling, and `.gitignore` covers `/esp-idf/` and
`/esp-idf-reference/` for anyone who puts it inside the repository anyway.
