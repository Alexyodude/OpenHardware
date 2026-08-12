# Connecting peripherals

**Date:** 2026-08-10
**Status:** design approved, not implemented
**Scope:** sub-project 1 of 2. The 3D view is sub-project 2 and gets its own spec.

## 1. Why this comes first

The original ask was two things: connect peripherals, and view them in 3D. They
are separable, and they have a dependency — a 3D view needs parts that exist,
sit somewhere, and are wired to pins. Without that there is nothing to draw. So
peripherals are specified here and 3D follows.

The 3D sub-project's own finding, recorded here because it shaped the split:
PICSimLab has **no 3D geometry of any kind**. No OpenGL, WebGL, mesh, vertex,
`.obj` or `.gltf` anywhere in `src/`. Every part is a 2D `part.svg`. Sub-project
2 is therefore a content pipeline before it is a renderer, and its cost lives in
geometry, not code.

## 2. What already works

Verified against a live PICSimLab 0.9.3 on 2026-08-10, not read from source:

| command | effect |
|---|---|
| `spshow 1` | enable spare parts (`info` then reports `Use Spare: 1`) |
| `splist` | quoted list of available part names |
| `spadd "Name" x y` | place a part; quoted name and both coordinates required |
| `spdel N` / `spdel all` | remove |
| `sprdcfg N` | read a part's config string |
| `spwrcfg N <cfg>` | write it |

`spadd "Push Buttons" 100 100` returns `Ok` and `sprdcfg 0` then returns
`"0,0,0,0,0,0,0,0,1,0,8"`. Placement works.

## 3. The problem this design solves

**A part's config string is positional, per-part, and the simulator will never
explain it.**

`src/lib/part.h` exposes only `GetInputId(char* name)` and
`GetOutputId(char* name)` — name to id. There is no call that enumerates a
part's pins. `src/lib/rcontrol.cc` only ever resolves *board* pin names via
`Board->MGetPinName`; part pin names appear nowhere in the protocol.

The meaning of each position exists solely in each part's C++ source, as the
argument order of a `sprintf` plus the string literals passed to
`RegisterIOpin`. From `src/parts/output_LED_matrix.cc:173`:

```c
sprintf(prefs, "%hhu,%hhu,%hhu,%hhu,%i,%i",
        input_pins[0], input_pins[1], input_pins[2], output_pins[0], angle,
        lmode);
```

So wiring a peripheral requires a **schema authored outside the simulator**.

## 4. Architecture

Purely additive. The transport and API built earlier are unchanged.

```
browser UI
     |
webui/bridge.py        existing, untouched
     |
webui/api.py           existing; gains wiring operations
     |
webui/parts/           NEW
  schema.py              loader + validator
  schemas/<part>.json    one per supported part
     |
rcontrol:  splist . spadd . sprdcfg . spwrcfg . spdel
```

`webui/parts/` is the only new component.

## 5. Schema format

```json
{
  "part": "LED Matrix",
  "source": "src/parts/output_LED_matrix.cc:173",
  "verified": "2026-08-10 round-trip against PICSimLab 0.9.3",
  "fields": [
    {"role": "pin", "dir": "in",  "label": "R"},
    {"role": "pin", "dir": "in",  "label": "G"},
    {"role": "pin", "dir": "in",  "label": "B"},
    {"role": "pin", "dir": "out", "label": "DOUT"},
    {"role": "setting", "type": "int", "label": "angle"},
    {"role": "setting", "type": "int", "label": "lmode"}
  ]
}
```

That last field is worth a note, because writing this example demonstrated the
hazard it warns about. The first draft of this spec labelled it `size`, quoting
the `sprintf` with its final argument elided as `...`. The argument is actually
`lmode`. The label was invented to fill a gap, read as fact, and was wrong —
which is exactly why `source` must cite a line and why a draft schema is never
authoritative until someone reads the source it claims to describe.

