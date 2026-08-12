# OpenHardware — tests for the schema-aware wiring API.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pytest

from tests.webui.stub_rcontrol import StubRControl, ok
from webui.api import SimulatorApi
from webui.parts.schema import Field, PartSchema, SchemaError, load_all_schemas
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


def test_connecting_a_pin_number_above_255_raises():
    # The config field is `%hhu` -- an unsigned char. Values above 255 wrap
    # mod 256 on the wire (300 lands as 44), so a caller wiring "pin 300" is
    # silently rewired to pin 44 and told it succeeded unless this is caught
    # client-side first.
    with StubRControl({"sprdcfg 0": ok(FRESH)}) as stub:
        api, client = api_for(stub)
        with pytest.raises(SchemaError, match="B1"):
            api.connect(0, BUTTONS, "B1", 300)
        client.close()


def test_connecting_a_negative_pin_number_raises():
    # Same wraparound from the other direction: -1 lands as 255 on the wire.
    with StubRControl({"sprdcfg 0": ok(FRESH)}) as stub:
        api, client = api_for(stub)
        with pytest.raises(SchemaError, match="B1"):
            api.connect(0, BUTTONS, "B1", -1)
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


# -- regression: the pre-existing sibling methods must agree with the new
# schema-aware ones on wire format, or the two pairs silently drift apart.


def test_read_part_config_strips_the_quotes_sprdcfg_returns():
    # sprdcfg's real reply is quoted -- `ok(FRESH)` alone would not reproduce
    # the bug, since the stub then never sends a quote to strip.
    with StubRControl({"sprdcfg 0": ok(f'"{FRESH}"')}) as stub:
        api, client = api_for(stub)
        config = api.read_part_config(0)
        client.close()
    assert '"' not in config
    assert config == FRESH


def test_write_part_config_sends_the_quoted_form():
    with StubRControl({"sprdcfg 0": ok(FRESH)}) as stub:
        api, client = api_for(stub)
        api.write_part_config(0, FRESH)
        client.close()
    assert f'spwrcfg 0 "{FRESH}"' in stub.received


# --- values that are not integers -------------------------------------------
#
# Added 2026-08-12. `input_LDR.cc:240` writes `vthreshold` with `%f`, so an LDR
# reports `0,0,100,2.500000`. Until the LDR schema was authored, every shipped
# schema was all-integer and `_values` parsed the whole config with `int()`.
# That crashed on read -- and worse, a read-modify-write would have written
# `2.500000` back as `2`, silently destroying a setting the caller never
# touched.


def _float_schema() -> PartSchema:
    return PartSchema(
        part="Floaty",
        source="src/parts/input_LDR.cc:240",
        fields=(
            Field(role="pin", dir="out", label="P1"),
            Field(role="pin", dir="out", label="P2"),
            Field(role="setting", type="int", label="value"),
            Field(role="setting", type="float", label="vthreshold"),
        ),
    )


def test_a_float_setting_reads_back_as_a_float():
    schema = _float_schema()
    with StubRControl({"sprdcfg 0": ok('"0,0,100,2.500000"')}) as stub:
        client = RControlClient(port=stub.port, timeout=2)
        client.connect()
        wiring = SimulatorApi(client).read_wiring(0, schema)
        client.close()
    assert wiring["vthreshold"] == pytest.approx(2.5)
    assert wiring["value"] == 100
    assert wiring["P1"] == 0


def test_a_pin_write_preserves_a_float_setting_byte_for_byte():
    """The corruption case. `2.500000` must go back exactly, not as `2`."""
    schema = _float_schema()
    with StubRControl({"sprdcfg 0": ok('"0,0,100,2.500000"')}) as stub:
        client = RControlClient(port=stub.port, timeout=2)
        client.connect()
        SimulatorApi(client).connect(0, schema, "P1", 9)
        client.close()
    written = [c for c in stub.received if c.startswith("spwrcfg")]
    assert written == ['spwrcfg 0 "9,0,100,2.500000"'], written


def test_an_unparseable_field_is_returned_as_text_not_raised_on():
    """Refusing to answer would make the whole part unreadable over one field."""
    schema = _float_schema()
    with StubRControl({"sprdcfg 0": ok('"0,0,100,nonsense"')}) as stub:
        client = RControlClient(port=stub.port, timeout=2)
        client.connect()
        wiring = SimulatorApi(client).read_wiring(0, schema)
        client.close()
    assert wiring["vthreshold"] == "nonsense"


# --- the shipped catalogue ---------------------------------------------------


def test_every_shipped_schema_loads_and_cites_a_line():
    schemas = load_all_schemas(
        pathlib.Path(__file__).resolve().parents[2] / "webui" / "parts" / "schemas"
    )
    assert len(schemas) >= 12, sorted(schemas)
    for name, schema in schemas.items():
        assert ":" in schema.source, f"{name} cites no line"
        assert schema.arity == len(schema.fields)


def test_every_pin_field_declares_a_direction():
    """A pin with no direction cannot be drawn or wired correctly."""
    schemas = load_all_schemas(
        pathlib.Path(__file__).resolve().parents[2] / "webui" / "parts" / "schemas"
    )
    for name, schema in schemas.items():
        for _, field in schema.pin_fields:
            assert field.dir in ("in", "out"), f"{name}.{field.label}"
