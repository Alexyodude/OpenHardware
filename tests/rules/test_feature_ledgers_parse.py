# OpenHardware — every real feature ledger must parse.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Closes the gap left by `test_ledger.py`.

`test_ledger.py` exercises `parse_ledger` against synthetic rows in
`tmp_path`. Nothing anywhere parses a real file under `docs/features/`, so a
malformed ledger merged tomorrow would be invisible to CI: `tools/ledger.py`
is armed at PARSER-ENFORCED, but an armed parser nobody calls on real data
enforces nothing.

`docs/features/README.md` contains an example table today, so it is included
here rather than excluded -- it documents the ledger format and must
therefore be valid itself, which is a property worth pinning.
"""

from __future__ import annotations

import pathlib

from tools.ledger import parse_ledger

REPO = pathlib.Path(__file__).resolve().parents[2]
FEATURES_DIR = REPO / "docs" / "features"


def test_every_feature_ledger_parses():
    paths = sorted(FEATURES_DIR.glob("*.md"))

    # A vacuous pass here is exactly the failure mode this project exists to
    # avoid: an empty loop over zero files "succeeds" without checking
    # anything. If the ledger directory is ever emptied out, this must fail
    # loudly rather than report a false green.
    assert paths, f"{FEATURES_DIR}: no ledger files found to parse"

    failures = []
    for path in paths:
        try:
            parse_ledger(path)
        except Exception as exc:  # noqa: BLE001 -- report every parse failure, not just the first
            failures.append(f"{path}: {exc}")

    assert not failures, "ledgers failed to parse:\n" + "\n".join(failures)
