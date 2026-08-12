# Connecting Peripherals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a caller place a peripheral on the simulated board and wire its pins, using schemas that describe each part's config string.

**Architecture:** A new `webui/parts/` package holds one JSON schema per supported part, describing the positional fields of that part's config string. `webui/api.py` gains schema-aware wiring operations on top of the existing `sprdcfg`/`spwrcfg` commands. A checker validates every schema, following the repository's pattern that each artifact class has a parser that raises rather than skips.

**Tech Stack:** Python 3.14.3, pytest 9.0.2, PyYAML 6.0.3, websockets 15.0.1. No new dependencies.

## Global Constraints

- **License:** GPL-2-or-later. Every new `.py` carries the header used by every other file in this repo — the three closing lines read "This program is free software; you can redistribute it and/or modify it under / the terms of the GNU General Public License as published by the Free Software / Foundation; either version 2, or (at your option) any later version."
- **No `sys.path` manipulation in test files.** `tests/webui/conftest.py` handles it.
- **No modification of any file that existed at tag `fork-point`** (`cd92747b1a04cab56c17f4e9ac35a1406c9935f7`) except `src/lib/board.h`, already logged in `docs/upstream-deltas.md`. Everything in this plan is new or is a fork-created file.
- **Test scope:** `pytest tests/rules/ tests/webui/ -v`. Never bare `pytest` from the repo root — upstream's `tests/python/` errors at collection.
- **Empty input raises.** Every loader and checker here raises rather than returning an empty result.
- **`verified` is absent until a live round-trip happens.** Never hand-write it.
- **Pin value `0` means unconnected.**
- **Round-trip proves configuration, not conduction** (spec §8). No test or docstring may claim a wire carries signal.
- **Branch:** `design/feature-strategy`.

---

## File Structure

| File | Responsibility |
|---|---|
| `webui/parts/__init__.py` | Package marker. |
| `webui/parts/schema.py` | `PartSchema` / `Field` dataclasses, `load_schema`, `load_all_schemas`, `SchemaError`. |
| `webui/parts/schemas/push_buttons.json` | Real schema, from `input_push_buttons.cc:377`. |
| `webui/parts/schemas/leds.json` | Real schema, from `output_leds.cc:220`. |
| `webui/parts/schemas/led_matrix.json` | Real schema, from `output_LED_matrix.cc:173`. |
| `webui/api.py` | Gains wiring operations. Existing methods unchanged. |
| `tools/check_part_schemas.py` | Validates every schema; wired into CI. |
| `.claude/rules/conformance-fixtures.md` | Gains a mechanism declaring the checker. |
| `tests/webui/test_part_schema.py` | Schema loading and validation. |
| `tests/webui/test_wiring.py` | Wiring API against the stub server. |
| `tests/webui/test_live_oracle.py` | Gains live round-trip tests. |
| `tests/rules/test_check_part_schemas.py` | Tests for the checker. |

**Baseline before starting:** `pytest tests/rules/ tests/webui/ -q` collects **134** tests. Nine of those are live-oracle tests that skip without a running simulator. Report the number you actually observe at each step; never adjust tests to hit a target.

---

### Task 1: Schema loader

**Files:**
- Create: `webui/parts/__init__.py`, `webui/parts/schema.py`
- Test: `tests/webui/test_part_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SchemaError`; frozen dataclasses `Field(role: str, label: str, dir: str | None, type: str | None)` and `PartSchema(part: str, source: str, fields: tuple[Field, ...], verified: str | None)`; `PartSchema.arity -> int`; `PartSchema.pin_fields -> list[tuple[int, Field]]` returning `(index, field)` pairs; `load_schema(path) -> PartSchema`; `load_all_schemas(dir) -> dict[str, PartSchema]` keyed by part name.

- [ ] **Step 1: Write the failing test**

Create `tests/webui/test_part_schema.py`:

