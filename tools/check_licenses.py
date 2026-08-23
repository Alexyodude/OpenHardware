#!/usr/bin/env python3
# OpenHardware - verify every file states the licence it is actually under.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Checker for rules/licence-hygiene.md.

This repository is MIT. It was extracted from a GPL-2-or-later fork of
PICSimLab, and three trees inside it are still not MIT. The whole risk lives in
that sentence: a header saying the wrong thing is worse than no header, because
someone downstream will believe it.

So there are three checks, and each guards a different way of being wrong.

## 1. Our source says MIT

Every source file outside the exempt trees carries
``SPDX-License-Identifier: MIT``. Machine-readable on purpose -- the previous
GPL boilerplate was three lines of prose that had to be pattern-matched, and
matching prose is how the old `find_v2_only` ended up asserting the *absence*
of a bad header rather than the presence of a good one.

## 2. Our source does not say GPL

A GPL grant anywhere outside ``patches/`` means one of two things, and both
need a person: a header the relicense missed, or code copied in from upstream
that should not have been. Neither is safe to leave.

This is the check that would have caught the relicense being half-done.

## 3. Patches say GPL, and never MIT

``patches/`` holds diffs against PICSimLab's GPL source. A diff is a derivative
of what it patches, so those files are GPL-2-or-later no matter what the rest
of the repository is. Labelling one MIT would be a licence claim we have no
right to make, so it is checked in both directions.

## Headers, not prose

Checks 1 and 2 read only the **leading comment block**, not the whole file.
A licence claim lives in the header; prose further down discusses licences,
and this module's own docstring names the GPL repeatedly. Scanning whole files
made this checker fail on itself, which is how the distinction got drawn.

## What is exempt, and why it is a directory rule

``webui/static/vendor/`` is three.js (MIT, (c) three.js authors) and
``tests/fixtures/`` is an excerpt of SingleStepTests/8088 (MIT, (c) Daniel
Balsom). Third-party source keeps the header it shipped with. Excluding the
directory rather than listing files means the next vendored dependency is
covered without editing this file -- and a dependency arriving with no
exclusion is a licence question for a person, not a header to rewrite.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

#: Directories whose contents are not ours to label. See the module docstring.
THIRD_PARTY = ("webui/static/vendor/", "tests/fixtures/")

#: Diffs against GPL source. GPL-2-or-later, checked in both directions.
PATCH_DIR = "patches/"

SOURCE_SUFFIXES = frozenset(
    {".c", ".cc", ".cpp", ".h", ".hpp", ".py", ".js", ".css", ".html", ".sh"}
)

SPDX_MIT = "SPDX-License-Identifier: MIT"
_GPL = "GNU General Public License"
_HEAD_BYTES = 4000
_HEAD_LINES = 40


class LicenceError(Exception):
    """There was nothing to check, which is never a pass."""


def is_third_party(rel: str) -> bool:
    """True for source kept verbatim from someone else."""
    return rel.replace("\\", "/").startswith(THIRD_PARTY)


def is_patch(rel: str) -> bool:
    """True for anything under patches/."""
    return rel.replace("\\", "/").startswith(PATCH_DIR)


def leading_comment_block(text: str) -> str:
    """The comment block at the very top of a file, and nothing after it.

    Stops at the first line that is not blank, a shebang, a doctype, a line
    comment, or inside a block comment. For Python that is the module
    docstring; for JS and CSS the first statement or rule; for HTML the first
    element after the header comment.
    """
    kept: list[str] = []
    in_block = False
    for line in text.splitlines()[:_HEAD_LINES]:
        stripped = line.strip()

        if in_block:
            kept.append(line)
            if "*/" in stripped or "-->" in stripped:
                in_block = False
            continue

        if not stripped:
            kept.append(line)
            continue
        if stripped.startswith(("#", "//")) or stripped.lower().startswith("<!doctype"):
            kept.append(line)
            continue
        if stripped.startswith(("/*", "<!--")):
            kept.append(line)
            if not (stripped.endswith("*/") or stripped.endswith("-->")):
                in_block = True
            continue
        break
    return "\n".join(kept)


