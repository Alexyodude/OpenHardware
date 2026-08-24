#!/usr/bin/env python3
# OpenHardware — which emulation targets can actually be run, right now.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Say which targets are runnable, by looking rather than by being told.

`docs/architectures.md` surveys eighteen chips, and the Targets view in the UI
renders that survey. Not one of those rows says whether you can *run* it — they
are verdicts about what emulating a part would take, which is a different
question with a different answer. Nineteen rows of research beside a Run button
reads as nineteen things you could run, and exactly one of them is true.

So this module answers the narrow question the UI needs before it offers a
choice: **for each target, is there a core, and is it built?**

## Both halves are computed

A hand-kept list of "done" targets is wrong the moment someone adds a core
directory or deletes `build/`, and it is wrong silently. `CLAUDE.md` makes the
same point about the inventory — "an inventory is the document that rots
fastest" — and the board list was moved to a generator for exactly this reason.

So a target exists because `core/<name>/CMakeLists.txt` exists, which is the
same test `tools/build_core.cores()` applies, and it is `READY` because its
library is on disk. Adding a core is adding a directory; building it is what
makes it selectable. Neither fact is written anywhere it could disagree with
itself.

## Why `UNBUILT` is a state and not an absence

A core that exists but is not built is not the same as a core that does not
exist, and collapsing them would produce the worst message in the set: a target
vanishing from the UI because someone deleted `build/`, with nothing on screen
saying so. `UNBUILT` carries the command that fixes it.

There is deliberately no third state here for the surveyed-but-not-started
chips. They are not targets — they are research, they live in
`docs/architectures.md`, and inventing a `Target` for each would put this module
back in the business of maintaining a list of chips.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys

try:
    from tools import build_core
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools import build_core

#: A core with its library on disk. Selectable.
READY = "ready"

#: A core that exists in `core/` but has not been built. Not selectable, and
#: the one state whose `detail` is a command rather than an explanation.
UNBUILT = "unbuilt"


class TargetError(Exception):
    """A target that cannot be selected, and why."""


@dataclasses.dataclass(frozen=True)
class Target:
    """One emulation target and whether it can be run."""

    name: str
    status: str
    library: str | None
    detail: str

    @property
    def selectable(self) -> bool:
        return self.status == READY

    def as_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "selectable": self.selectable,
            "library": self.library,
            "detail": self.detail,
        }


def _repo_relative(path: pathlib.Path) -> str:
    """`build/lib/i8086.dll`, not 78 characters of absolute Windows path.

    These strings are read in a table cell and in a `<select>` tooltip, and the
    absolute form overflowed both — it pushed the row wide enough that the
    command telling you how to fix the problem was scrolled off the right edge.
    Falls back to the absolute path rather than raising, because a build
    directory outside the repository is unusual but not wrong.
    """
    try:
        return path.relative_to(build_core.REPO).as_posix()
    except ValueError:
        return str(path)


def _inspect(name: str) -> Target:
    """One core's status, from the filesystem alone."""
    try:
        path = build_core.library_path(name)
    except build_core.BuildError as exc:
        # A platform this project has no library naming rule for. Reporting it
        # as UNBUILT would send the reader to `build_core.py` to run a build
        # that cannot produce a name, so the reason is carried instead.
        return Target(name, UNBUILT, None, str(exc))

    if path.is_file():
        return Target(name, READY, _repo_relative(path), "built and loadable")
    return Target(
        name,
        UNBUILT,
        None,
        f"no {_repo_relative(path)} — run `python tools/build_core.py`",
    )


def catalogue() -> list[Target]:
    """Every core under `core/`, in a fixed order, with status computed.

    Empty is a legitimate answer here, unlike the collectors in
    `tools/inventory.py` that raise on it. Those describe a repository that
    certainly has tests and files; this describes a `core/` directory that a
    checkout may genuinely not have built yet, and "no targets are ready" is a
    true statement the UI must be able to render.
    """
    return [_inspect(name) for name in build_core.cores()]


def find(name: str) -> Target | None:
    """The named target, or None. Never a guess at what was meant."""
    for target in catalogue():
        if target.name == name:
            return target
    return None


def default_name() -> str | None:
    """The target the UI should start on: the first ready one, else None.

    First *ready*, not first: opening on a target that cannot run, when a
    runnable one is sitting beside it, makes the tool look broken on a machine
    where it works.
    """
    for target in catalogue():
        if target.selectable:
            return target.name
    return None


def require_selectable(name: str) -> Target:
    """The named target, or raise saying precisely why it cannot be selected.

    Selection is refused rather than accepted-and-disabled. "Target selection
    needs targets that are done" is the rule this enforces, and a selected
    target that cannot step is a state every caller would then have to
    remember to check.
    """
    target = find(name)
    if target is None:
        known = ", ".join(t.name for t in catalogue()) or "none"
        raise TargetError(f"no such target: {name!r}. Cores under core/: {known}")
    if not target.selectable:
        raise TargetError(f"target {name!r} is not runnable: {target.detail}")
    return target
