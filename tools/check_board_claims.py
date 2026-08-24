#!/usr/bin/env python3
# OpenHardware — verify nothing says a board runs firmware without a test that watched it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Checker for rules/board-claims.md.

`webui/boards/catalogue.py` holds the register: `FIRMWARE_VERIFIED` maps a chip
to the test that watched a real compiled image execute on it. That dict is the
only thing in this repository licensed to say a board runs firmware, and this
checker is what makes it binding on everything outside it.

Five checks, each a different way the claim comes loose from its evidence.

## 1. A chip named beside a run-claim has no test behind it

`unevidenced_chip_claims`. Any surface -- prose, template, script -- where the
words "runs firmware" land on the same line as a chip from `CHIPS` that has no
entry in `FIRMWARE_VERIFIED`. That is the sentence somebody writes when a chip
whose core is built and whose siblings work looks runnable, which is exactly
when it is easiest to believe and hardest to check.

## 2. A code surface makes the claim without ever reading the register

`ungrounded_code_claims`. Check 1 can only see a chip that is spelled out, and
a badge reading "RUNS FIRMWARE" spells out none. So the test here is whether
the file rendering it consults `firmware_verified` anywhere at all. A file that
says it and never asks is saying it from memory.

## 3. The claim is decided by a weaker fact

`claims_decided_by_a_weaker_fact`. `runnable`, `core_built`, `core_exists` and
`described` are facts about this repository -- that a core compiled, that a
description file is present. None of them is a fact about a board. The badge
did once read RUNS FIRMWARE for anything with a built core and a description,
where an empty `samd21.py` would have earned it; this is that mistake, named so
it cannot come back quietly.

## 4. A named test does not exist

`missing_evidence`. A path in the register that is not on disk.

## 5. A named test exists but never loads an image

`evidence_that_never_loads_an_image`. Naming any file satisfies check 4. The
named file has to name a firmware image that exists beside it, read that image
off disk, and step a CPU over it -- all three, in that one file. Evidence you
have to chase through three modules is evidence nobody checks.