```python
# OpenHardware — tests for the part schema loader.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import json
import pathlib

import pytest

from webui.parts.schema import SchemaError, load_all_schemas, load_schema

VALID = {
    "part": "Example",
    "source": "src/parts/example.cc:100",
    "fields": [
        {"role": "pin", "dir": "out", "label": "A"},
        {"role": "setting", "type": "int", "label": "size"},
    ],
}


def write(tmp_path: pathlib.Path, data: dict, name: str = "example.json") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_valid_schema_loads(tmp_path):
    schema = load_schema(write(tmp_path, VALID))
    assert schema.part == "Example"
    assert schema.source == "src/parts/example.cc:100"
    assert schema.arity == 2
    assert schema.verified is None


def test_pin_fields_report_their_position(tmp_path):
    # Position matters: it is the index into the config CSV.
    schema = load_schema(write(tmp_path, VALID))
    assert [(i, f.label) for i, f in schema.pin_fields] == [(0, "A")]


def test_missing_source_raises(tmp_path):
    data = {k: v for k, v in VALID.items() if k != "source"}
    with pytest.raises(SchemaError, match="source"):
        load_schema(write(tmp_path, data))


def test_empty_fields_raises(tmp_path):
    with pytest.raises(SchemaError, match="no fields"):
        load_schema(write(tmp_path, {**VALID, "fields": []}))


def test_unknown_role_raises(tmp_path):
    bad = {**VALID, "fields": [{"role": "wire", "label": "A"}]}
    with pytest.raises(SchemaError, match="wire"):
        load_schema(write(tmp_path, bad))


def test_a_pin_without_direction_raises(tmp_path):
    bad = {**VALID, "fields": [{"role": "pin", "label": "A"}]}
    with pytest.raises(SchemaError, match="dir"):
        load_schema(write(tmp_path, bad))


def test_a_setting_without_type_raises(tmp_path):
    bad = {**VALID, "fields": [{"role": "setting", "label": "s"}]}
    with pytest.raises(SchemaError, match="type"):
        load_schema(write(tmp_path, bad))


def test_malformed_json_raises_schema_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SchemaError):
        load_schema(path)


def test_an_empty_schema_directory_raises(tmp_path):
    # A loader that returns {} for an empty directory reports the same thing as
    # a loader that found every schema, and CI cannot tell them apart.
    with pytest.raises(SchemaError, match="no schemas"):
        load_all_schemas(tmp_path)


def test_a_missing_schema_directory_raises(tmp_path):
    with pytest.raises(SchemaError, match="does not exist"):
        load_all_schemas(tmp_path / "absent")


def test_duplicate_part_names_raise(tmp_path):
    write(tmp_path, VALID, "one.json")
    write(tmp_path, VALID, "two.json")
    with pytest.raises(SchemaError, match="duplicate"):
        load_all_schemas(tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/webui/test_part_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'webui.parts'`

- [ ] **Step 3: Write minimal implementation**

Create `webui/parts/__init__.py`:

```python
# OpenHardware — part schemas: what each position in a config string means.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
```

Create `webui/parts/schema.py`:

```python
# OpenHardware — load and validate part wiring schemas.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Describe the positional fields of a part's rcontrol config string.

A part's config is a positional CSV produced by that part's `WritePreferences`
and consumed by its `ReadPreferences`. The simulator will not explain it:
`src/lib/part.h` offers only `GetInputId(name)` and `GetOutputId(name)`, so a
caller can ask which id a named pin has but never which pins exist. That
knowledge lives only in each part's C++ source, which is why these schemas are
authored here and why every one cites the line it came from.

A wrong schema does not raise. It writes a valid-looking config that wires the
circuit incorrectly and reports success, so `source` and `verified` carry real
weight: `source` says where the layout was read, `verified` says a live
round-trip confirmed it. `verified` is absent until that happens and is never
hand-written.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib

ROLES = frozenset({"pin", "setting"})
DIRECTIONS = frozenset({"in", "out"})

#: A pin field set to 0 is unconnected. Confirmed against a freshly placed
#: part, whose config reads `0,0,0,0,0,0,0,0,1,0,8`.
UNCONNECTED = 0


class SchemaError(Exception):
    """A schema is missing, malformed, or internally inconsistent."""


@dataclasses.dataclass(frozen=True)
class Field:
    role: str
    label: str
    dir: str | None = None
    type: str | None = None


@dataclasses.dataclass(frozen=True)
class PartSchema:
    part: str
    source: str
    fields: tuple[Field, ...]
    verified: str | None = None

    @property
    def arity(self) -> int:
        """How many comma-separated values the config string must have."""
        return len(self.fields)

    @property
    def pin_fields(self) -> list[tuple[int, Field]]:
        """Wireable fields with their index into the config CSV."""
        return [(i, f) for i, f in enumerate(self.fields) if f.role == "pin"]

    def index_of(self, label: str) -> int:
        for index, field in enumerate(self.fields):
            if field.label == label:
                return index
        raise SchemaError(f"{self.part}: no field labelled {label!r}")


def _field(raw: object, part: str, index: int) -> Field:
    if not isinstance(raw, dict):
        raise SchemaError(f"{part}: field {index} is not an object")
    role = raw.get("role")
    if role not in ROLES:
        raise SchemaError(f"{part}: field {index} has role {role!r}, expected one of {sorted(ROLES)}")
    label = raw.get("label")
    if not label:
        raise SchemaError(f"{part}: field {index} has no label")
    if role == "pin":
        if raw.get("dir") not in DIRECTIONS:
            raise SchemaError(
                f"{part}: pin field {label!r} needs dir in {sorted(DIRECTIONS)}"
            )
    elif not raw.get("type"):
        raise SchemaError(f"{part}: setting field {label!r} needs a type")
    return Field(role=role, label=label, dir=raw.get("dir"), type=raw.get("type"))


def load_schema(path: pathlib.Path) -> PartSchema:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaError(f"{path}: cannot read schema: {exc}") from exc
    if not isinstance(raw, dict):
        raise SchemaError(f"{path}: schema must be an object")

    part = raw.get("part")
    if not part:
        raise SchemaError(f"{path}: missing 'part'")
    source = raw.get("source")
    if not source:
        raise SchemaError(f"{path}: {part} has no 'source'; a schema with no citation is a guess")

    fields = raw.get("fields")
    if not isinstance(fields, list) or not fields:
        raise SchemaError(f"{path}: {part} has no fields")

    return PartSchema(
        part=part,
        source=source,
        fields=tuple(_field(f, part, i) for i, f in enumerate(fields)),
        verified=raw.get("verified"),
    )


def load_all_schemas(directory: pathlib.Path) -> dict[str, PartSchema]:
    if not directory.is_dir():
        raise SchemaError(f"{directory}: schema directory does not exist")
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise SchemaError(f"{directory}: contains no schemas")

    schemas: dict[str, PartSchema] = {}
    for path in paths:
        schema = load_schema(path)
        if schema.part in schemas:
            raise SchemaError(f"{path}: duplicate part name {schema.part!r}")
        schemas[schema.part] = schema
    return schemas
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/webui/test_part_schema.py -q`
Expected: PASS — 11 passed

