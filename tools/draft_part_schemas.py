#!/usr/bin/env python3
# OpenHardware — draft part wiring schemas from the C++ that writes the config.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Read each part's `WritePreferences` and emit a **draft** schema.

A part's config string is positional and the simulator will never explain it:
`src/lib/part.h` offers name-to-id lookup only. The meaning of each position
exists solely as the argument order of a `sprintf` in that part's source.

**This tool is a labour saver, never an authority.** The peripherals design
(§6) is explicit about why: formats vary, some branch at runtime, and a
generated schema that is merely plausible is the dangerous case, because it
writes a valid-looking config that wires the circuit wrongly and reports
success. Every draft must be read against the cited line by a person before it
is moved into `webui/parts/schemas/`, and `verified` must not be added until a
live round-trip has happened.

So this writes to a directory you name, never into the shipped schema
directory, and it stamps each draft with `"draft": true`.

    python tools/draft_part_schemas.py --out drafts/
    python tools/draft_part_schemas.py --part "Servo Motor"
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

PARTS_DIR = pathlib.Path("src/parts")

#: `part_init(PART_SERVO_Name, cpart_servo, "Output");`
_PART_INIT = re.compile(
    r"part_init\(\s*(?P<macro>\w+)\s*,\s*(?P<cls>\w+)\s*,\s*\"(?P<category>\w+)\"\s*\)"
)
#: `#define PART_SERVO_Name "Servo Motor"`
_NAME_DEFINE = re.compile(r'#define\s+(?P<macro>\w+)\s+"(?P<name>[^"]+)"')
#: the `sprintf(prefs, "fmt", args...)` inside WritePreferences
_SPRINTF = re.compile(
    r"sprintf\s*\(\s*prefs\s*,\s*\"(?P<fmt>[^\"]*)\"\s*,(?P<args>.*?)\)\s*;",
    re.DOTALL,
)
_CONVERSION = re.compile(r"%[-+ #0-9.]*(?:hh|h|l|ll|z)?[diouxXeEfgGcs]")


class DraftError(Exception):
    """A part's source did not have the shape this drafter can read."""


def part_names(root: pathlib.Path) -> dict[pathlib.Path, str]:
    """Map each part source file to the display name it registers."""
    macros: dict[str, str] = {}
    for header in root.glob("*.h"):
        for match in _NAME_DEFINE.finditer(header.read_text(encoding="utf-8", errors="replace")):
            macros[match.group("macro")] = match.group("name")

    found: dict[pathlib.Path, str] = {}
    for source in sorted(root.glob("*.cc")):
        init = _PART_INIT.search(source.read_text(encoding="utf-8", errors="replace"))
        if init is None:
            continue
        name = macros.get(init.group("macro"))
        if name is not None:
            found[source] = name
    if not found:
        raise DraftError(f"no part registrations found under {root}")
    return found


def _split_args(text: str) -> list[str]:
    """Split a C argument list on top-level commas."""
    args, depth, current = [], 0, ""
    for char in text:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            args.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        args.append(current.strip())
    return [a for a in args if a]


def _classify(arg: str) -> dict:
    """Turn one sprintf argument into a draft field.

    `input_pins[0]` is a pin the part reads; `output_pins[0]` is one it drives.

    A bare `pins[N]` is **also a pin**, but its direction is not derivable from
    the name -- nine parts use that array, and in `input_hcsr04.cc` element 0
    is read (`pins_[pins[0] - 1].value`) while element 1 is driven
    (`SpareParts.SetPin(pins[1], 0)`). Calling those settings, as an earlier
    version of this drafter did, would have produced a schema that looks
    complete and refuses to wire two real pins. So they are marked for review
    with a null direction rather than guessed.

    Anything else is a setting, labelled with the variable's own name, which is
    a starting point for a human rather than a claim about meaning.
    """
    bare = arg.replace(" ", "")
    array = re.match(r"^(?P<base>\w+)\[(?P<index>\d+)\]$", bare)
    base = array.group("base") if array else bare
    suffix = f"_{int(array.group('index')) + 1}" if array else ""

    if base in ("input_pins", "input_pin"):
        return {"role": "pin", "dir": "in", "label": f"in{suffix or '_1'}"}
    if base in ("output_pins", "output_pin"):
        return {"role": "pin", "dir": "out", "label": f"out{suffix or '_1'}"}
    if base in ("pins", "pin"):
        return {
            "role": "pin",
            "dir": None,
            "label": f"pin{suffix or '_1'}",
            "needs_review": "direction not derivable from the variable name",
        }
    return {"role": "setting", "type": "int", "label": f"{base}{suffix}"}


def draft(source: pathlib.Path, name: str) -> dict:
    """Build one draft schema from a part's source file."""
    text = source.read_text(encoding="utf-8", errors="replace")
    start = text.find("WritePreferences")
    if start < 0:
        raise DraftError(f"{name}: no WritePreferences in {source.name}")

    match = _SPRINTF.search(text, start)
    if match is None:
        raise DraftError(
            f"{name}: WritePreferences in {source.name} does not use the "
            f"`sprintf(prefs, \"...\", ...)` shape this drafter reads. Author "
            f"its schema by hand."
        )

    line = text.count("\n", 0, match.start()) + 1
    args = _split_args(match.group("args"))
    conversions = _CONVERSION.findall(match.group("fmt"))

    if len(conversions) != len(args):
        raise DraftError(
            f"{name}: {len(conversions)} conversions but {len(args)} arguments "
            f"at {source.name}:{line}. Read it by hand -- a mismatch here is "
            f"exactly the case a plausible guess would get wrong."
        )

    return {
        "part": name,
        "source": f"{source.as_posix()}:{line}",
        "draft": True,
        "format": match.group("fmt"),
        "fields": [_classify(arg) for arg in args],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parts-dir", type=pathlib.Path, default=PARTS_DIR)
    parser.add_argument("--out", type=pathlib.Path, help="write one JSON per part here")
    parser.add_argument("--part", help="draft only this part name")
    args = parser.parse_args(argv)

    try:
        registry = part_names(args.parts_dir)
    except DraftError as exc:
        print(f"draft_part_schemas: {exc}", file=sys.stderr)
        return 2

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    drafted = failed = 0
    for source, name in sorted(registry.items(), key=lambda kv: kv[1]):
        if args.part and name != args.part:
            continue
        try:
            schema = draft(source, name)
        except DraftError as exc:
            failed += 1
            print(f"SKIP {name}: {exc}", file=sys.stderr)
            continue
        drafted += 1
        if args.out:
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            (args.out / f"{slug}.json").write_text(
                json.dumps(schema, indent=2) + "\n", encoding="utf-8"
            )
        else:
            print(json.dumps(schema, indent=2))

    print(
        f"draft_part_schemas: {drafted} drafted, {failed} need hand authoring",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
