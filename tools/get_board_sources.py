#!/usr/bin/env python3
# OpenHardware - fetch a hardware source named in the registry.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Fetch one source from `tools/board_sources.py` into `third_party/`.

## Fetch, do not vendor

Downloads land in `third_party/`, which is git-ignored. Nothing fetched here
is ever committed, and that boundary is the whole reason this tool can cover
the market: `rules/licence-hygiene.md` governs what this repository *ships*,
so a vendor whose design files are CC-BY-SA, or under a bespoke grant, or
under terms one of its own repositories forgot to include, can be fetched
without any of that becoming a licence claim we made.

**Size decides, not licence.** This is the precedent the retiring
`tools/get_seeed_hardware.sh` set, and it is worth keeping in the tool that
replaced it. The largest source in the registry is 196,037 KiB, and nearly all
of that is two marketing PNGs per board — pictures of a pinout, not a pinout.
It is MIT, so vendoring it would have been **permitted**. It is fetched
sparsely anyway, because a 191 MiB tree dwarfs the source of this project
several times over and every clone would pay for it. The same judgement is
already recorded for the 2 GB 8088 corpus in `tools/get_8088_tests.sh`.

What is worth fetching and what is deliberately left behind are properties of
each source, so they live in the table as `Fetch.wanted` and `Fetch.skipped`,
with a reason required next to every skip. **No vendor is named in this file**,
and `tests/rules/test_board_sources.py::test_the_fetcher_names_no_vendor` reads
this source and fails if one ever is.

## A fetch that lands nothing is an error

The retiring script counted `.kicad_mod` and `.kicad_sym` after checkout and
refused to report success over an empty tree, because a silent empty fetch
makes the importer report zero boards over zero footprints — which reads
exactly like success. That check was written in terms of one vendor's file
extensions. The generic form is: every directory or file the table asked for
must exist afterwards. It is checked here for every source, on every fetch.

    python tools/get_board_sources.py --list
    python tools/get_board_sources.py <source>
    python tools/get_board_sources.py <source> --all

`--list` prints the names, because naming one here would put a vendor in this
file and the test above would rightly object.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

try:
    from tools.board_sources import Source, SourceError, Transport, source, sources
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    # Same reason `tools/inventory.py` does this: running the file directly
    # puts `tools/` on sys.path rather than the repository root, so the
    # package is not importable. Both invocations work after this.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools.board_sources import Source, SourceError, Transport, source, sources

REPO = pathlib.Path(__file__).resolve().parents[1]


def _git(args: list[str], cwd: pathlib.Path) -> str:
    """Run git, or raise carrying what it said."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise SourceError(
            f"git {' '.join(args)} in {cwd}: {(exc.stderr or '').strip() or exc}"
        ) from exc
    except FileNotFoundError as exc:
        raise SourceError(f"git is required to fetch a source: {exc}") from exc
    return result.stdout


def _clone(url: str, dest: pathlib.Path) -> None:
    """Make a blobless, shallow, unchecked-out clone at `dest`.

    Blobless and `--no-checkout` so that narrowing happens before any file
    content is transferred. Cloning first and narrowing afterwards would
    download everything the table said to skip and then hide it.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(
        [
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            "--depth",
            "1",
            url,
            dest.name,
        ],
        cwd=dest.parent,
    )
    _git(["sparse-checkout", "init", "--cone"], cwd=dest)


def _narrow(dest: pathlib.Path, wanted: tuple[str, ...], everything: bool) -> None:
    """Restrict the working tree to `wanted`, or open it up completely."""
    if everything or not wanted:
        _git(["sparse-checkout", "disable"], cwd=dest)
    else:
        # `ls-tree` answers from the commit, before anything is checked out.
        files = {
            name for name in wanted
            if _git(["ls-tree", "HEAD", "--", name], cwd=dest).split()[1:2] == ["blob"]
        }
        if files:
            # Cone mode takes directories, and every file at the top level
            # with them, so a file on its own is a gitignore-style pattern,
            # its glob characters escaped so that it matches only itself.
            _git(["sparse-checkout", "set", "--no-cone", *(
                "/" + re.sub(r"([\\*?\[])", r"\\\1", name) + ("" if name in files else "/")
                for name in wanted
            )], cwd=dest)
        else:
            _git(["sparse-checkout", "set", "--cone", *wanted], cwd=dest)
    _git(["checkout"], cwd=dest)