- [ ] **Step 5: Commit**

```bash
git add webui/parts/ tests/webui/test_part_schema.py
git commit -m "feat(parts): add part schema loader

A schema says what each position in a part's config CSV means, because the
simulator will not: part.h exposes name-to-id lookup only, with no way to
enumerate a part's pins. Malformed schemas raise rather than load partially."
```

---

### Task 2: Three real schemas

Every value below was read from the source line cited. Do not invent labels; if a field's meaning is unclear, read the file rather than guessing.

**Files:**
- Create: `webui/parts/schemas/push_buttons.json`, `webui/parts/schemas/leds.json`, `webui/parts/schemas/led_matrix.json`
- Test: `tests/webui/test_part_schema.py` (append)

**Interfaces:**
- Consumes: `load_all_schemas`, `PartSchema` from Task 1.
- Produces: `webui/parts/schemas/` as the canonical schema directory.

- [ ] **Step 1: Write the failing test**

Append to `tests/webui/test_part_schema.py`:

```python
REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMAS = REPO / "webui" / "parts" / "schemas"


def test_the_shipped_schemas_all_load():
    assert load_all_schemas(SCHEMAS)


def test_push_buttons_matches_its_source():
    """input_push_buttons.cc:377 — 8 output pins, then active, mode, Size.

    A live `sprdcfg` on a freshly placed Push Buttons returned
    "0,0,0,0,0,0,0,0,1,0,8", which decodes exactly against this layout:
    eight unconnected pins, active=1, mode=0, Size=8.
    """
    schema = load_all_schemas(SCHEMAS)["Push Buttons"]
    assert schema.arity == 11
    assert len(schema.pin_fields) == 8
    assert all(f.dir == "out" for _, f in schema.pin_fields)
    assert [f.label for f in schema.fields[8:]] == ["active", "mode", "Size"]


def test_leds_matches_its_source():
    """output_leds.cc:220 — 8 input pins, active, 8 colors, Size."""
    schema = load_all_schemas(SCHEMAS)["LEDs"]
    assert schema.arity == 18
    assert len(schema.pin_fields) == 8
    assert all(f.dir == "in" for _, f in schema.pin_fields)
    assert schema.fields[8].label == "active"
    assert schema.fields[17].label == "Size"


def test_led_matrix_matches_its_source():
    """output_LED_matrix.cc:173 — 3 input pins, 1 output pin, angle, lmode."""
    schema = load_all_schemas(SCHEMAS)["LED Matrix"]
    assert schema.arity == 6
    assert [f.dir for _, f in schema.pin_fields] == ["in", "in", "in", "out"]
    assert [f.label for f in schema.fields[4:]] == ["angle", "lmode"]


def test_no_shipped_schema_claims_verification_it_has_not_earned():
    # `verified` is set only by a live round-trip, never by hand.
    for schema in load_all_schemas(SCHEMAS).values():
        if schema.verified is not None:
            assert "round-trip" in schema.verified
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/webui/test_part_schema.py -q`
Expected: FAIL — `SchemaError: ... schema directory does not exist`

- [ ] **Step 3: Write the schemas**

Create `webui/parts/schemas/push_buttons.json`:

