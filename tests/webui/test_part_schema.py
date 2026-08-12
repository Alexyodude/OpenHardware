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

INTERLEAVED = {
    "part": "Interleaved",
    "source": "src/parts/example.cc:1",
    "fields": [
        {"role": "setting", "type": "int", "label": "before"},
        {"role": "pin", "dir": "out", "label": "A"},
        {"role": "setting", "type": "int", "label": "between"},
        {"role": "pin", "dir": "in", "label": "B"},
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
    # Settings deliberately precede and separate the pins: a pre-filtered
    # implementation would report (0, "A"), (1, "B") and pass a fixture where
    # pins came first. These indices are positions in the config CSV, and
    # connect() rewrites a single column by them.
    schema = load_schema(write(tmp_path, INTERLEAVED))
    assert [(i, f.label) for i, f in schema.pin_fields] == [(1, "A"), (3, "B")]


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
