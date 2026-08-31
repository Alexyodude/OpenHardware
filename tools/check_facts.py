#!/usr/bin/env python3
# OpenHardware - claims living documents make about this tree, recomputed.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""A count restated in prose is recomputed on every run, so it fails a check
instead of waiting for a reader to notice.

tools/DUPLICATION.md is the survey this table came from and the backlog of
what is not yet here. Two shapes live in this file:

- **Derived facts** (the FACTS table): the document states a number or a name
  that the tree can compute. The tree is the source; the prose is compared to
  it. Not in the table means not watched.

- **Anchored claims** (the ANCHORS table): the document describes what a
  function does, and only a human can say whether the description survives an
  edit to the function. The hash of the function's source at the moment a
  human last confirmed the claim lives in tools/facts_store.json. When the
  source moves, the claim reports STALE until someone re-reads both sides:

      python tools/check_facts.py --confirm claude-md:is-mask-film

  There is deliberately no --confirm-all. The one action that must stay
  expensive is clearing a stale flag without looking.

Every extractor complains when its pattern finds nothing: a claim that can no
longer be found is a dead row, not a passing one. A watched document that does
not exist is likewise a finding — a check that skips its missing input has
switched itself off.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess
import sys
import tomllib

try:
    from tools.stale import Store, anchored, listed_but_missing
except ModuleNotFoundError:  # pragma: no cover - only when run as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from stale import Store, anchored, listed_but_missing

try:
    from tools.rules_meta import load_rules
except ModuleNotFoundError:  # pragma: no cover - only when run as a script
    from rules_meta import load_rules

ROOT = pathlib.Path(__file__).resolve().parents[1]
STORE_PATH = ROOT / "tools" / "facts_store.json"

#: Word-numerals as this repository's prose writes them. A digit string is
#: also accepted, so an editor who writes "8 suites" is still checked.
_UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}


def as_number(token: str) -> int:
    """'twenty-six' -> 26, 'Seven' -> 7, '12' -> 12. Raises on anything else."""
    word = token.strip().lower().rstrip(".,;:")
    if word.isdigit():
        return int(word)
    if word in _UNITS:
        return _UNITS[word]
    if word in _TENS:
        return _TENS[word]
    tens, dash, unit = word.partition("-")
    if dash and tens in _TENS and unit in _UNITS:
        return _TENS[tens] + _UNITS[unit]
    raise ValueError(f"not a number this checker can read: {token!r}")


def _flat(text: str) -> str:
    """Whitespace-normalised, so a sentence is findable however it wraps."""
    return " ".join(text.split())


def _dead(doc: str, what: str) -> list[str]:
    return [
        f"{doc}: the {what} sentence can no longer be found — "
        f"the pattern is dead, and a dead row is not a passing one"
    ]


# --- computed values ---------------------------------------------------------


def _precommit_block(text: str) -> str | None:
    match = re.search(r"## Before you commit\s+```bash\n(.*?)```", text, re.S)
    return match.group(1) if match else None


def _block_checkers(block: str) -> list[str]:
    return re.findall(r"python (tools/check_\w+\.py)", block)


def _armed_script_checkers() -> set[str]:
    out = set()
    for rule in load_rules(ROOT / "rules"):
        for mech in rule.mechanisms:
            if mech.tier == "SCRIPT-ENFORCED" and mech.armed and mech.checker:
                out.add(mech.checker)
    return out


def _module_tuple_len(path: pathlib.Path, name: str) -> int:
    """How many elements a module-level tuple/list literal holds, by ast."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign)
            else node.targets if isinstance(node, ast.Assign) else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                return len(node.value.elts)
    raise ValueError(f"{path}: no module-level assignment to {name}")


def _model_and_composed_boards() -> tuple[set[str], set[str]]:
    """Board names out of import_3d_model's MODELS and COMPOSED, by ast."""
    path = ROOT / "tools" / "import_3d_model.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    models: set[str] = set()
    composed: set[str] = set()
    for node in tree.body:
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign)
            else node.targets if isinstance(node, ast.Assign) else []
        )
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "MODELS":
                for call in node.value.elts:
                    for kw in call.keywords:
                        if kw.arg == "boards":
                            models |= {ast.literal_eval(e) for e in kw.value.elts}
            elif target.id == "COMPOSED":
                composed |= {ast.literal_eval(row.elts[0]) for row in node.value.elts}
    if not models or not composed:
        raise ValueError(f"{path}: MODELS or COMPOSED not found or empty")
    return models, composed