def _header(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")[:_HEAD_BYTES]
    return leading_comment_block(text)


def _whole(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[:_HEAD_BYTES]


def _candidates(root: pathlib.Path) -> list[pathlib.Path]:
    """Files to consider: what git tracks, or everything if this is not a repo.

    **Tracked, not present.** An earlier version walked the filesystem with
    `rglob`, which meant it judged files this repository does not own. It
    found 26 problems the moment `.claude/` was installed from
    `Alexyodude/claude-template` -- 151 gitignored files, none of them ours to
    label, every report a false one.

    A licence header is a claim this repository makes about code it
    distributes. It distributes what it tracks. So git decides the set, and an
    ignored file is not merely skipped but genuinely out of scope.

    The `rglob` fallback is for the tmp_path directories the tests build,
    which are not repositories.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        tracked = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if tracked:
            return [root / rel for rel in tracked]
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
        pass
    return [path for path in root.rglob("*") if ".git" not in path.parts]


def _ours(root: pathlib.Path = pathlib.Path(".")) -> list[pathlib.Path]:
    """Every source file this repository owns and must label itself."""
    return sorted(
        path
        for path in _candidates(root)
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and not is_third_party(path.relative_to(root).as_posix())
        and not is_patch(path.relative_to(root).as_posix())
    )


def missing_mit(root: pathlib.Path = pathlib.Path(".")) -> list[pathlib.Path]:
    """Our source files that do not carry the SPDX MIT identifier."""
    paths = _ours(root)
    if not paths:
        raise LicenceError(f"{root}: no source files to scan")
    return [path for path in paths if SPDX_MIT not in _header(path)]


def stray_gpl(root: pathlib.Path = pathlib.Path(".")) -> list[pathlib.Path]:
    """Our source files still claiming the GPL. See docstring section 2."""
    paths = _ours(root)
    if not paths:
        raise LicenceError(f"{root}: no source files to scan")
    return [path for path in paths if _GPL in _header(path)]


def mislabelled_patches(root: pathlib.Path = pathlib.Path(".")) -> list[pathlib.Path]:
    """Anything under patches/ claiming MIT, or a README that omits the GPL.

    The patch files are diffs and carry no header of their own, so what is
    actually pinned is that the directory's README states the licence and that
    nothing in there claims MIT.
    """
    directory = root / PATCH_DIR.rstrip("/")
    if not directory.is_dir():
        return []

    offenders = [
        path
        for path in sorted(directory.rglob("*"))
        if path.is_file() and SPDX_MIT in _whole(path)
    ]

    # Prose, so read whole rather than as a header block.
    readme = directory / "README.md"
    if not readme.is_file() or _GPL not in _whole(readme):
        offenders.append(readme)
    return offenders


def main() -> int:
    root = pathlib.Path(".")
    try:
        missing = missing_mit(root)
        stray = stray_gpl(root)
        patches = mislabelled_patches(root)
    except LicenceError as exc:
        print(f"check_licenses: {exc}", file=sys.stderr)
        return 2

    for path in missing:
        print(f"{path}: no '{SPDX_MIT}' header", file=sys.stderr)
    for path in stray:
        print(
            f"{path}: claims the GPL in its header, but only patches/ may. "
            f"Either the relicense missed it, or upstream code was copied in.",
            file=sys.stderr,
        )
    for path in patches:
        print(
            f"{path}: patches/ is GPL-2-or-later and must not claim MIT; "
            f"patches/README.md must state the licence",
            file=sys.stderr,
        )

    total = len(missing) + len(stray) + len(patches)
    if total:
        print(
            f"check_licenses: {total} problem(s), per "
            f"rules/licence-hygiene.md",
            file=sys.stderr,
        )
        return 1
    print(f"check_licenses: OK ({len(_ours(root))} files carry {SPDX_MIT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