```json
{
  "part": "Push Buttons",
  "source": "src/parts/input_push_buttons.cc:377",
  "fields": [
    {"role": "pin", "dir": "out", "label": "B1"},
    {"role": "pin", "dir": "out", "label": "B2"},
    {"role": "pin", "dir": "out", "label": "B3"},
    {"role": "pin", "dir": "out", "label": "B4"},
    {"role": "pin", "dir": "out", "label": "B5"},
    {"role": "pin", "dir": "out", "label": "B6"},
    {"role": "pin", "dir": "out", "label": "B7"},
    {"role": "pin", "dir": "out", "label": "B8"},
    {"role": "setting", "type": "int", "label": "active"},
    {"role": "setting", "type": "int", "label": "mode"},
    {"role": "setting", "type": "int", "label": "Size"}
  ]
}
```

Create `webui/parts/schemas/leds.json`:

```json
{
  "part": "LEDs",
  "source": "src/parts/output_leds.cc:220",
  "fields": [
    {"role": "pin", "dir": "in", "label": "L1"},
    {"role": "pin", "dir": "in", "label": "L2"},
    {"role": "pin", "dir": "in", "label": "L3"},
    {"role": "pin", "dir": "in", "label": "L4"},
    {"role": "pin", "dir": "in", "label": "L5"},
    {"role": "pin", "dir": "in", "label": "L6"},
    {"role": "pin", "dir": "in", "label": "L7"},
    {"role": "pin", "dir": "in", "label": "L8"},
    {"role": "setting", "type": "int", "label": "active"},
    {"role": "setting", "type": "int", "label": "color1"},
    {"role": "setting", "type": "int", "label": "color2"},
    {"role": "setting", "type": "int", "label": "color3"},
    {"role": "setting", "type": "int", "label": "color4"},
    {"role": "setting", "type": "int", "label": "color5"},
    {"role": "setting", "type": "int", "label": "color6"},
    {"role": "setting", "type": "int", "label": "color7"},
    {"role": "setting", "type": "int", "label": "color8"},
    {"role": "setting", "type": "int", "label": "Size"}
  ]
}
```

Create `webui/parts/schemas/led_matrix.json`:

```json
{
  "part": "LED Matrix",
  "source": "src/parts/output_LED_matrix.cc:173",
  "fields": [
    {"role": "pin", "dir": "in", "label": "R"},
    {"role": "pin", "dir": "in", "label": "G"},
    {"role": "pin", "dir": "in", "label": "B"},
    {"role": "pin", "dir": "out", "label": "DOUT"},
    {"role": "setting", "type": "int", "label": "angle"},
    {"role": "setting", "type": "int", "label": "lmode"}
  ]
}
```

Note the direction convention, which is counter-intuitive and worth stating: `dir` is from the **part's** perspective. Push Buttons uses `output_pins` because it *drives* a signal into the MCU; LEDs uses `input_pins` because it *receives* one. A UI labelling these "output" and "input" from the board's point of view would have them backwards.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/webui/test_part_schema.py -q`
Expected: PASS — 16 passed

- [ ] **Step 5: Commit**

```bash
git add webui/parts/schemas/
git commit -m "feat(parts): add schemas for Push Buttons, LEDs, LED Matrix

Each field read from the cited source line. Push Buttons decodes the live
capture 0,0,0,0,0,0,0,0,1,0,8 exactly: eight unconnected pins, active=1,
mode=0, Size=8. None claims verification yet."
```

---

### Task 3: Wiring API

**Files:**
- Modify: `webui/api.py`
- Test: `tests/webui/test_wiring.py`

**Interfaces:**
- Consumes: `PartSchema`, `SchemaError`, `UNCONNECTED` from Task 1; `SimulatorApi`, `RControlClient` from the existing `webui/api.py` and `webui/rcontrol.py`; `RControlCommandError` from `webui/rcontrol.py`.
- Produces: on `SimulatorApi` — `part_count() -> int`, `place_part(name, x, y) -> int`, `read_config(index) -> str`, `write_config(index, cfg) -> None`, `read_wiring(index, schema) -> dict[str, int]`, `connect(index, schema, label, pin) -> None`, `disconnect(index, schema, label) -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/webui/test_wiring.py`:

```python
# OpenHardware — tests for the schema-aware wiring API.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pytest

from tests.webui.stub_rcontrol import StubRControl, ok
from webui.api import SimulatorApi
from webui.parts.schema import PartSchema, load_all_schemas
from webui.rcontrol import RControlClient

import pathlib

SCHEMAS = load_all_schemas(
    pathlib.Path(__file__).resolve().parents[2] / "webui" / "parts" / "schemas"
)
BUTTONS: PartSchema = SCHEMAS["Push Buttons"]
FRESH = "0,0,0,0,0,0,0,0,1,0,8"


def api_for(stub: StubRControl):
    client = RControlClient(host="127.0.0.1", port=stub.port, timeout=2.0)
    client.connect()
    return SimulatorApi(client), client