def _catalogue_boards() -> set[str]:
    boards = {
        json.loads(p.read_text(encoding="utf-8"))["board"]
        for p in sorted((ROOT / "webui" / "boards").glob("*.json"))
    }
    if not boards:
        raise ValueError("webui/boards/ holds no board JSON at all")
    return boards


# --- the facts ---------------------------------------------------------------


def precommit_checkers(text: str) -> list[str]:
    block = _precommit_block(text)
    if block is None:
        return _dead("CLAUDE.md", "'Before you commit' block")
    listed = set(_block_checkers(block))
    armed = _armed_script_checkers()
    out = []
    for missing in sorted(armed - listed):
        out.append(
            f"CLAUDE.md: {missing} is armed SCRIPT-ENFORCED in rules/ "
            f"but the 'Before you commit' block does not run it"
        )
    for extra in sorted(listed - armed):
        out.append(
            f"CLAUDE.md: the 'Before you commit' block runs {extra}, "
            f"which no armed rule declares — retired, or never registered"
        )
    return out


def source_skippers(text: str) -> list[str]:
    match = re.search(
        r"The first (\S+) checkers need a PICSimLab \*\*source\*\* checkout",
        _flat(text),
    )
    if not match:
        return _dead("CLAUDE.md", "'first N checkers need a source checkout'")
    block = _precommit_block(text)
    if block is None:
        return _dead("CLAUDE.md", "'Before you commit' block")
    listed = _block_checkers(block)
    skippers = [
        c for c in listed
        if (ROOT / c).exists()
        and "no PICSimLab source checkout" in (ROOT / c).read_text(encoding="utf-8")
    ]
    out = []
    claimed = as_number(match.group(1))
    if claimed != len(skippers):
        out.append(
            f"CLAUDE.md: says the first {claimed} checkers skip without a "
            f"source checkout; {len(skippers)} do: {', '.join(skippers)}"
        )
    if listed[: len(skippers)] != skippers:
        out.append(
            f"CLAUDE.md: the source-needing checkers are not the first "
            f"{len(skippers)} listed — the block runs {listed[:len(skippers)]}, "
            f"the skippers are {skippers}"
        )
    return out


def testpaths_count(text: str) -> list[str]:
    match = re.search(r"points `testpaths` at the (\S+) suites", _flat(text))
    if not match:
        return _dead("CLAUDE.md", "'testpaths at the N suites'")
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    actual = len(config["tool"]["pytest"]["ini_options"]["testpaths"])
    claimed = as_number(match.group(1))
    if claimed != actual:
        return [
            f"CLAUDE.md: says testpaths names {claimed} suites; "
            f"pyproject.toml names {actual}"
        ]
    return []


def sample_count(text: str) -> list[str]:
    match = re.search(r"step and run and (\S+) sample programs", _flat(text))
    if not match:
        return _dead("CLAUDE.md", "'N sample programs'")
    actual = _module_tuple_len(ROOT / "webui" / "emulator.py", "SAMPLES")
    claimed = as_number(match.group(1))
    if claimed != actual:
        return [
            f"CLAUDE.md: says {claimed} sample programs; "
            f"webui/emulator.py SAMPLES holds {actual}"
        ]
    return []


