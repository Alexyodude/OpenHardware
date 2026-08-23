# OpenHardware — locate the PICSimLab installation this project drives.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Resolve where PICSimLab lives, because it is no longer in this tree.

OpenHardware is a **client** of PICSimLab, not a fork of it. It speaks the
rcontrol TCP protocol (`webui/rcontrol.py`) and reads the board and part art
that a PICSimLab install already ships (`webui/assets.py`). Neither of those
requires PICSimLab's source to be vendored here, and vendoring it is what this
module exists to avoid: a 89 MB tree of someone else's GPL-2-or-later C++,
carried forever, diverging quietly.

So every path into PICSimLab goes through here, and there is exactly one
resolution order. See `docs/picsimlab-reference.md`.

## Two roots, deliberately separate

`install_root()` finds `share/` — board and part artwork. A *binary* install
has this, so the web UI runs against a packaged PICSimLab with no source
checkout anywhere.

`source_root()` finds `src/` — the C++ itself. Only a source checkout has it,
and only the dev-time rule checkers want it: `tools/check_board_contract.py`
reads `src/lib/board.h`, `tools/draft_part_schemas.py` scrapes
`src/parts/*.cc`. Keeping them apart is what lets a user run the UI without
ever cloning upstream, while CI still gets to check our schemas against the
source they were read from.

A checker that needs source and cannot find it must **skip and say so**, never
pass quietly. A silent skip is how a checker stops checking without anyone
noticing, which is the failure `.claude/rules/` exists to prevent.
"""

from __future__ import annotations

import os
import pathlib

#: Overrides everything. Set to a PICSimLab checkout or install prefix.
ENV_VAR = "PICSIMLAB_ROOT"

#: Searched in order, relative to this repository's parent directory. The
#: first name is the one `docs/picsimlab-reference.md` tells you to clone, and
#: the `-reference` suffix is load-bearing: it says read-only, not a fork you
#: are meant to commit to.
SIBLING_NAMES = ("picsimlab-reference", "picsimlab")

#: What proves a directory is a PICSimLab root rather than an empty folder
#: someone created with the right name.
INSTALL_MARKER = pathlib.Path("share") / "boards"
SOURCE_MARKER = pathlib.Path("src") / "lib" / "board.h"


class PicsimlabNotFound(Exception):
    """PICSimLab is not where any of the documented locations say it is."""


def repo_root() -> pathlib.Path:
    """This repository's top directory."""
    return pathlib.Path(__file__).resolve().parent.parent


def _candidates(explicit: pathlib.Path | None) -> list[pathlib.Path]:
    if explicit is not None:
        return [pathlib.Path(explicit).expanduser().resolve()]

    from_env = os.environ.get(ENV_VAR)
    if from_env:
        # An explicitly set variable is an instruction, not a hint: if it is
        # wrong the caller wants to hear that, not to have a sibling silently
        # used instead and a stale tree checked for the next hour.
        return [pathlib.Path(from_env).expanduser().resolve()]

    parent = repo_root().parent
    return [parent / name for name in SIBLING_NAMES]


def _resolve(marker: pathlib.Path, what: str, explicit) -> pathlib.Path:
    tried = _candidates(explicit)
    for candidate in tried:
        if (candidate / marker).exists():
            return candidate

    listing = "\n".join(f"  {path}" for path in tried)
    raise PicsimlabNotFound(
        f"no PICSimLab {what} found (looked for {marker.as_posix()} under):\n"
        f"{listing}\n"
        f"Set ${ENV_VAR}, or clone the reference beside this repo:\n"
        f"  git clone https://github.com/lcgamboa/picsimlab "
        f"{repo_root().parent / SIBLING_NAMES[0]}\n"
        f"See docs/picsimlab-reference.md."
    )


def install_root(explicit: pathlib.Path | None = None) -> pathlib.Path:
    """Root holding `share/boards` — a binary install or a source checkout."""
    return _resolve(INSTALL_MARKER, "install", explicit)


def source_root(explicit: pathlib.Path | None = None) -> pathlib.Path:
    """Root holding `src/lib/board.h` — a source checkout only."""
    return _resolve(SOURCE_MARKER, "source checkout", explicit)


def find_install(explicit: pathlib.Path | None = None) -> pathlib.Path | None:
    """`install_root()` or None. For callers that degrade rather than fail."""
    try:
        return install_root(explicit)
    except PicsimlabNotFound:
        return None


def find_source(explicit: pathlib.Path | None = None) -> pathlib.Path | None:
    """`source_root()` or None. For checkers that must skip, loudly."""
    try:
        return source_root(explicit)
    except PicsimlabNotFound:
        return None