- **`role`** separates wireable from not. Only `pin` fields are connection
  points; without this a UI would offer to wire an angle to a GPIO.
- **`source`** cites the line the layout came from. A schema with no citation is
  a guess.
- **`verified`** records a live round-trip and is **absent until one happens**.
  An unverified schema is usable but must be visibly unproven, because a wrong
  schema silently miswires a circuit rather than erroring.
- **Pin value `0` means unconnected**, matching the observed config of a freshly
  placed part.

## 6. How schemas are produced

Hand-authored, seeded by a parser, verified live.

A parser over `src/parts/*.cc` extracts each `sprintf(prefs, ...)` format and
the `RegisterIOpin("NAME")` literals to **draft** a schema. Each draft is then
read against the source by a human or agent, corrected, and only then subjected
to a live round-trip.

The parser is a labour saver, never an authority. Formats vary between parts and
some branch at runtime, so a generated schema that is merely plausible is the
dangerous case — it produces a circuit that is wired wrongly and reports
success.

Coverage is deliberately partial. Schemas are written for parts as they are
needed; there is no requirement to cover all 52 before anything works.

## 7. The wiring API

```python
place_part(name, x, y) -> int        # spadd, returns the new index
remove_part(index) / remove_all()    # spdel N / spdel all
read_config(index) -> str            # sprdcfg, raw
write_config(index, cfg)             # spwrcfg, raw
read_wiring(index, schema) -> dict   # config string -> named fields
connect(index, schema, label, pin)   # set one pin field, write back
disconnect(index, schema, label)     # same, to 0
```

`connect()` is necessarily a read-modify-write of the entire config string,
because `spwrcfg` accepts nothing smaller. Concurrent writers would clobber each
other; the bridge's existing request lock prevents that. That lock was added for
protocol framing reasons and turns out to be load-bearing for correctness here
too.

**There is no part-count command.** `spadd` returns `Ok`, not an index, and
`spshow` returns a flag. Counting is done by probing `sprdcfg` upward until it
returns ERROR, which is how `place_part` learns the index it just created. This
is inelegant and it is what the protocol offers.

## 8. Verification, and its ceiling

Three checks, strongest first:

1. **Round-trip** — `spwrcfg` a config, `sprdcfg` it back, require a match.
   Proves the write took effect.
2. **Arity** — a schema's field count must equal the CSV field count of a real
   `sprdcfg` reply. Cheap, and catches the most likely schema error.
3. **Placement** — after `spadd`, `sprdcfg` at the expected index must succeed.

**The ceiling: none of this proves a wire carries signal.** That requires
`get part[N].in[M]`, which returns ERROR for every index on a headlessly placed
part because `GetInputCount()` is 0 (`docs/known-issues.md` 4a.5). A verified
schema therefore proves **configuration, not conduction**, and no cell may claim
otherwise.

This is the honest boundary of the sub-project. Closing it needs either the
GUI-layout path that populates part inputs, or an upstream change.

## 9. Testing

- `tests/webui/test_part_schema.py` — loading, validation, arity. A malformed
  schema raises rather than loading partially.
- Live round-trip tests extend `tests/webui/test_live_oracle.py`, opt-in under
  `OPENHARDWARE_LIVE=1` so an absent simulator fails rather than skips.
- `tools/check_part_schemas.py` — every schema parses, cites a `source`, and has
  consistent arity. Declared as a mechanism in `.claude/rules/`, which means the
  meta-guard will require it to appear in `rules.yml`.

The checker follows the house pattern: every artifact class in this repository
has a parser that raises rather than skips.

## 10. Non-goals

- Not all 52 parts. Schemas are written on demand.
- Not signal-level verification — see §8.
- Not the 3D view, which is sub-project 2.
- No upstream C++ changes. An `spcfgfmt` introspection command would make
  schemas unnecessary and is the right eventual contribution, but it requires a
  build pipeline that can verify it, which §8.4 shows does not yet exist.