def board_model_split(text: str) -> list[str]:
    flat = _flat(text)
    match = re.search(
        r"(\S+) of the (\S+) boards then draw a vendor file instead of an "
        r"extruded footprint: \*\*(\S+) from Seeed's own mechanical model\*\* "
        r"and \*\*(\S+) composed\*\*",
        flat,
    )
    if not match:
        return _dead("CLAUDE.md", "'N of the M boards draw a vendor file'")
    left = re.search(r"The one left is `([^`]+)`", flat)
    if not left:
        return _dead("CLAUDE.md", "'The one left is …'")

    models, composed = _model_and_composed_boards()
    boards = _catalogue_boards()
    out = []
    for phantom in sorted((models | composed) - boards):
        out.append(
            f"tools/import_3d_model.py names {phantom!r}, "
            f"which webui/boards/ does not hold"
        )
    overlap = models & composed
    if overlap:
        out.append(
            f"MODELS and COMPOSED overlap on {sorted(overlap)} — "
            f"'thirteen and twelve' double-counts them"
        )
    uncovered = boards - models - composed
    checks = (
        ("boards drawing a vendor file", as_number(match.group(1)),
         len((models | composed) & boards)),
        ("boards in webui/boards/", as_number(match.group(2)), len(boards)),
        ("from Seeed's own mechanical model", as_number(match.group(3)),
         len(models & boards)),
        ("composed from a published PCB", as_number(match.group(4)),
         len(composed & boards)),
    )
    for what, claimed, actual in checks:
        if claimed != actual:
            out.append(f"CLAUDE.md: says {claimed} {what}; the tree says {actual}")
    if uncovered != {left.group(1)}:
        out.append(
            f"CLAUDE.md: says the one board left out is {left.group(1)!r}; "
            f"the uncovered set is {sorted(uncovered)}"
        )
    return out