def _files_under(dest: pathlib.Path) -> list[pathlib.Path]:
    """Every file in the working tree, ignoring git's own storage."""
    return [
        path
        for path in dest.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(dest).parts
    ]


def _verify(src: Source, dest: pathlib.Path, everything: bool) -> None:
    """Refuse to report success over a tree that did not arrive.

    The generic form of the retiring script's footprint count: whatever the
    table asked for has to be there afterwards. A fetch that silently lands
    nothing is the failure that reads most like success, so it is the one
    checked hardest.
    """
    if not everything and src.fetch.wanted:
        missing = [name for name in src.fetch.wanted if not (dest / name).exists()]
        if missing:
            # What is on disk is not the useful answer: a sparse checkout that
            # matched nothing leaves an empty tree, so reporting it says only
            # "nothing", which is what the caller already knows. The
            # repository's own top level says what the row should have asked
            # for instead.
            top = sorted(
                {
                    line.strip().rstrip("/")
                    for line in _git(
                        ["ls-tree", "--name-only", "HEAD"], cwd=dest
                    ).splitlines()
                    if line.strip()
                }
            )
            raise SourceError(
                f"{src.name}: the table asked for {missing} and the fetch did not "
                f"land them in {dest}. The repository's top level holds "
                f"{top or 'nothing'}. Either {src.fetch.url} has moved them, or "
                f"the row is wrong."
            )
        return

    if not _files_under(dest):
        raise SourceError(
            f"{src.name}: {dest} holds no files after fetching {src.fetch.url}. "
            f"Refusing to report success over an empty tree."
        )


def fetch(src: Source, root: pathlib.Path, everything: bool = False) -> pathlib.Path:
    """Fetch `src` under `root`, and return where it landed.

    Re-running is safe and is how a source is re-narrowed: an existing clone
    is kept and only its working tree is changed. Nothing here deletes a tree
    somebody else's tool is already reading out of.
    """
    if src.fetch.transport is not Transport.GIT_SPARSE:
        raise SourceError(
            f"{src.name} is published as {src.fetch.transport.value}, which this "
            f"tool does not fetch. Download it by hand from {src.fetch.url}, into "
            f"{src.dest(root)}."
        )

    dest = src.dest(root)
    if not (dest / ".git").is_dir():
        _clone(src.fetch.url, dest)
    _narrow(dest, src.fetch.wanted, everything)
    _verify(src, dest, everything)
    return dest


def _describe(src: Source) -> list[str]:
    """One source, as the lines `--list` prints for it."""
    sampled = "  [read from one sampled repository]" if src.licence.sampled else ""
    lines = [
        f"{src.name}",
        f"    vendor     {src.vendor}",
        f"    model      {src.model}",
        f"    size       {src.size}",
        f"    licence    {src.licence.name} over {src.licence.covers}{sampled}",
        f"    transport  {src.fetch.transport.value}",
        f"    url        {src.fetch.url}",
    ]
    lines.append(
        f"    fetches    {', '.join(src.fetch.wanted) if src.fetch.wanted else 'everything'}"
    )
    for path, why in src.fetch.skipped:
        lines.append(f"    skips      {path}: {why}")
    absent = src.absent()
    lines.append(
        f"    publishes no {', '.join(absent)}" if absent
        else "    publishes every artefact class this registry asks about"
    )
    lines.append(f"    cite       {src.cite}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "name", nargs="?", help="the source to fetch; omit with --list"
    )
    parser.add_argument(
        "--list", action="store_true", help="print the registry and fetch nothing"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="everything",
        help="fetch the skipped paths too, reasons and all",
    )
    args = parser.parse_args()

    if args.list:
        for src in sources():
            for line in _describe(src):
                print(line)
            print()
        return 0

    if not args.name:
        parser.error("give a source name, or --list to see them")

    try:
        src = source(args.name)
        dest = fetch(src, REPO, args.everything)
    except SourceError as exc:
        print(f"get_board_sources: {exc}", file=sys.stderr)
        return 2

    files = _files_under(dest)
    print(f"{src.name}: {len(files)} file(s) in {dest.relative_to(REPO).as_posix()}")
    print(f"Licence: {src.licence.name}, {src.licence.covers}.")
    if src.licence.sampled:
        print(
            "  That licence was read from one sampled repository. This vendor "
            "ships one repository per board; re-read it for any other board."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