**What this does not catch.** It is a check on vocabulary, not on meaning. A
surface that claims a board works while avoiding the word "firmware" passes,
and so does a named test that loads an image and then asserts nothing. The
first is a gap in the phrase table below, and widening it is cheap; the second
is what review is for. Never report a passing run as evidence that a board
works. It proves only that every claim points at a test that touches a real
image.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Exit code meaning "did not run", distinct from 0 (ran, clean) and 1 (found
#: problems). Same convention as the checkers that need a PICSimLab checkout;
#: tools/check_board_contract.py says why collapsing the two is how a suite
#: goes green while checking nothing. Here the missing thing is the register
#: itself: with no catalogue there is nothing to hold the surfaces to.
SKIPPED = 3

#: The register, relative to the repository root.
CATALOGUE = "webui/boards/catalogue.py"

#: The words that assert a board has run something. Deliberately narrow: every
#: entry is a phrase that would be a lie if no image had executed. "runnable",
#: "supported" and "works" are not here, because those are claims about the
#: repository and check 3 is what governs them.
#:
#: `firmware[ -]verified` matches the badge text but **not** the identifier
#: `firmware_verified`, which is the evidence field. A pattern matching both
#: would let every check below be satisfied by the claim itself.
_RUN_CLAIM = re.compile(
    r"\b(?:runs?|running|ran)\s+(?:a\s+|an\s+|the\s+|real\s+|any\s+|compiled\s+)*firmware\b"
    r"|\bfirmware\s+(?:runs?|ran|running|executes?|executed)\b"
    r"|\bfirmware[ -]verified\b",
    re.IGNORECASE,
)

#: A temporal clause is not a claim. "the bit is set before firmware runs"
#: says *when* a register settles; it asserts nothing about this repository
#: running anything.
#:
#: This was found the day the rule was armed, on `webui/boards/samd21.py`,
#: and it is the failure worth remembering: the flagged sentence explained
#: that PM_APBBMASK_PORT is set at power-on, and the sentence immediately
#: after it named the test that turns the claim into a measurement. So the
#: substring match failed the careful author while a sloppier one who phrased
#: it "this board runs firmware" in a docstring would have been caught. A
#: check that fires on the discipline it exists to encourage gets disarmed by
#: whoever it blocks next, and then it protects nothing.
_TEMPORAL = re.compile(
    r"\b(?:before|after|when|whenever|while|until|till|once|unless|if|since|as)\s+"
    r"(?:the\s+|any\s+)?firmware\s+(?:runs?|ran|running|executes?|executed)\b",
    re.IGNORECASE,
)


def _asserts_a_run(line: str) -> bool:
    """True when the line claims firmware runs, not merely when it would."""
    temporal = [m.span() for m in _TEMPORAL.finditer(line)]
    return any(
        not any(start <= m.start() < end for start, end in temporal)
        for m in _RUN_CLAIM.finditer(line)
    )


#: The evidence field. A surface that consults this is deriving the claim
#: rather than asserting it.
_EVIDENCE_FIELD = re.compile(r"\bFIRMWARE_VERIFIED\b|\bfirmware_verified\b")

#: Facts about the repository, which are not facts about a board. Matched only
#: as an attribute or a key, so prose using the word "runnable" is left alone.
_WEAKER_FACT = re.compile(r"""[.\[("']\s*["']?(runnable|core_built|core_exists|described)\b""")

#: How far ABOVE a run-claim a weaker fact still counts as deciding it: the
#: claim line and the two above it. Far enough for a condition on one line and
#: its body on the next, and no farther.
#:
#: It was symmetric at first, and the first thing it caught was the strip
#: counter in `webui/static/emulator.js`, where a `runnable` three lines up
#: decides a different cell entirely. A window that reaches forward, or too far
#: back, reports lines nobody can act on, and a check whose output cannot be
#: acted on is a check that gets switched off.
WINDOW = 2

#: Files a reader learns from. Default-on: a new file is a surface unless it is
#: excluded below, because the opposite default is how a new page ships making
#: an old claim.
SURFACE_SUFFIXES = frozenset(
    {".py", ".js", ".html", ".css", ".md", ".json", ".yml", ".yaml", ".txt"}
)

#: Surfaces where the claim is rendered rather than described. Checks 2 and 3
#: read an expression, so they apply only here.
CODE_SUFFIXES = frozenset({".py", ".js", ".html", ".css"})

#: Directories that are not surfaces, each for its own reason.
#:
#: `third_party` is the one worth spelling out. It is a fetched vendor tree,
#: git-ignored, and the first thing this checker found in it was Seeed saying
#: their DAPLink firmware runs on a SAMD21. It does -- on real silicon. What a
#: vendor says about their own hardware is not this repository claiming its
#: emulator runs anything, and folding the two together would fail the check on
#: documents nobody here can edit.
#:
#: `tests` is the evidence, not the claim. `patches` is upstream code with a
#: diff on it, and its words are upstream ones. `build` is generated. `vendor`
#: and `node_modules` are somebody elses code.
EXCLUDED_DIRS = frozenset(
    {"__pycache__", "node_modules", "vendor", "build", "third_party", "tests", "patches"}
)


def _skip_directory(name: str) -> bool:
    """Dot-directories are tooling, caches and editor state: `.git`, `.omc`,
    `.pytest_cache`, `.venv`, `.vscode`. Naming them one at a time is a list
    that rots, and a machine-local cache turning up in a report is how a
    checker gets ignored."""
    return name.startswith(".") or name in EXCLUDED_DIRS

#: Not surfaces, and each for its own reason. Tickets and handoffs are the
#: record of what was decided and when, and rewriting history to satisfy a
#: present checker is worse than the claim it would remove. Research notes are
#: somebody thinking, not the project speaking.
EXCLUDED_PREFIXES = ("docs/tickets/", "docs/research/", "docs/HANDOFF_")

#: The two files of this rule. A document about a claim has to be able to quote
#: the claim, and a checker has to carry the phrase table it matches on.
NOT_A_SURFACE = frozenset({"rules/board-claims.md", "tools/check_board_claims.py"})

#: What a compiled image is called. A test naming none of these has shown the
#: checker no image.
IMAGE_SUFFIXES = frozenset({".bin", ".elf", ".hex", ".uf2", ".img", ".s19", ".axf"})

#: Reading the image off disk, rather than assembling one in the test.
_READERS = frozenset({"read_bytes"})

#: Executing it.
_STEPPERS = frozenset({"step"})


class ClaimError(Exception):
    """The register could not be read, or a named test could not be parsed."""


def _text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _module_constant(tree: ast.Module, name: str, where: pathlib.Path) -> object:
    """A module-level literal, read without importing the module.

    Parsed rather than imported, because the register must be readable from a
    tree that cannot be imported: a checkout with no built core, or the copy a
    test builds to prove this checker fails.
    """
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target = node.targets[0].id
        if target != name:
            continue
        try:
            return ast.literal_eval(node.value)
        except ValueError as exc:
            raise ClaimError(
                f"{where}: {name} is not a literal and cannot be read without "
                f"importing the module: {exc}"
            ) from exc
    raise ClaimError(f"{where}: no module-level {name}")


def _catalogue_tree(root: pathlib.Path) -> tuple[ast.Module, pathlib.Path]:
    path = root / CATALOGUE
    if not path.is_file():
        raise ClaimError(f"{path}: the register is not there")
    try:
        return ast.parse(_text(path), filename=str(path)), path
    except SyntaxError as exc:
        raise ClaimError(f"{path}: will not parse: {exc}") from exc


def register(root: pathlib.Path | None = None) -> dict[str, str]:
    """`FIRMWARE_VERIFIED` -- chip to the test that watched an image execute."""
    tree, path = _catalogue_tree(REPO if root is None else root)
    value = _module_constant(tree, "FIRMWARE_VERIFIED", path)
    if not isinstance(value, dict):
        raise ClaimError(
            f"{path}: FIRMWARE_VERIFIED is a {type(value).__name__}, not a dict"
        )
    return value


def chips(root: pathlib.Path | None = None) -> list[str]:
    """Every chip name the catalogue knows, in its canonical spelling."""
    tree, path = _catalogue_tree(REPO if root is None else root)
    value = _module_constant(tree, "CHIPS", path)
    if not isinstance(value, dict) or not value:
        raise ClaimError(f"{path}: CHIPS is empty or not a dict; every chip would pass")
    return list(value)


def _chip_pattern(names: list[str]) -> re.Pattern[str]:
    """Chip names, longest first, ending at a delimiter.

    The delimiter guard is the one `catalogue.chip_for` needs and for the same
    reason: without it `ESP32-C6` matches inside `ESP32-C61`, which is a
    different real part.
    """
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(
        rf"(?<![0-9A-Za-z])({alternatives})(?![0-9A-Za-z])", re.IGNORECASE
    )


def surfaces(root: pathlib.Path | None = None) -> list[pathlib.Path]:
    """Every file a reader could learn from, under `root`."""
    root = REPO if root is None else root
    out: list[pathlib.Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _skip_directory(d))
        for name in sorted(filenames):
            path = pathlib.Path(dirpath) / name
            if path.suffix.lower() not in SURFACE_SUFFIXES:
                continue
            rel = path.relative_to(root).as_posix()
            if rel in NOT_A_SURFACE or rel.startswith(EXCLUDED_PREFIXES):
                continue
            out.append(path)
    return sorted(out)


def unevidenced_chip_claims(root: pathlib.Path | None = None) -> list[str]:
    """1. A chip is named beside a run-claim and names no test."""
    root = REPO if root is None else root
    verified = {chip.lower() for chip in register(root)}
    pattern = _chip_pattern(chips(root))

    problems: list[str] = []
    for path in surfaces(root):
        rel = path.relative_to(root).as_posix()
        for number, line in enumerate(_text(path).splitlines(), start=1):
            if not _asserts_a_run(line):
                continue
            for chip in sorted({m.group(1) for m in pattern.finditer(line)}):
                if chip.lower() in verified:
                    continue
                problems.append(
                    f"{rel}:{number}: says {chip} runs firmware, but {chip} names no "
                    f"test in FIRMWARE_VERIFIED: {line.strip()!r}"
                )
    return problems


def ungrounded_code_claims(root: pathlib.Path | None = None) -> list[str]:
    """2. A code surface makes the claim and never reads the register."""
    root = REPO if root is None else root
    problems: list[str] = []
    for path in surfaces(root):
        if path.suffix.lower() not in CODE_SUFFIXES:
            continue
        text = _text(path)
        if _EVIDENCE_FIELD.search(text):
            continue
        rel = path.relative_to(root).as_posix()
        for number, line in enumerate(text.splitlines(), start=1):
            if _asserts_a_run(line):
                problems.append(
                    f"{rel}:{number}: says firmware runs, but nothing in this file "
                    f"reads firmware_verified, so the claim is written down rather "
                    f"than derived: {line.strip()!r}"
                )
                break
    return problems


def claims_decided_by_a_weaker_fact(root: pathlib.Path | None = None) -> list[str]:
    """3. A run-claim sits next to `runnable` and friends, not to the evidence."""
    root = REPO if root is None else root
    problems: list[str] = []
    for path in surfaces(root):
        if path.suffix.lower() not in CODE_SUFFIXES:
            continue
        lines = _text(path).splitlines()
        rel = path.relative_to(root).as_posix()
        for index, line in enumerate(lines):
            if not _asserts_a_run(line):
                continue
            window = "\n".join(lines[max(0, index - WINDOW) : index + 1])
            if _EVIDENCE_FIELD.search(window):
                continue
            weaker = sorted({m.group(1) for m in _WEAKER_FACT.finditer(window)})
            if weaker:
                problems.append(
                    f"{rel}:{index + 1}: run-claim decided by {', '.join(weaker)} with "
                    f"no firmware_verified in the {WINDOW} lines above it. Those are "
                    f"facts about this repository, not about a board: {line.strip()!r}"
                )
    return problems


def missing_evidence(root: pathlib.Path | None = None) -> list[str]:
    """4. The register names a test that is not there."""
    root = REPO if root is None else root
    return [
        f"{chip}: FIRMWARE_VERIFIED names {evidence}, which does not exist under {root}"
        for chip, evidence in sorted(register(root).items())
        if not (root / evidence).is_file()
    ]


def _calls(tree: ast.Module) -> set[str]:
    """Every called name: attributes by attribute, plain functions by name."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
        elif isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def _reads_bytes_off_disk(tree: ast.Module) -> bool:
    if _calls(tree) & _READERS:
        return True
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
            and any(
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and "b" in arg.value
                for arg in node.args[1:]
            )
        ):
            return True
    return False


def _image_names(tree: ast.Module) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and pathlib.PurePosixPath(node.value).suffix.lower() in IMAGE_SUFFIXES
    }


def _found_beside(test: pathlib.Path, name: str) -> bool:
    """Is a file of that name anywhere under the named test's own directory?"""
    basename = pathlib.PurePosixPath(name).name
    return any(candidate.is_file() for candidate in test.parent.rglob(basename))


def evidence_that_never_loads_an_image(root: pathlib.Path | None = None) -> list[str]:
    """5. The named test names no image, or never reads one, or never steps."""
    root = REPO if root is None else root
    problems: list[str] = []
    for chip, evidence in sorted(register(root).items()):
        test = root / evidence
        if not test.is_file():
            continue  # missing_evidence reports it; saying it twice helps nobody.
        try:
            tree = ast.parse(_text(test), filename=str(test))
        except SyntaxError as exc:
            raise ClaimError(
                f"{evidence}: cited as evidence for {chip}, and will not parse: {exc}"
            ) from exc

        named = _image_names(tree)
        on_disk = sorted(name for name in named if _found_beside(test, name))
        why: list[str] = []
        if not named:
            suffixes = ", ".join(sorted(IMAGE_SUFFIXES))
            why.append(f"names no image file (nothing ending in {suffixes})")
        elif not on_disk:
            why.append(
                f"names {sorted(named)} but no such file exists under {test.parent}"
            )
        if not _reads_bytes_off_disk(tree):
            why.append(
                "never reads an image off disk (no .read_bytes(), no binary open())"
            )
        if not (_calls(tree) & _STEPPERS):
            why.append("never executes it (no .step() call)")
        if why:
            problems.append(f"{chip}: {evidence} " + "; ".join(why))
    return problems


CHECKS = (
    ("a chip named beside a run-claim with no test behind it", unevidenced_chip_claims),
    (
        "a code surface claiming firmware runs without reading the register",
        ungrounded_code_claims,
    ),
    (
        "a run-claim decided by a fact about the repository",
        claims_decided_by_a_weaker_fact,
    ),
    ("a named test that does not exist", missing_evidence),
    ("a named test that never loads an image", evidence_that_never_loads_an_image),
)


def main() -> int:
    if not (REPO / CATALOGUE).is_file():
        print(
            f"check_board_claims: SKIPPED - no {CATALOGUE} under {REPO}. There is no "
            f"register of firmware claims, so nothing was checked.",
            file=sys.stderr,
        )
        return SKIPPED

    failed = False
    try:
        for label, check in CHECKS:
            problems = check()
            if not problems:
                continue
            failed = True
            print(f"{label}:", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
        claims = register()
        scanned = len(surfaces())
    except ClaimError as exc:
        print(f"check_board_claims: {exc}", file=sys.stderr)
        return 2

    if failed:
        print(
            "check_board_claims: a board claims to run firmware without a test that "
            "watched it, per rules/board-claims.md",
            file=sys.stderr,
        )
        return 1

    evidence = ", ".join(f"{chip} -> {path}" for chip, path in sorted(claims.items()))
    print(f"check_board_claims: OK ({scanned} surfaces, {len(claims)} claim: {evidence})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