def kicad_url_lives_once(text: str) -> list[str]:
    claim = re.search(
        r"`KICAD_3D` in `tools/import_3d_model\.py` is the one place "
        r"that URL lives",
        _flat(text),
    )
    if not claim:
        return _dead("CLAUDE.md", "'KICAD_3D is the one place that URL lives'")
    # Assembled rather than written out, so this file is not itself the
    # second home it exists to find. Spelling the literal here made the check
    # fail on itself the moment it was staged -- the same lesson
    # check_licenses records about scanning whole files rather than headers.
    # Excluding this path instead would have been a special case that blinds
    # the check to a real copy landing in it.
    needle = "gitlab.com/kicad/libraries/" + "kicad-" + "packages3D"
    result = subprocess.run(
        ["git", "grep", "-l", needle],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    holders = sorted(line.strip() for line in result.stdout.splitlines() if line.strip())
    if holders != ["tools/import_3d_model.py"]:
        return [
            f"CLAUDE.md: says the KiCad GitLab URL lives in one place; "
            f"git grep finds it in {holders or 'no tracked file at all'}"
        ]
    return []


def schema_file_count(text: str) -> list[str]:
    match = re.search(r"webui/parts/schemas/\*\.json` \((\d+) files\)", text)
    if not match:
        return _dead("PROVENANCE.md", "'(N files)' schema count")
    actual = len(list((ROOT / "webui" / "parts" / "schemas").glob("*.json")))
    claimed = int(match.group(1))
    if claimed != actual:
        return [
            f"PROVENANCE.md: says {claimed} schema files; "
            f"webui/parts/schemas/ holds {actual}"
        ]
    return []


def sst_case_count(text: str) -> list[str]:
    mentions = re.findall(r"\b(\S+) (?:test cases|committed cases)\b", _flat(text))
    if not mentions:
        return _dead("PROVENANCE.md", "'N test cases' / 'N committed cases'")
    actual = sum(
        len(json.loads(p.read_text(encoding="utf-8")))
        for p in sorted((ROOT / "tests" / "fixtures" / "sst8088").glob("*.json"))
    )
    out = []
    for token in mentions:
        claimed = as_number(token)
        if claimed != actual:
            out.append(
                f"PROVENANCE.md: says {claimed} SST8088 cases; "
                f"tests/fixtures/sst8088/ holds {actual}"
            )
    return out


#: (id, document, what drift it catches, check). **Not in this table means
#: not watched** — tools/DUPLICATION.md holds the backlog. Every check takes
#: the document's text and returns complaints; a pattern that matches nothing
#: must complain, never pass.
FACTS: list[tuple[str, str, str, object]] = [
    ("claude-md:precommit-checkers", "CLAUDE.md",
     "a checker armed in rules/ that the pre-commit list does not run, "
     "or a listed checker no rule declares",
     precommit_checkers),
    ("claude-md:source-skippers", "CLAUDE.md",
     "the 'first N need a source checkout' sentence drifting from the "
     "checkers' own SKIPPED messages",
     source_skippers),
    ("claude-md:testpaths", "CLAUDE.md",
     "a suite added to pyproject.toml without the prose count following",
     testpaths_count),
    ("claude-md:sample-programs", "CLAUDE.md",
     "a sample added to webui/emulator.py without the prose count following",
     sample_count),
    ("claude-md:board-model-split", "CLAUDE.md",
     "a board gaining or losing a vendor model while the 25/26/13/12 "
     "paragraph stands still",
     board_model_split),
    ("claude-md:kicad-url", "CLAUDE.md",
     "a second copy of the KiCad GitLab URL appearing anywhere tracked",
     kicad_url_lives_once),
    ("provenance:schema-count", "PROVENANCE.md",
     "a part schema added or removed without the audit's count following",
     schema_file_count),
    ("provenance:sst-cases", "PROVENANCE.md",
     "the committed SST8088 excerpt growing while 'eleven' stands still",
     sst_case_count),
]

#: (id, file, function). The claim is a CLAUDE.md paragraph *about* the
#: function; the anchor is the function's source when a human last confirmed
#: the paragraph. Re-confirm with --confirm <id> after re-reading both.
ANCHORS: list[tuple[str, str, str]] = [
    ("claude-md:is-mask-film", "tools/import_3d_model.py", "is_mask_film"),
    ("claude-md:mark-turns", "tools/compose_board_3d.py", "mark_turns"),
]


def function_source(path: pathlib.Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(text, node)
            if segment:
                return segment
    raise ValueError(f"{path}: no function named {name}")


def run_facts(root: pathlib.Path = ROOT) -> list[str]:
    """Every fact row against its document. Missing documents are findings."""
    complaints = list(listed_but_missing(root, sorted({doc for _, doc, _, _ in FACTS})))
    for _, doc, _, check in FACTS:
        path = root / doc
        if not path.exists():
            continue  # already reported by listed_but_missing, loudly
        complaints.extend(check(path.read_text(encoding="utf-8")))
    return complaints


def run_anchors(store: Store) -> list[str]:
    items = {
        ident: function_source(ROOT / file, name)
        for ident, file, name in ANCHORS
    }
    return anchored(store, items)


def confirm(ident: str) -> int:
    for anchor_id, file, name in ANCHORS:
        if anchor_id == ident:
            store = Store(STORE_PATH)
            store.confirm(ident, function_source(ROOT / file, name),
                          file=file, function=name)
            store.save()
            print(f"check_facts: {ident} re-anchored to {file}:{name} as it is now")
            return 0
    print(f"check_facts: no anchor named {ident!r}; "
          f"the anchors are {', '.join(a for a, _, _ in ANCHORS)}",
          file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--confirm":
        if len(args) != 2:
            print("usage: check_facts.py --confirm <id>", file=sys.stderr)
            return 2
        return confirm(args[1])
    if args:
        print(f"check_facts: unknown arguments {args!r}", file=sys.stderr)
        return 2

    complaints = run_facts()
    notes: list[str] = []
    for line in run_anchors(Store(STORE_PATH)):
        # Per stale.anchored: STALE fails, never-reviewed only reports.
        (notes if line.startswith("unanchored") else complaints).append(line)

    for line in notes:
        print(f"check_facts: {line}", file=sys.stderr)
    for line in complaints:
        print(f"check_facts: {line}", file=sys.stderr)
    if complaints:
        print(f"check_facts: {len(complaints)} claim(s) no longer true of the "
              f"tree; see tools/DUPLICATION.md", file=sys.stderr)
        return 1
    print(f"check_facts: OK ({len(FACTS)} facts derived, "
          f"{len(ANCHORS)} anchors held)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