def test_part_count_probes_until_error():
    # There is no count command; sprdcfg N errors past the last part.
    replies = {"sprdcfg 0": ok(FRESH), "sprdcfg 1": ok(FRESH), "sprdcfg 2": "ERROR\r\n>"}
    with StubRControl(replies) as stub:
        api, client = api_for(stub)
        assert api.part_count() == 2
        client.close()


def test_part_count_is_zero_when_the_first_probe_errors():
    with StubRControl({"sprdcfg 0": "ERROR\r\n>"}) as stub:
        api, client = api_for(stub)
        assert api.part_count() == 0
        client.close()


def test_place_part_returns_the_new_index():
    replies = {
        "sprdcfg 0": "ERROR\r\n>",
        'spadd "Push Buttons" 100 200': ok(),
    }
    with StubRControl(replies) as stub:
        api, client = api_for(stub)
        assert api.place_part("Push Buttons", 100, 200) == 0
        client.close()
    assert 'spadd "Push Buttons" 100 200' in stub.received


def test_read_wiring_maps_labels_to_values():
    with StubRControl({"sprdcfg 0": ok(FRESH)}) as stub:
        api, client = api_for(stub)
        wiring = api.read_wiring(0, BUTTONS)
        client.close()
    assert wiring["B1"] == 0
    assert wiring["active"] == 1
    assert wiring["Size"] == 8


def test_connect_rewrites_only_the_named_field():
    # The quotes matter: rcontrol.cc:1307 scans `%d "%511[^"]"`, so an
    # unquoted config never reaches the part.
    with StubRControl({"sprdcfg 0": ok(FRESH)}) as stub:
        api, client = api_for(stub)
        api.connect(0, BUTTONS, "B3", 7)
        client.close()
    assert 'spwrcfg 0 "0,0,7,0,0,0,0,0,1,0,8"' in stub.received


def test_disconnect_sets_the_field_to_zero():
    wired = "0,0,7,0,0,0,0,0,1,0,8"
    with StubRControl({"sprdcfg 0": ok(wired)}) as stub:
        api, client = api_for(stub)
        api.disconnect(0, BUTTONS, "B3")
        client.close()
    assert 'spwrcfg 0 "0,0,0,0,0,0,0,0,1,0,8"' in stub.received


def test_connecting_a_setting_field_is_refused():
    # Wiring an angle to a GPIO is nonsense; the schema's roles exist to stop it.
    with StubRControl({"sprdcfg 0": ok(FRESH)}) as stub:
        api, client = api_for(stub)
        with pytest.raises(Exception, match="not a pin"):
            api.connect(0, BUTTONS, "Size", 3)
        client.close()


def test_a_config_of_the_wrong_arity_raises():
    # Arity is the cheapest check that a schema matches the running part.
    with StubRControl({"sprdcfg 0": ok("1,2,3")}) as stub:
        api, client = api_for(stub)
        with pytest.raises(Exception, match="arity"):
            api.read_wiring(0, BUTTONS)
        client.close()


