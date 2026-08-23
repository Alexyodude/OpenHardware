# OpenHardware - fixtures for the native core suite.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Build the core once per session, or skip the suite loudly.

The core is C++, so this suite needs a compiler. A contributor working on the
Python side may not have one, and CI on a platform we have not wired up may
not either. Neither should fail the run -- but neither may pass it silently,
so the skip names the reason and the command that fixes it.

Building is session-scoped: `tools/build_core.py` is a no-op once the library
exists, but the vcvarsall environment capture on Windows costs a second or two
and there is no reason to pay it per test.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from core.i8086 import abi  # noqa: E402  (needs the path insert above)


@pytest.fixture(scope="session")
def library():
    """The loaded shared library, or skip with the reason."""
    try:
        return abi.load()
    except abi.AbiError as exc:
        pytest.skip(f"i8086 core unavailable: {exc}")


@pytest.fixture
def cpu(library):
    """A fresh processor per test, freed afterwards.

    Per test rather than per session: these tests write memory and set
    registers, and a shared megabyte would make them order-dependent in a way
    that only shows up when one is run alone.
    """
    with abi.Cpu() as instance:
        yield instance
