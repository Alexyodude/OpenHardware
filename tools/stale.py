# OpenHardware - the staleness store and its three comparators.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The store and the three comparators. ~150 lines, meant to be read and edited.

This is deliberately not a library. Copy it into `tools/`, delete what you do not
need, and change what does not fit. A dependency you cannot read is a dependency
you will trust when it is wrong -- which is the failure this whole method exists
to prevent.

    from stale import anchored, content_key, newer_than, Store
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def key_of(text: str) -> str:
    """The address of a piece of text. 16 hex chars is ~64 bits: plenty.

    Normalise first, or trivial reflows will read as edits. Normalise *too*
    hard and real edits stop registering -- collapsing whitespace is right,
    lower-casing is not.
    """
    return hashlib.sha1(" ".join(text.split()).encode("utf-8")).hexdigest()[:16]


class Store:
    """A JSON file mapping an id to {"hash": …, plus whatever you need}.

    The hash is **the source text when a human last confirmed the entry**, not
    when it was generated. That distinction is the entire point: generation is
    cheap and can be redone, belief cannot.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict = json.loads(self.path.read_text(encoding="utf-8")) \
            if self.path.exists() else {}

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")

    def stale(self, ident: str, source_text: str) -> bool:
        e = self.data.get(ident)
        return bool(e) and e.get("hash") != key_of(source_text)

    def unanchored(self, ident: str) -> bool:
        return ident not in self.data

    def confirm(self, ident: str, source_text: str, **fields) -> None:
        """Record that a human has re-read this and it still holds.

        Never expose a `confirm_all`. The one action that must stay expensive is
        clearing a stale flag without looking.
        """
        self.data.setdefault(ident, {}).update(hash=key_of(source_text), **fields)


# --- shape 1: anchored -------------------------------------------------------

def anchored(store: Store, items: dict[str, str]) -> list[str]:
    """`items` is {id: current source text}. Returns complaints.

    STALE fails; UNANCHORED only reports. A backlog of never-reviewed entries
    on day one would drown the one real hit -- and a check whose output is
    mostly noise gets ignored, which loses the signal too.
    """
    out = []
    for ident, text in sorted(items.items()):
        if store.stale(ident, text):
            out.append(f"STALE       {ident} — its source changed since this was confirmed")
        elif store.unanchored(ident):
            out.append(f"unanchored  {ident} — never reviewed")
    return out


# --- shape 2: content-addressed ---------------------------------------------

MISSING = "⟨untranslated⟩"


def content_build(blocks: list[str], store: dict[str, str]) -> tuple[list[str], list[str]]:
    """Pair each source block with its derived text, keyed by the block itself.

    Returns (output, missing). The source is **copied**, never regenerated --
    if the governing text is re-emitted from anywhere but the original, the
    scheme is defeated and the two can differ while every key still matches.
    """
    out, missing = [], []
    for b in blocks:
        k = key_of(b)
        if k in store and store[k]:
            out.append(store[k])
        else:
            out.append(MISSING)
            missing.append(b.strip().splitlines()[0][:60] if b.strip() else "(blank)")
        out.append(b)
    return out, missing


def content_verify(built: str, blocks: list[str]) -> list[str]:
    """Every source block still present verbatim in the built file."""
    return [f"source block altered in the build: {b.strip()[:60]!r}"
            for b in blocks if b.strip() and b not in built]


# --- shape 3: ordered --------------------------------------------------------

def newer_than(artefact: Path, *inputs: Path) -> tuple[bool, str]:
    """The artefact must be at least as new as everything it derives from.

    Get `inputs` from whatever actually knows them. Inferring them from the
    artefact's own name is how you end up comparing a file to itself.
    """
    if not artefact.exists():
        return True, f"{artefact} does not exist"
    at = artefact.stat().st_mtime
    late = [str(i) for i in inputs if i.exists() and i.stat().st_mtime > at]
    return bool(late), (f"{artefact} is older than: {', '.join(late)}" if late
                        else f"{artefact} is current")


def one_copy_only(root: Path, name: str, ignore=(".git", ".build")) -> tuple[bool, str]:
    """Exactly one copy of a file exists in the tree.

    Two copies kept in sync by a check are strictly worse than one copy: the
    check reports divergence only after it has happened. Prefer deleting the
    duplicate, and use this to stop it coming back.
    """
    found = sorted(p for p in root.rglob(name) if not set(p.parts) & set(ignore))
    if not found:
        return True, f"{name} does not exist"
    if len(found) > 1:
        return True, (f"{len(found)} copies of {name}: "
                      + ", ".join(str(p.relative_to(root)) for p in found))
    return False, f"one copy: {found[0].relative_to(root)}"


# --- the thing people forget ------------------------------------------------

def listed_but_missing(root: Path, names: list[str]) -> list[str]:
    """Every watched path still exists.

    Without this, a watch list quietly stops watching whenever a file moves,
    and the run still prints "clean". Call it from every checker that iterates
    a hard-coded list of paths.
    """
    return [f"{n}: LISTED BUT MISSING — no longer being checked. Fix the path; "
            f"do not delete the entry." for n in names if not (root / n).exists()]