def test_an_unknown_label_raises():
    with StubRControl({"sprdcfg 0": ok(FRESH)}) as stub:
        api, client = api_for(stub)
        with pytest.raises(Exception, match="no field labelled"):
            api.connect(0, BUTTONS, "nonexistent", 1)
        client.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/webui/test_wiring.py -q`
Expected: FAIL — `AttributeError: 'SimulatorApi' object has no attribute 'part_count'`

- [ ] **Step 3: Write minimal implementation**

Add to the imports at the top of `webui/api.py`:

```python
from webui.parts.schema import UNCONNECTED, PartSchema, SchemaError
from webui.rcontrol import RControlClient, RControlCommandError, Response
```

(The existing import line already brings in `RControlClient` and `Response`; extend it rather than duplicating it.)

Append these methods to `SimulatorApi`:

```python
    # -- wiring ------------------------------------------------------------

    def part_count(self) -> int:
        """Count placed parts by probing until the server refuses.

        There is no count command. `spadd` returns Ok rather than an index and
        `spshow` returns a flag, so the only way to learn how many parts exist
        is to ask for each in turn until one errors.
        """
        index = 0
        while True:
            try:
                self.client.command(f"sprdcfg {index}")
            except RControlCommandError:
                return index
            index += 1

    def place_part(self, name: str, xpos: int, ypos: int) -> int:
        """Place a part and return the index it landed at."""
        index = self.part_count()
        self.add_part(name, xpos, ypos)
        return index

    def read_config(self, index: int) -> str:
        # A live `sprdcfg 0` returned `"0,0,0,0,0,0,0,0,1,0,8"` -- quoted.
        return self.client.command(f"sprdcfg {index}").body.strip().strip('"')

    def write_config(self, index: int, config: str) -> None:
        """Write a part's whole config string.

        The quotes are mandatory. rcontrol.cc:1307 parses this argument with
        `sscanf(cmd + 8, "%d \\"%511[^\\"]\\"", &pid, scfg)`, so an unquoted
        config never reaches the part -- the same trap `spadd` sets.

        The server also validates arity for us: rcontrol.cc:1310 compares
        `Part->ReadPreferences(scfg)` against `Part->PreferencesNumberFields()`
        and answers ERROR when they disagree. So a schema with the wrong field
        count fails loudly on write rather than silently miswiring, which is a
        stronger guarantee than this plan assumed.
        """
        self.client.command(f'spwrcfg {index} "{config}"')

    def _values(self, index: int, schema: PartSchema) -> list[int]:
        raw = self.read_config(index)
        values = [int(v) for v in raw.split(",") if v.strip() != ""]
        if len(values) != schema.arity:
            raise SchemaError(
                f"{schema.part}: arity mismatch — schema declares {schema.arity} "
                f"fields, part {index} reported {len(values)}: {raw!r}"
            )
        return values

    def read_wiring(self, index: int, schema: PartSchema) -> dict[str, int]:
        """Map every field label to its current value."""
        return {
            field.label: value
            for field, value in zip(schema.fields, self._values(index, schema))
        }

    def _set_field(self, index: int, schema: PartSchema, label: str, value: int) -> None:
        position = schema.index_of(label)
        if schema.fields[position].role != "pin":
            raise SchemaError(f"{schema.part}: {label!r} is not a pin field")
        values = self._values(index, schema)
        values[position] = int(value)
        self.write_config(index, ",".join(str(v) for v in values))

    def connect(self, index: int, schema: PartSchema, label: str, pin: int) -> None:
        """Wire one of the part's pins to a board pin number."""
        self._set_field(index, schema, label, pin)

    def disconnect(self, index: int, schema: PartSchema, label: str) -> None:
        self._set_field(index, schema, label, UNCONNECTED)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/webui/test_wiring.py -q`
Expected: PASS — 9 passed

- [ ] **Step 5: Run the whole suite**

Run: `pytest tests/rules/ tests/webui/ -q`
Expected: PASS. Report the observed count.

- [ ] **Step 6: Commit**

```bash
git add webui/api.py tests/webui/test_wiring.py
git commit -m "feat(webui): add schema-aware wiring API

connect() is a read-modify-write of the whole config string because spwrcfg
accepts nothing smaller; the bridge's existing request lock is what stops two
writers clobbering each other. part_count() probes sprdcfg upward because the
protocol offers no count command."
```

---

### Task 4: Schema checker, declared and wired into CI

**Files:**
- Create: `tools/check_part_schemas.py`
- Modify: `.claude/rules/conformance-fixtures.md` (frontmatter and a new numbered section), `.github/workflows/rules.yml`
- Test: `tests/rules/test_check_part_schemas.py`

**Interfaces:**
- Consumes: `load_all_schemas`, `SchemaError` from Task 1.
- Produces: `find_problems(directory) -> list[str]` and `main() -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/rules/test_check_part_schemas.py`:

```python
# OpenHardware — tests for the part schema checker.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import json
import pathlib

import pytest

from tools.check_part_schemas import find_problems

REPO = pathlib.Path(__file__).resolve().parents[2]

GOOD = {
    "part": "Example",
    "source": "src/parts/example.cc:100",
    "fields": [{"role": "pin", "dir": "out", "label": "A"}],
}


