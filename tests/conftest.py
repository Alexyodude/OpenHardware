# OpenHardware - fixtures shared by every suite.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Make the repo root importable, and expose the PICSimLab reference checkout.

PICSimLab is not in this tree. Tests that read its source -- the board
contract, the layering rule, the schema citations -- get its location from the
`upstream` fixture, which **skips rather than fails** when no checkout is
present. A contributor with no clone of upstream can still run everything that
does not need it.

The skip is not silent: pytest reports it by name, and CI clones the reference
so the skip never happens there. See `docs/picsimlab-reference.md`.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from webui import picsimlab  # noqa: E402  (needs the path insert above)


@pytest.fixture(scope="session")
def upstream() -> pathlib.Path:
    """Root of a PICSimLab **source** checkout, or skip the test."""
    root = picsimlab.find_source()
    if root is None:
        pytest.skip(
            f"no PICSimLab source checkout; set ${picsimlab.ENV_VAR} or clone it "
            f"beside this repo (see docs/picsimlab-reference.md)"
        )
    return root
