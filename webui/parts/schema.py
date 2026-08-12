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