def write(tmp_path, data, name="example.json"):
    (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def test_a_good_schema_has_no_problems(tmp_path):
    assert find_problems(write(tmp_path, GOOD)) == []


def test_a_source_without_a_line_number_is_a_problem(tmp_path):
    # "src/parts/example.cc" does not say where; a citation must be checkable.
    bad = {**GOOD, "source": "src/parts/example.cc"}
    problems = find_problems(write(tmp_path, bad))
    assert any("line number" in p for p in problems)


def test_a_source_pointing_at_a_missing_file_is_a_problem(tmp_path):
    bad = {**GOOD, "source": "src/parts/does_not_exist.cc:1"}
    problems = find_problems(write(tmp_path, bad), repo_root=REPO)
    assert any("does not exist" in p for p in problems)


def test_an_empty_directory_raises(tmp_path):
    with pytest.raises(Exception, match="no schemas"):
        find_problems(tmp_path)


def test_the_shipped_schemas_pass():
    assert find_problems(REPO / "webui" / "parts" / "schemas", repo_root=REPO) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/rules/test_check_part_schemas.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.check_part_schemas'`

- [ ] **Step 3: Write minimal implementation**

Create `tools/check_part_schemas.py`:

```python
#!/usr/bin/env python3
# OpenHardware — validate part wiring schemas.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Checker for the schema requirements in .claude/rules/conformance-fixtures.md.

Loading proves a schema is well formed. This additionally proves its citation
is checkable: a `source` must name a file that exists and a line within it. A
schema whose citation cannot be followed is indistinguishable from one that was
guessed, and a guessed schema wires a circuit wrongly while reporting success.
"""

from __future__ import annotations

import pathlib
import re
import sys

try:
    from webui.parts.schema import SchemaError, load_all_schemas
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from webui.parts.schema import SchemaError, load_all_schemas

SCHEMA_DIR = pathlib.Path("webui/parts/schemas")
_SOURCE = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+)$")


def find_problems(
    directory: pathlib.Path = SCHEMA_DIR, repo_root: pathlib.Path | None = None
) -> list[str]:
    """Return every problem found. Raises if there is nothing to check."""
    schemas = load_all_schemas(directory)

    problems: list[str] = []
    for schema in schemas.values():
        match = _SOURCE.match(schema.source)
        if not match:
            problems.append(
                f"{schema.part}: source {schema.source!r} has no line number"
            )
            continue
        if repo_root is None:
            continue
        cited = repo_root / match.group("path")
        if not cited.is_file():
            problems.append(f"{schema.part}: source file {match.group('path')} does not exist")
            continue
        lines = cited.read_text(encoding="utf-8", errors="replace").splitlines()
        if int(match.group("line")) > len(lines):
            problems.append(
                f"{schema.part}: source line {match.group('line')} is past the end of "
                f"{match.group('path')} ({len(lines)} lines)"
            )
    return problems


def main() -> int:
    try:
        problems = find_problems(SCHEMA_DIR, repo_root=pathlib.Path("."))
    except SchemaError as exc:
        print(f"check_part_schemas: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"check_part_schemas: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print("check_part_schemas: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/rules/test_check_part_schemas.py -q`
Expected: PASS — 5 passed

- [ ] **Step 5: Run the checker against the real schemas**

Run: `python tools/check_part_schemas.py`
Expected: `check_part_schemas: OK`, exit 0

- [ ] **Step 6: Declare the mechanism**

In `.claude/rules/conformance-fixtures.md`, add a third entry to the `mechanisms:` list in the frontmatter, keeping the existing two unchanged:

```yaml
  - tier: SCRIPT-ENFORCED
    checker: tools/check_part_schemas.py
    armed: true
```

Then append this section to the end of the same file:

```markdown
## 6. 2026-08-10 — SCRIPT-ENFORCED: a schema must cite a checkable line

`tools/check_part_schemas.py` requires every part schema's `source` to name a
file that exists and a line within it.

A part's config string is positional and the simulator will not explain it
(`src/lib/part.h` offers name-to-id lookup only), so each schema is authored by
reading that part's `WritePreferences`. A wrong schema does not raise — it
writes a valid-looking config that wires the circuit incorrectly and reports
success. The citation is what makes a schema auditable, so a citation nobody
can follow is treated as no citation at all.

`find_problems` raises on an empty directory, for the reason section 2 gives.
```

- [ ] **Step 7: Wire it into CI**

In `.github/workflows/rules.yml`, add a step immediately after the `check_board_contract` step:

```yaml
      - name: check_part_schemas
        run: python tools/check_part_schemas.py
```

- [ ] **Step 8: Confirm the meta-guard is satisfied**

Run: `pytest tests/rules/ tests/webui/ -q`
Expected: PASS. `test_every_armed_script_enforced_checker_runs_in_ci` must pass — it fails if a declared checker has no `run:` line, which is why Step 7 is not optional. Report the observed count.

- [ ] **Step 9: Commit**

```bash
git add tools/check_part_schemas.py tests/rules/test_check_part_schemas.py \
        .claude/rules/conformance-fixtures.md .github/workflows/rules.yml
git commit -m "feat(rules): require part schemas to cite a checkable line

A wrong schema does not raise; it miswires a circuit and reports success, so
the citation is what makes it auditable. Declaring the mechanism makes the
meta-guard demand the CI step."
```

---

### Task 5: Live round-trip verification

**Files:**
- Modify: `tests/webui/test_live_oracle.py`
- Modify: `webui/parts/schemas/push_buttons.json` (add `verified` once it passes)

**Interfaces:**
- Consumes: everything from Tasks 1-3.
- Produces: no new API. This task converts a schema from unproven to proven.

- [ ] **Step 1: Write the failing test**

Append to `tests/webui/test_live_oracle.py`:

```python
# --- wiring, against a live simulator ---------------------------------------


@pytest.fixture
def buttons(api):
    """Place a Push Buttons part and yield (index, schema). Cleans up after."""
    import pathlib

    from webui.parts.schema import load_all_schemas

    schemas = load_all_schemas(
        pathlib.Path(__file__).resolve().parents[2] / "webui" / "parts" / "schemas"
    )
    api.client.command("spshow 1")
    index = api.place_part("Push Buttons", 100, 100)
    yield index, schemas["Push Buttons"]
    api.client.try_command(f"spdel {index}")


def test_a_placed_part_matches_its_schema_arity(api, buttons):
    """The cheapest proof a schema describes the running part."""
    index, schema = buttons
    wiring = api.read_wiring(index, schema)
    assert len(wiring) == schema.arity


def test_a_freshly_placed_part_has_no_connections(api, buttons):
    index, schema = buttons
    wiring = api.read_wiring(index, schema)
    assert all(wiring[f.label] == 0 for _, f in schema.pin_fields)


def test_a_wiring_change_round_trips(api, buttons):
    """Write a pin, read it back. Proves configuration, NOT conduction.

    Nothing here shows a signal reaches the pin — that needs
    get part[N].in[M], which returns ERROR on a headlessly placed part
    (docs/known-issues.md 4a.5). This asserts only that the simulator stored
    what it was told.
    """
    index, schema = buttons
    api.connect(index, schema, "B1", 7)
    assert api.read_wiring(index, schema)["B1"] == 7

    api.disconnect(index, schema, "B1")
    assert api.read_wiring(index, schema)["B1"] == 0


def test_settings_survive_a_pin_write(api, buttons):
    """connect() rewrites the whole string, so it must not disturb settings."""
    index, schema = buttons
    before = api.read_wiring(index, schema)
    api.connect(index, schema, "B2", 5)
    after = api.read_wiring(index, schema)
    assert after["active"] == before["active"]
    assert after["Size"] == before["Size"]
```

- [ ] **Step 2: Run against a live simulator**

Start one first, in WSL:

```bash
wsl -d Ubuntu-22.04 -- bash -lc 'cd /root/oh/src && DISPLAY=:0 setsid nohup ./picsimlab /root/oh/tests/blink/blink.pzw >/root/picsimlab.log 2>&1 < /dev/null &'
```

Then run, from the repo root on Windows:

```bash
OPENHARDWARE_LIVE=1 pytest tests/webui/test_live_oracle.py -v
```

Expected: all pass. If `place_part` fails, check that `/root/oh/share/picsimlab` exists as a symlink to `/root/oh/share` — without it, placing a part **segfaults the simulator** (docs/known-issues.md 4a.1 and 4a.2).

If a test fails because the live config's arity differs from the schema, **the schema is wrong, not the test**. Read the cited source line again and correct the schema. That is this task's whole purpose.

- [ ] **Step 3: Mark the schema verified**

Only after Step 2 passes, add to `webui/parts/schemas/push_buttons.json`, after `"source"`:

```json
  "verified": "2026-08-10 round-trip against PICSimLab 0.9.3",
```

Do not add `verified` to `leds.json` or `led_matrix.json` — those parts were not placed or round-tripped, and claiming otherwise is the overclaim this field exists to prevent.

- [ ] **Step 4: Confirm both modes**

Run: `pytest tests/rules/ tests/webui/ -q` (live tests skip)
Run: `OPENHARDWARE_LIVE=1 pytest tests/rules/ tests/webui/ -q` (live tests run)
Expected: both pass. Report both observed counts.

- [ ] **Step 5: Commit**

```bash
git add tests/webui/test_live_oracle.py webui/parts/schemas/push_buttons.json
git commit -m "test(webui): verify Push Buttons wiring against a live simulator

Round-trips a pin write through spwrcfg/sprdcfg and confirms settings are
undisturbed. Only push_buttons.json gains `verified`; the other two schemas
were never placed, and claiming otherwise is the overclaim that field exists
to prevent.

Proves configuration, not conduction: nothing here shows a signal reaches the
pin, which needs get part[N].in[M] (known-issues 4a.5)."
```

---

## Done criteria

- [ ] `python tools/check_part_schemas.py` exits 0, and CI runs it.
- [ ] All six checkers exit 0: layering, board_contract, part_schemas, licenses, deltas, banned_symbols.
- [ ] `pytest tests/rules/ tests/webui/ -q` passes with live tests skipping.
- [ ] `OPENHARDWARE_LIVE=1 pytest tests/rules/ tests/webui/ -q` passes with them running.
- [ ] Exactly one schema carries `verified`, and it is the one that was round-tripped.
- [ ] `git diff --name-status cd92747 HEAD` shows only `A` lines plus the single logged `M src/lib/board.h`.

## Deliberately deferred

| Deferred | Why | Unblocked by |
|---|---|---|
| Schemas for the other 49 parts | Written on demand; the spec makes partial coverage explicit | Need |
| Signal-level verification | `get part[N].in[M]` errors on a headlessly placed part | known-issues 4a.5 |
| A parser to draft schemas from `src/parts/*.cc` | Three hand-written schemas are enough to prove the format; a generator is worth building once the format has settled | This plan landing |
| An upstream `spcfgfmt` command | Would make schemas unnecessary, but needs a build pipeline that can verify it | spec §8.4 |
| The 3D view | Sub-project 2, own spec | This plan landing |
