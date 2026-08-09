# Feature-Strategy Machinery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the meta-layer for the OpenHardware fork of PICSimLab — a feature-derivation skill, five machine-checked rules, and the checkers that arm them.

**Architecture:** Each rule is a markdown file with YAML frontmatter declaring one or more enforcement *mechanisms*, each naming a checker and an `armed` flag. A shared parser (`tools/rules_meta.py`) reads that frontmatter; a meta-guard test fails if any armed mechanism names a checker that does not exist. Checkers are standalone Python scripts that exit non-zero on violation, wired into CI. No simulator code is written.

**Tech Stack:** Python 3.14.3, pytest 9.0.2, PyYAML 6.0.3, git 2.53.0.

## Global Constraints

- **License:** GPL-2-or-later. Every new source file carries the header in `HEADER_TEMPLATE` below, verbatim. Upstream was verified v2-or-later on 2026-08-09 (spec §8.1).
- **Dependencies:** MIT, BSD, or GPL-compatible only. PyYAML is MIT. Apache-2.0 is permitted *only* because upstream is v2-or-later; if Task 3 finds a v2-only header anywhere, Apache-2.0 becomes forbidden and this constraint inverts.
- **Additive-only:** No file that exists at tag `fork-point` (`cd92747b1a04cab56c17f4e9ac35a1406c9935f7`) may be modified. Every file in this plan is new. Local-only ignores go in `.git/info/exclude`, never in upstream's `.gitignore`.
- **Test scope:** Always `pytest tests/rules/ -v`. Never bare `pytest` from the repo root — upstream's `tests/python/test_blink.py` imports the out-of-tree module `PICSimLab_rcontrol` and requires a built binary, so a bare run errors at collection.
- **Branch:** All work on `design/feature-strategy`, which already exists and holds the spec commit.
- **Vacuous-pass ban:** No checker may pass when it has nothing to check. Empty input is an error, not a success. Upstream's `tests/python/test_blink.py:54` demonstrates the failure mode this bans — it catches `ConnectionError`, prints it, and passes.

**HEADER_TEMPLATE** (Python files — first four lines of every new `.py`):

```python
# OpenHardware — <one-line description>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
```

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/rules_meta.py` | Parse rule frontmatter into `Rule`/`Mechanism` objects. Raises on malformed input. |
| `tools/check_layering.py` | Fail if `src/sim_backend/` includes from `parts/` or the UI. |
| `tools/check_licenses.py` | Fail on any v2-only GPL header; require a header on new source files. |
| `tools/check_deltas.py` | Fail if a file existing at `fork-point` was modified without a ledger entry. |
| `tools/check_banned_symbols.py` | Fail if new simulation code calls `rand()`/`time()`/`clock()`. |
| `tools/ledger.py` | Parse feature-ledger markdown tables into `Cell` objects. Raises on malformed rows. |
| `.claude/rules/*.md` | Five rule documents, each with frontmatter declaring its mechanisms. |
| `.claude/skills/feature-strategy/SKILL.md` | The six-phase derivation procedure. |
| `docs/upstream-deltas.md` | Ledger of intentional modifications to upstream files. |
| `tests/rules/*.py` | Tests for every tool above, plus the meta-guard. |
| `CLAUDE.md` | Repo-root pointer that loads the rules into agent context. |
| `.github/workflows/rules.yml` | Runs all checkers and `tests/rules/` on push and PR. |

`tests/rules/` is a new directory rather than files dropped into upstream's `tests/`, which is a make-driven C++ suite. Keeping them separate is what makes the scoped `pytest tests/rules/` command above safe.

**Deviations from the spec's §7 layout, both deliberate:**

| Spec said | Plan does | Why |
|---|---|---|
| `tests/test_rules_are_armed.py` | `tests/rules/test_rules_are_armed.py` | Upstream `tests/` is a make-driven C++ suite with its own `Makefile`; mixing pytest files into it invites a bare `pytest` run that fails at collection |
| two checkers (`check_licenses`, `check_deltas`) | five tools | Spec §6.3, §6.4, and §6.5 each declare an enforcement mechanism without naming its script. `check_layering.py`, `check_banned_symbols.py`, and `ledger.py` are those three scripts; `rules_meta.py` is the shared frontmatter parser they all depend on |

Neither deviation changes what the spec requires — only where the files live and how many of them it takes.

---

### Task 1: Rule metadata parser

**Files:**
- Create: `tools/rules_meta.py`
- Test: `tests/rules/test_rules_meta.py`

**Interfaces:**
- Consumes: nothing (foundation task).
- Produces: `load_rules(rules_dir: pathlib.Path = RULES_DIR) -> list[Rule]`, `parse_rule(path: pathlib.Path) -> Rule`, `RuleParseError`, and frozen dataclasses `Rule(name: str, path: pathlib.Path, mechanisms: tuple[Mechanism, ...])` and `Mechanism(tier: str, checker: str | None, armed: bool, blocked_by: str | None)`. Every later task imports from this module.

- [ ] **Step 1: Write the failing test**

Create `tests/rules/test_rules_meta.py`:

```python
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from tools.rules_meta import Mechanism, RuleParseError, load_rules, parse_rule

VALID = """---
rule: example
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_example.py
    armed: true
---

# Example rule
"""


def write(tmp_path: pathlib.Path, text: str, name: str = "example.md") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_a_valid_rule(tmp_path):
    rule = parse_rule(write(tmp_path, VALID))
    assert rule.name == "example"
    assert rule.mechanisms == (
        Mechanism("SCRIPT-ENFORCED", "tools/check_example.py", True, None),
    )


def test_missing_frontmatter_raises(tmp_path):
    with pytest.raises(RuleParseError, match="no frontmatter"):
        parse_rule(write(tmp_path, "# Just a heading\n"))


def test_unclosed_frontmatter_raises(tmp_path):
    with pytest.raises(RuleParseError, match="not closed"):
        parse_rule(write(tmp_path, "---\nrule: example\n"))


def test_unknown_tier_raises(tmp_path):
    text = VALID.replace("SCRIPT-ENFORCED", "VIBES-ENFORCED")
    with pytest.raises(RuleParseError, match="VIBES-ENFORCED"):
        parse_rule(write(tmp_path, text))


def test_enforced_mechanism_without_checker_raises(tmp_path):
    text = VALID.replace("    checker: tools/check_example.py\n", "")
    with pytest.raises(RuleParseError, match="names no checker"):
        parse_rule(write(tmp_path, text))


def test_non_boolean_armed_raises(tmp_path):
    text = VALID.replace("armed: true", "armed: yes-please")
    with pytest.raises(RuleParseError, match="must be true or false"):
        parse_rule(write(tmp_path, text))


def test_empty_rules_directory_raises(tmp_path):
    # A rules dir with no rules must be an error, never an empty pass.
    with pytest.raises(RuleParseError, match="no rule files"):
        load_rules(tmp_path)


def test_missing_rules_directory_raises(tmp_path):
    with pytest.raises(RuleParseError, match="does not exist"):
        load_rules(tmp_path / "nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/rules/test_rules_meta.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.rules_meta'`

- [ ] **Step 3: Write minimal implementation**

Create `tools/__init__.py` (empty file, makes `tools` importable), then `tools/rules_meta.py`:

```python
# OpenHardware — parse .claude/rules frontmatter into structured metadata.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Parse ``.claude/rules/*.md`` frontmatter.

A malformed rule file raises. It is never skipped: a rule that silently fails
to parse is indistinguishable from a rule nobody wrote, which is the exact
failure the rule system exists to prevent.
"""

from __future__ import annotations

import dataclasses
import pathlib

import yaml

RULES_DIR = pathlib.Path(".claude/rules")

VALID_TIERS = frozenset(
    {
        "CONVENTION",
        "HOOK-ENFORCED",
        "SCRIPT-ENFORCED",
        "TEST-ENFORCED",
        "PARSER-ENFORCED",
    }
)


class RuleParseError(Exception):
    """A rule file's frontmatter is missing, malformed, or incomplete."""


@dataclasses.dataclass(frozen=True)
class Mechanism:
    tier: str
    checker: str | None
    armed: bool
    blocked_by: str | None = None


@dataclasses.dataclass(frozen=True)
class Rule:
    name: str
    path: pathlib.Path
    mechanisms: tuple[Mechanism, ...]


def _frontmatter(text: str, path: pathlib.Path) -> dict:
    if not text.startswith("---\n"):
        raise RuleParseError(f"{path}: no frontmatter block (file must start with '---')")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise RuleParseError(f"{path}: frontmatter block is not closed")
    try:
        data = yaml.safe_load(text[4 : end + 1])
    except yaml.YAMLError as exc:
        raise RuleParseError(f"{path}: invalid YAML in frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise RuleParseError(f"{path}: frontmatter must be a mapping")
    return data


def parse_rule(path: pathlib.Path) -> Rule:
    data = _frontmatter(path.read_text(encoding="utf-8"), path)

    name = data.get("rule")
    if not name:
        raise RuleParseError(f"{path}: missing required key 'rule'")

    raw = data.get("mechanisms")
    if not isinstance(raw, list) or not raw:
        raise RuleParseError(f"{path}: 'mechanisms' must be a non-empty list")

    mechanisms = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise RuleParseError(f"{path}: mechanism {index} is not a mapping")
        tier = item.get("tier")
        if tier not in VALID_TIERS:
            raise RuleParseError(
                f"{path}: mechanism {index} has tier {tier!r}; "
                f"valid tiers are {sorted(VALID_TIERS)}"
            )
        armed = item.get("armed")
        if not isinstance(armed, bool):
            raise RuleParseError(
                f"{path}: mechanism {index} 'armed' must be true or false"
            )
        checker = item.get("checker")
        if tier != "CONVENTION" and not checker:
            raise RuleParseError(
                f"{path}: mechanism {index} is {tier} but names no checker"
            )
        mechanisms.append(Mechanism(tier, checker, armed, item.get("blocked_by")))

    return Rule(name=name, path=path, mechanisms=tuple(mechanisms))


def load_rules(rules_dir: pathlib.Path = RULES_DIR) -> list[Rule]:
    if not rules_dir.is_dir():
        raise RuleParseError(f"{rules_dir}: rules directory does not exist")
    paths = sorted(rules_dir.glob("*.md"))
    if not paths:
        raise RuleParseError(f"{rules_dir}: contains no rule files")
    return [parse_rule(path) for path in paths]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/rules/test_rules_meta.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add tools/__init__.py tools/rules_meta.py tests/rules/test_rules_meta.py
git commit -m "feat(rules): add rule frontmatter parser

Malformed or empty input raises rather than yielding an empty pass."
```

---

### Task 2: First armed rule — core-interface, end to end

Delivers one rule with a working checker and the meta-guard that ties them together, proving the whole loop before four more rules are written.

**Files:**
- Create: `.claude/rules/core-interface.md`
- Create: `tools/check_layering.py`
- Test: `tests/rules/test_check_layering.py`, `tests/rules/test_rules_are_armed.py`

**Interfaces:**
- Consumes: `load_rules`, `RuleParseError` from `tools.rules_meta`.
- Produces: `find_violations(backend_dir: pathlib.Path) -> list[tuple[pathlib.Path, int, str]]` returning `(path, line_number, include_target)`, and `main() -> int` returning a process exit code.

- [ ] **Step 1: Write the failing test**

Create `tests/rules/test_check_layering.py`:

```python
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from tools.check_layering import find_violations

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_forbidden_parts_include_is_found(tmp_path):
    (tmp_path / "bsim_bad.cc").write_text(
        '#include "../parts/input_POT.h"\n', encoding="utf-8"
    )
    violations = find_violations(tmp_path)
    assert len(violations) == 1
    assert violations[0][1] == 1
    assert violations[0][2] == "../parts/input_POT.h"


def test_forbidden_ui_include_is_found(tmp_path):
    (tmp_path / "bsim_bad.h").write_text('#include "picsimlab1.h"\n', encoding="utf-8")
    assert len(find_violations(tmp_path)) == 1


def test_lxrad_include_is_found(tmp_path):
    (tmp_path / "bsim_bad.h").write_text("#include <lxrad.h>\n", encoding="utf-8")
    assert len(find_violations(tmp_path)) == 1


def test_permitted_includes_are_not_flagged(tmp_path):
    (tmp_path / "bsim_ok.h").write_text(
        '#include "../lib/board.h"\n'
        '#include "../devices/bitbang_uart.h"\n'
        "#include <simavr/avr_adc.h>\n",
        encoding="utf-8",
    )
    assert find_violations(tmp_path) == []


def test_empty_directory_raises(tmp_path):
    # Nothing to scan must be an error, not a pass.
    with pytest.raises(ValueError, match="no source files"):
        find_violations(tmp_path / "missing")


def test_real_sim_backend_is_clean():
    # Verified clean at fork-point on 2026-08-09; this pins it.
    assert find_violations(REPO / "src" / "sim_backend") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/rules/test_check_layering.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.check_layering'`

- [ ] **Step 3: Write minimal implementation**

Create `tools/check_layering.py`:

```python
#!/usr/bin/env python3
# OpenHardware — enforce that CPU backends do not depend on parts or the UI.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Checker for .claude/rules/core-interface.md.

Nothing under ``src/sim_backend/`` may include from ``src/parts/`` or from the
lxrad UI layer. A backend that reaches into parts stops being swappable, which
is the property the ``bsim_*`` seam exists to provide.
"""

from __future__ import annotations

import pathlib
import re
import sys

BACKEND_DIR = pathlib.Path("src/sim_backend")
SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".h", ".hpp"})

_INCLUDE = re.compile(r'^\s*#\s*include\s*["<]([^">]+)[">]')
_FORBIDDEN_SUBSTRING = ("parts/", "lxrad")
_FORBIDDEN_PATTERN = re.compile(r"picsimlab\d")


def _is_forbidden(target: str) -> bool:
    if any(fragment in target for fragment in _FORBIDDEN_SUBSTRING):
        return True
    return bool(_FORBIDDEN_PATTERN.search(target))


def find_violations(
    backend_dir: pathlib.Path = BACKEND_DIR,
) -> list[tuple[pathlib.Path, int, str]]:
    paths = sorted(
        path
        for path in backend_dir.glob("*")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
    ) if backend_dir.is_dir() else []

    if not paths:
        raise ValueError(f"{backend_dir}: no source files to scan")

    violations: list[tuple[pathlib.Path, int, str]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            match = _INCLUDE.match(line)
            if match and _is_forbidden(match.group(1)):
                violations.append((path, number, match.group(1)))
    return violations


def main() -> int:
    try:
        violations = find_violations()
    except ValueError as exc:
        print(f"check_layering: {exc}", file=sys.stderr)
        return 2
    for path, number, target in violations:
        print(f"{path}:{number}: forbidden include {target!r}", file=sys.stderr)
    if violations:
        print(
            f"check_layering: {len(violations)} violation(s) of "
            f".claude/rules/core-interface.md",
            file=sys.stderr,
        )
        return 1
    print("check_layering: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/rules/test_check_layering.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Run the checker against the real tree**

Run: `python tools/check_layering.py`
Expected: `check_layering: OK`, exit code 0

- [ ] **Step 6: Write the rule document**

Create `.claude/rules/core-interface.md`:

```markdown
---
rule: core-interface
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_layering.py
    armed: true
  - tier: CONVENTION
    checker: null
    armed: false
---

# Core interface

A new CPU architecture is a `bsim_*` pair under `src/sim_backend/` implementing
the contract declared as pure virtuals in `src/lib/board.h`. Rules are labelled
**SCRIPT-ENFORCED** or **CONVENTION**:

> Breaking the enforced rule fails CI. Breaking a convention only hurts whoever
> reads the code next.

## 1. 2026-08-09 — SCRIPT-ENFORCED: backends may not include parts or UI

`tools/check_layering.py` scans every source file in `src/sim_backend/` for
`#include` targets containing `parts/` or `lxrad`, or matching `picsimlab\d`.
Any hit exits non-zero.

Measured at `fork-point` (`cd92747`): **15 files in `src/sim_backend/`, zero
violations.** The baseline is clean, so this rule never needed an exemption
list, and `test_real_sim_backend_is_clean` pins that.

The permitted dependencies are the ones upstream already uses —
`../lib/board.h`, `../devices/*`, `../lib/serial_port.h`, and engine headers
such as `<simavr/avr_adc.h>`. A backend that reaches into `parts/` stops being
swappable, which is the entire property the `bsim_*` seam provides.

## 2. 2026-08-09 — SCRIPT-ENFORCED: an empty scan is an error

`find_violations` raises `ValueError` when the directory holds no source files.
A checker that passes because it found nothing to check reports the same green
as a checker that verified 15 files, and the two are indistinguishable in CI
output. `test_empty_directory_raises` pins it.

## 3. 2026-08-09 — CONVENTION: implement the whole board contract

`src/lib/board.h` declares the pin API as pure virtuals — `MSetPin`,
`MSetPinDOV`, `MSetAPin`, `MSetPinOAV`, `MGetPin` — plus the `MInit`/`MEnd`/
`MStep`/`MReset` lifecycle and the `DBG*` debug accessors. C++ enforces that
they exist. Nothing enforces that they are *correct*, and a backend that stubs
`MSetAPin` to a no-op compiles, links, runs, and silently produces a dead
analog pin.

Not enforced here because correctness per method is what
`.claude/rules/conformance-fixtures.md` covers, one ledger cell at a time.
```

- [ ] **Step 7: Write the meta-guard test**

Create `tests/rules/test_rules_are_armed.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from tools.rules_meta import load_rules

REPO = pathlib.Path(__file__).resolve().parents[2]
RULES_DIR = REPO / ".claude" / "rules"


def test_rules_parse():
    # load_rules raises on an empty or missing directory, so this also proves
    # at least one rule exists.
    assert load_rules(RULES_DIR)


def test_every_armed_mechanism_has_an_existing_checker():
    missing = []
    for rule in load_rules(RULES_DIR):
        for mechanism in rule.mechanisms:
            if not mechanism.armed or mechanism.tier == "CONVENTION":
                continue
            if not (REPO / mechanism.checker).exists():
                missing.append(f"{rule.name}: {mechanism.checker}")
    assert not missing, f"armed mechanisms naming absent checkers: {missing}"


def test_every_unarmed_mechanism_explains_why():
    unexplained = []
    for rule in load_rules(RULES_DIR):
        for mechanism in rule.mechanisms:
            if mechanism.armed or mechanism.tier == "CONVENTION":
                continue
            if not mechanism.blocked_by:
                unexplained.append(f"{rule.name}: {mechanism.tier}")
    assert not unexplained, f"unarmed mechanisms with no blocked_by: {unexplained}"
```

- [ ] **Step 8: Run the meta-guard**

Run: `pytest tests/rules/ -v`
Expected: PASS — 17 passed

- [ ] **Step 9: Commit**

```bash
git add .claude/rules/core-interface.md tools/check_layering.py \
        tests/rules/test_check_layering.py tests/rules/test_rules_are_armed.py
git commit -m "feat(rules): arm core-interface with layering checker

sim_backend measured clean at fork-point: 15 files, 0 violations."
```

---

### Task 3: gpl-hygiene rule and license checker

**Files:**
- Create: `.claude/rules/gpl-hygiene.md`, `tools/check_licenses.py`
- Test: `tests/rules/test_check_licenses.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `find_v2_only(root: pathlib.Path) -> list[pathlib.Path]` and `find_missing_headers(paths: list[pathlib.Path]) -> list[pathlib.Path]`, plus `main() -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/rules/test_check_licenses.py`:

```python
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from tools.check_licenses import find_missing_headers, find_v2_only

V2_OR_LATER = (
    "# This program is free software; you can redistribute it and/or modify it\n"
    "# under the terms of the GNU General Public License as published by the Free\n"
    "# Software Foundation; either version 2, or (at your option) any later version.\n"
)

V2_ONLY = (
    "# This program is free software; you can redistribute it and/or modify it\n"
    "# under the terms of the GNU General Public License version 2 as published\n"
    "# by the Free Software Foundation.\n"
)


def test_v2_only_header_is_detected(tmp_path):
    (tmp_path / "bad.py").write_text(V2_ONLY, encoding="utf-8")
    assert find_v2_only(tmp_path) == [tmp_path / "bad.py"]


def test_v2_or_later_header_is_accepted(tmp_path):
    (tmp_path / "good.py").write_text(V2_OR_LATER, encoding="utf-8")
    assert find_v2_only(tmp_path) == []


def test_non_source_files_are_ignored(tmp_path):
    # COPYING is the stock GPL-2 text and must never trip the v2-only check.
    # A real source file sits alongside it because a directory holding only
    # COPYING has no source files at all, which is the error case below.
    (tmp_path / "COPYING").write_text(V2_ONLY, encoding="utf-8")
    (tmp_path / "real.py").write_text(V2_OR_LATER, encoding="utf-8")
    assert find_v2_only(tmp_path) == []


def test_missing_header_is_detected(tmp_path):
    path = tmp_path / "new.py"
    path.write_text("print('hello')\n", encoding="utf-8")
    assert find_missing_headers([path]) == [path]


def test_present_header_satisfies_the_check(tmp_path):
    path = tmp_path / "new.py"
    path.write_text(V2_OR_LATER + "print('hello')\n", encoding="utf-8")
    assert find_missing_headers([path]) == []


def test_empty_scan_raises(tmp_path):
    with pytest.raises(ValueError, match="no source files"):
        find_v2_only(tmp_path / "missing")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/rules/test_check_licenses.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.check_licenses'`

- [ ] **Step 3: Write minimal implementation**

Create `tools/check_licenses.py`:

```python
#!/usr/bin/env python3
# OpenHardware — verify GPL headers keep the v2-or-later path open.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Checker for .claude/rules/gpl-hygiene.md.

Two checks with different scopes:

* v2-only headers are searched for across the **whole tree**, because a single
  such file revokes the GPL-3 path and every Apache-2.0 dependency with it.
* header presence is required only on files **added since fork-point**, because
  upstream's files are upstream's business.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

FORK_POINT = "fork-point"
SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".h", ".hpp", ".py"})

_GPL = "GNU General Public License"
_LATER = "any later version"
_HEAD_BYTES = 4000


def _source_files(root: pathlib.Path) -> list[pathlib.Path]:
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and ".git" not in path.parts
    )


def find_v2_only(root: pathlib.Path = pathlib.Path(".")) -> list[pathlib.Path]:
    paths = _source_files(root)
    if not paths:
        raise ValueError(f"{root}: no source files to scan")
    offenders = []
    for path in paths:
        head = path.read_text(encoding="utf-8", errors="replace")[:_HEAD_BYTES]
        if _GPL in head and _LATER not in head:
            offenders.append(path)
    return offenders


def find_missing_headers(paths: list[pathlib.Path]) -> list[pathlib.Path]:
    offenders = []
    for path in paths:
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        head = path.read_text(encoding="utf-8", errors="replace")[:_HEAD_BYTES]
        if _GPL not in head:
            offenders.append(path)
    return offenders


def _added_since_fork_point() -> list[pathlib.Path]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=A", FORK_POINT, "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [pathlib.Path(line) for line in result.stdout.split() if line]


def main() -> int:
    try:
        v2_only = find_v2_only()
    except ValueError as exc:
        print(f"check_licenses: {exc}", file=sys.stderr)
        return 2

    for path in v2_only:
        print(f"{path}: GPL header is version-2-only", file=sys.stderr)

    missing = find_missing_headers(_added_since_fork_point())
    for path in missing:
        print(f"{path}: new source file has no GPL header", file=sys.stderr)

    if v2_only:
        print(
            "check_licenses: a v2-only header revokes the GPL-3 path; "
            "every Apache-2.0 dependency must be removed",
            file=sys.stderr,
        )
    if v2_only or missing:
        return 1
    print("check_licenses: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/rules/test_check_licenses.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Settle spec §8.1 against the whole tree**

Run: `python tools/check_licenses.py`
Expected: `check_licenses: OK`, exit code 0.

This is the definitive answer to spec §8.1, which until now rested on a
two-file sample. Record the result in the rule document in Step 6. If this
step instead reports v2-only files, **stop and report** — the dependency
policy in Global Constraints inverts and Apache-2.0 becomes forbidden.

- [ ] **Step 6: Write the rule document**

Create `.claude/rules/gpl-hygiene.md`:

```markdown
---
rule: gpl-hygiene
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_licenses.py
    armed: true
---

# GPL hygiene

PICSimLab is GPL-2-or-later. This fork inherits that, and every rule here
protects one consequence of it.

## 1. 2026-08-09 — SCRIPT-ENFORCED: no file may carry a v2-only header

`find_v2_only` in `tools/check_licenses.py` scans the whole tree for a file
whose first 4000 bytes mention `GNU General Public License` without
`any later version`.

Upstream is v2-**or-later**, verified in `src/picsimlab1.cc` and
`src/sim_backend/bsim_simavr.h`. That is what makes **Apache-2.0 dependencies
usable**: the combined work moves forward to GPL-3, with which Apache-2.0 is
compatible. Under GPL-2-only it is not, because of the patent-termination
clause.

So the check is deliberately inverted from the obvious one. Asserting that a
GPL header is *present* would pass the exact tree that breaks the project — one
v2-only file among thousands of correct ones. The check asserts the *absence*
of v2-only headers instead.

`COPYING` cannot settle this and is excluded by extension: it is the stock GPL-2
text, whose appendix carries the "or any later version" boilerplate in every
copy ever distributed. Only per-file source headers decide it, and
`test_non_source_files_are_ignored` pins that exclusion.

## 2. 2026-08-09 — SCRIPT-ENFORCED: new source files carry the header

Scoped to files added since `fork-point`, via
`git diff --diff-filter=A fork-point HEAD`. Upstream's files are upstream's
business; ours are ours.

## 3. 2026-08-09 — SCRIPT-ENFORCED: dependency licences

MIT, BSD, and GPL-compatible licences only. PyYAML (MIT) is the sole
third-party Python dependency. Apache-2.0 is permitted **only while section 1
passes** — the moment it fails, every Apache-2.0 dependency must go.
```

- [ ] **Step 7: Run the full suite**

Run: `pytest tests/rules/ -v`
Expected: PASS — 23 passed

- [ ] **Step 8: Commit**

```bash
git add .claude/rules/gpl-hygiene.md tools/check_licenses.py \
        tests/rules/test_check_licenses.py
git commit -m "feat(rules): arm gpl-hygiene with license checker

Checks for the absence of v2-only headers, not the presence of any header:
one v2-only file revokes the GPL-3 path and every Apache-2.0 dependency."
```

---

### Task 4: upstream-sync rule and delta checker

**Files:**
- Create: `.claude/rules/upstream-sync.md`, `tools/check_deltas.py`, `docs/upstream-deltas.md`
- Test: `tests/rules/test_check_deltas.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `logged_paths(ledger: pathlib.Path) -> set[str]`, `unlogged_modifications(changed: set[str], at_fork: set[str], logged: set[str]) -> list[str]`, and `main() -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/rules/test_check_deltas.py`:

```python
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from tools.check_deltas import logged_paths, unlogged_modifications

LEDGER = """# Upstream deltas

## `src/lib/spareparts.cc`

Reason: analog net semantics, spec section 4.1.
"""


def test_ledger_paths_are_parsed(tmp_path):
    path = tmp_path / "upstream-deltas.md"
    path.write_text(LEDGER, encoding="utf-8")
    assert logged_paths(path) == {"src/lib/spareparts.cc"}


def test_missing_ledger_yields_no_paths(tmp_path):
    assert logged_paths(tmp_path / "absent.md") == set()


def test_modified_upstream_file_without_entry_is_flagged():
    result = unlogged_modifications(
        changed={"src/lib/board.h"},
        at_fork={"src/lib/board.h"},
        logged=set(),
    )
    assert result == ["src/lib/board.h"]


def test_modified_upstream_file_with_entry_passes():
    result = unlogged_modifications(
        changed={"src/lib/board.h"},
        at_fork={"src/lib/board.h"},
        logged={"src/lib/board.h"},
    )
    assert result == []


def test_new_file_is_never_flagged():
    # Additive files are unrestricted; they did not exist at fork-point.
    result = unlogged_modifications(
        changed={"tools/check_deltas.py"},
        at_fork={"src/lib/board.h"},
        logged=set(),
    )
    assert result == []


def test_empty_fork_point_set_raises():
    # An empty fork-point listing means the tag resolved to nothing; treating
    # that as "no upstream files" would pass every modification silently.
    with pytest.raises(ValueError, match="no files at fork-point"):
        unlogged_modifications(changed={"a"}, at_fork=set(), logged=set())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/rules/test_check_deltas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.check_deltas'`

- [ ] **Step 3: Write minimal implementation**

Create `tools/check_deltas.py`:

```python
#!/usr/bin/env python3
# OpenHardware — require every modification to an upstream file to be logged.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Checker for .claude/rules/upstream-sync.md.

Additive files are unrestricted. A file that existed at ``fork-point`` may only
be modified if ``docs/upstream-deltas.md`` names it in backticks.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

FORK_POINT = "fork-point"
LEDGER = pathlib.Path("docs/upstream-deltas.md")

_BACKTICKED = re.compile(r"`([^`]+)`")


def logged_paths(ledger: pathlib.Path = LEDGER) -> set[str]:
    if not ledger.is_file():
        return set()
    text = ledger.read_text(encoding="utf-8")
    return {match.group(1).strip() for match in _BACKTICKED.finditer(text)}


def unlogged_modifications(
    changed: set[str], at_fork: set[str], logged: set[str]
) -> list[str]:
    if not at_fork:
        raise ValueError(
            f"no files at fork-point: does tag {FORK_POINT!r} exist?"
        )
    return sorted((changed & at_fork) - logged)


def _git(*args: str) -> set[str]:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    )
    return {line for line in result.stdout.splitlines() if line}


def main() -> int:
    try:
        offenders = unlogged_modifications(
            changed=_git("diff", "--name-only", FORK_POINT, "HEAD"),
            at_fork=_git("ls-tree", "-r", "--name-only", FORK_POINT),
            logged=logged_paths(),
        )
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"check_deltas: {exc}", file=sys.stderr)
        return 2

    for path in offenders:
        print(
            f"{path}: upstream file modified but absent from {LEDGER}",
            file=sys.stderr,
        )
    if offenders:
        print(
            f"check_deltas: {len(offenders)} unlogged upstream modification(s)",
            file=sys.stderr,
        )
        return 1
    print("check_deltas: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/rules/test_check_deltas.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Create the empty ledger**

Create `docs/upstream-deltas.md`:

```markdown
# Upstream deltas

Every file that existed at tag `fork-point` and has since been modified must
appear here as a `## ` heading naming its repo-relative path in backticks,
followed by the reason.

Enforced by `tools/check_deltas.py`, per `.claude/rules/upstream-sync.md`.

**Current count: zero.** Every file added by this fork so far is new, which is
the state this fork intends to hold for as long as possible.
```

- [ ] **Step 6: Run the checker against the real tree**

Run: `python tools/check_deltas.py`
Expected: `check_deltas: OK`, exit code 0 — no upstream file has been modified.

- [ ] **Step 7: Write the rule document**

Create `.claude/rules/upstream-sync.md`:

```markdown
---
rule: upstream-sync
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_deltas.py
    armed: true
---

# Upstream sync

The fork commit is tagged `fork-point`
(`cd92747b1a04cab56c17f4e9ac35a1406c9935f7`, 2026-07-30).

## 1. 2026-08-09 — SCRIPT-ENFORCED: modifications to upstream files must be logged

`tools/check_deltas.py` intersects `git diff --name-only fork-point HEAD` with
`git ls-tree -r --name-only fork-point` and subtracts the backticked paths in
`docs/upstream-deltas.md`. Anything left exits non-zero.

Additive files are unrestricted and always will be. Two of this fork's three
planned additions — the 8086 core and the web UI — are entirely new files and
will never appear in the ledger.

## 2. 2026-08-09 — SCRIPT-ENFORCED: an unresolvable tag is an error

`unlogged_modifications` raises when the fork-point file set is empty. Without
that guard a missing or misspelled tag yields an empty intersection, which
reads as "no unlogged modifications" — the check would pass hardest at the exact
moment it stopped working. `test_empty_fork_point_set_raises` pins it.

## 3. 2026-08-09 — CONVENTION: prefer a new file to an edit

The analog solver is the one planned change with no purely additive form, since
it must give `src/lib/spareparts.cc` shared-node semantics it does not have
(spec section 4.1). Every entry the ledger ever gains is a future merge
conflict, so the question to answer before adding one is whether the change can
live beside the original instead of inside it.

Local-only ignores belong in `.git/info/exclude`, never in upstream's
`.gitignore`. This repository's own `.omc/` entry is handled that way.
```

- [ ] **Step 8: Run the full suite**

Run: `pytest tests/rules/ -v`
Expected: PASS — 29 passed

- [ ] **Step 9: Commit**

```bash
git add .claude/rules/upstream-sync.md tools/check_deltas.py \
        docs/upstream-deltas.md tests/rules/test_check_deltas.py
git commit -m "feat(rules): arm upstream-sync with delta ledger checker

An unresolvable fork-point tag raises rather than passing vacuously."
```

---

### Task 5: determinism rule and banned-symbol checker

Ships one armed mechanism and one explicitly unarmed one, exercising the
`blocked_by` path in the meta-guard for the first time.

**Files:**
- Create: `.claude/rules/determinism.md`, `tools/check_banned_symbols.py`
- Test: `tests/rules/test_check_banned_symbols.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `find_banned(paths: list[pathlib.Path]) -> list[tuple[pathlib.Path, int, str]]` and `main() -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/rules/test_check_banned_symbols.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from tools.check_banned_symbols import find_banned


def test_rand_call_is_flagged(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("int x = rand();\n", encoding="utf-8")
    assert find_banned([path]) == [(path, 1, "rand")]


def test_time_call_is_flagged(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("t = time(NULL);\n", encoding="utf-8")
    assert find_banned([path]) == [(path, 1, "time")]


def test_srand_is_not_mistaken_for_rand(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("srand(1);\n", encoding="utf-8")
    assert find_banned([path]) == []


def test_comments_are_not_flagged(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("// never call rand() here\n", encoding="utf-8")
    assert find_banned([path]) == []


def test_non_source_files_are_skipped(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("rand()\n", encoding="utf-8")
    assert find_banned([path]) == []


def test_clean_file_passes(tmp_path):
    path = tmp_path / "bsim_new.cc"
    path.write_text("int x = cycles * 2;\n", encoding="utf-8")
    assert find_banned([path]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/rules/test_check_banned_symbols.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.check_banned_symbols'`

- [ ] **Step 3: Write minimal implementation**

Create `tools/check_banned_symbols.py`:

```python
#!/usr/bin/env python3
# OpenHardware — ban nondeterministic calls from new simulation code.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Checker for .claude/rules/determinism.md.

Scoped to files added since ``fork-point``. Upstream's existing use of these
symbols is upstream's business; a delta would be needed to change it, and this
checker is not the place to force one.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

FORK_POINT = "fork-point"
SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".h", ".hpp"})
BANNED = ("rand", "time", "clock")

_CALL = re.compile(r"(?<![\w])(" + "|".join(BANNED) + r")\s*\(")
_COMMENT = re.compile(r"^\s*(//|/\*|\*)")


def find_banned(
    paths: list[pathlib.Path],
) -> list[tuple[pathlib.Path, int, str]]:
    hits: list[tuple[pathlib.Path, int, str]] = []
    for path in paths:
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if _COMMENT.match(line):
                continue
            match = _CALL.search(line)
            if match:
                hits.append((path, number, match.group(1)))
    return hits


def _added_since_fork_point() -> list[pathlib.Path]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=A", FORK_POINT, "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [pathlib.Path(line) for line in result.stdout.split() if line]


def main() -> int:
    try:
        hits = find_banned(_added_since_fork_point())
    except subprocess.CalledProcessError as exc:
        print(f"check_banned_symbols: {exc}", file=sys.stderr)
        return 2
    for path, number, symbol in hits:
        print(f"{path}:{number}: nondeterministic call {symbol}()", file=sys.stderr)
    if hits:
        print(
            f"check_banned_symbols: {len(hits)} violation(s) of "
            f".claude/rules/determinism.md",
            file=sys.stderr,
        )
        return 1
    print("check_banned_symbols: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/rules/test_check_banned_symbols.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Run the checker against the real tree**

Run: `python tools/check_banned_symbols.py`
Expected: `check_banned_symbols: OK`, exit code 0

- [ ] **Step 6: Write the rule document**

Create `.claude/rules/determinism.md`:

```markdown
---
rule: determinism
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_banned_symbols.py
    armed: true
  - tier: TEST-ENFORCED
    checker: tests/rules/test_replay_determinism.py
    armed: false
    blocked_by: >-
      Requires a verified Makefile.NOGUI build producing VCD output without a
      display. Spec section 8.4 is still open.
---

# Determinism

Same firmware, same inputs, same output. A simulator that violates this
produces plausible results that cannot be reproduced, and the resulting bug
hunt is measured in weeks.

## 1. 2026-08-09 — SCRIPT-ENFORCED: no nondeterministic calls in new simulation code

`tools/check_banned_symbols.py` rejects `rand(`, `time(`, and `clock(` in files
added since `fork-point`. `srand(` is deliberately not matched — the regex uses
a negative lookbehind for word characters, and `test_srand_is_not_mistaken_for_rand`
pins that, since seeding is how determinism is *achieved*.

Scoped to new files only. Forcing upstream's existing usage to comply would
require an upstream delta, which section 3 of `.claude/rules/upstream-sync.md`
exists to discourage.

## 2. 2026-08-09 — TEST-ENFORCED, NOT YET ARMED: identical replay

Two headless runs of the same firmware must produce byte-identical VCD output.
`armed: false` until spec section 8.4 confirms `Makefile.NOGUI` emits VCD
without a display.

The unarmed state is declared in this file's frontmatter and checked by
`test_every_unarmed_mechanism_explains_why`. A rule claiming enforcement it
does not have is worse than no rule, because it implies coverage that is not
there.

## 3. 2026-08-09 — CONVENTION: simulation time is an integer

Accumulating simulated time in a float makes step size affect results and
sequence affect totals, so two runs that differ only in scheduling order
diverge. Not enforced: distinguishing a time accumulator from any other float
needs more than a grep.
```

- [ ] **Step 7: Run the full suite**

Run: `pytest tests/rules/ -v`
Expected: PASS — 35 passed. `test_every_unarmed_mechanism_explains_why` now
exercises a real unarmed mechanism for the first time.

- [ ] **Step 8: Commit**

```bash
git add .claude/rules/determinism.md tools/check_banned_symbols.py \
        tests/rules/test_check_banned_symbols.py
git commit -m "feat(rules): arm determinism's symbol check, declare replay unarmed

The replay mechanism ships armed:false with blocked_by naming spec 8.4."
```

---

### Task 6: conformance-fixtures rule and ledger parser

**Files:**
- Create: `.claude/rules/conformance-fixtures.md`, `tools/ledger.py`, `docs/features/README.md`
- Test: `tests/rules/test_ledger.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Cell(id: str, tier: str, oracle: str, tolerance: str, status: str, fixture: str)` and `parse_ledger(path: pathlib.Path) -> list[Cell]`, raising `LedgerError`.

- [ ] **Step 1: Write the failing test**

Create `tests/rules/test_ledger.py`:

```python
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from tools.ledger import Cell, LedgerError, parse_ledger

HEADER = (
    "| id | tier | oracle | tolerance | status | fixture |\n"
    "|---|---|---|---|---|---|\n"
)


def write(tmp_path, rows: str) -> pathlib.Path:
    path = tmp_path / "ledger.md"
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def test_parses_a_planned_cell(tmp_path):
    path = write(tmp_path, "| i8086.mov | F0 | ISA manual 2-21 | exact | planned | - |\n")
    assert parse_ledger(path) == [
        Cell("i8086.mov", "F0", "ISA manual 2-21", "exact", "planned", "-")
    ]


def test_unknown_tier_raises(tmp_path):
    path = write(tmp_path, "| a | F9 | manual | exact | planned | - |\n")
    with pytest.raises(LedgerError, match="F9"):
        parse_ledger(path)


def test_unknown_status_raises(tmp_path):
    path = write(tmp_path, "| a | F0 | manual | exact | shipped | - |\n")
    with pytest.raises(LedgerError, match="shipped"):
        parse_ledger(path)


def test_scheduled_cell_without_oracle_raises(tmp_path):
    path = write(tmp_path, "| a | F0 |  | exact | in-progress | - |\n")
    with pytest.raises(LedgerError, match="no oracle"):
        parse_ledger(path)


def test_done_cell_without_fixture_raises(tmp_path):
    path = write(tmp_path, "| a | F0 | manual | exact | done | - |\n")
    with pytest.raises(LedgerError, match="no fixture"):
        parse_ledger(path)


def test_wrong_column_count_raises(tmp_path):
    path = write(tmp_path, "| a | F0 | manual |\n")
    with pytest.raises(LedgerError, match="expected 6 columns"):
        parse_ledger(path)


def test_duplicate_id_raises(tmp_path):
    rows = (
        "| a | F0 | manual | exact | planned | - |\n"
        "| a | F1 | manual | exact | planned | - |\n"
    )
    with pytest.raises(LedgerError, match="duplicate id"):
        parse_ledger(write(tmp_path, rows))


def test_ledger_with_no_rows_raises(tmp_path):
    with pytest.raises(LedgerError, match="no cells"):
        parse_ledger(write(tmp_path, ""))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/rules/test_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.ledger'`

- [ ] **Step 3: Write minimal implementation**

Create `tools/ledger.py`:

```python
#!/usr/bin/env python3
# OpenHardware — parse feature ledgers into validated cells.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Parser for the feature ledgers under ``docs/features/``.

Every malformed row raises. A ledger parser that skips rows it cannot read
deletes features silently, and a feature nobody can see is a feature nobody
builds.
"""

from __future__ import annotations

import dataclasses
import pathlib

TIERS = ("F0", "F1", "F2", "F3")
STATUSES = ("planned", "in-progress", "done")
SCHEDULED = ("in-progress", "done")
COLUMNS = 6
_EMPTY = {"", "-", "—"}


class LedgerError(Exception):
    """A ledger row is malformed, incomplete, or contradictory."""


@dataclasses.dataclass(frozen=True)
class Cell:
    id: str
    tier: str
    oracle: str
    tolerance: str
    status: str
    fixture: str


def _rows(text: str) -> list[tuple[int, list[str]]]:
    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or all(set(cell) <= {"-", ":"} for cell in cells if cell):
            continue  # separator row
        if cells[0].lower() == "id":
            continue  # header row
        rows.append((number, cells))
    return rows


def parse_ledger(path: pathlib.Path) -> list[Cell]:
    rows = _rows(path.read_text(encoding="utf-8"))
    if not rows:
        raise LedgerError(f"{path}: contains no cells")

    cells: list[Cell] = []
    seen: set[str] = set()
    for number, values in rows:
        where = f"{path}:{number}"
        if len(values) != COLUMNS:
            raise LedgerError(f"{where}: expected {COLUMNS} columns, got {len(values)}")
        cell = Cell(*values)
        if not cell.id:
            raise LedgerError(f"{where}: row has no id")
        if cell.id in seen:
            raise LedgerError(f"{where}: duplicate id {cell.id!r}")
        seen.add(cell.id)
        if cell.tier not in TIERS:
            raise LedgerError(f"{where}: tier {cell.tier!r} not in {list(TIERS)}")
        if cell.status not in STATUSES:
            raise LedgerError(f"{where}: status {cell.status!r} not in {list(STATUSES)}")
        if cell.status in SCHEDULED and cell.oracle in _EMPTY:
            raise LedgerError(
                f"{where}: status {cell.status!r} but no oracle; "
                f"a cell with no oracle cannot be scheduled"
            )
        if cell.status == "done" and cell.fixture in _EMPTY:
            raise LedgerError(f"{where}: status 'done' but no fixture")
        cells.append(cell)
    return cells
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/rules/test_ledger.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Document the ledger format**

Create `docs/features/README.md`:

```markdown
# Feature ledgers

One file per area, each a markdown table parsed by `tools/ledger.py`.

| id | tier | oracle | tolerance | status | fixture |
|---|---|---|---|---|---|
| i8086.mov.reg | F0 | Intel 8086 ISA manual, table 2-21 | exact | planned | - |

- **tier** — `F0` functional, `F1` timing-approximate, `F2` cycle-accurate,
  `F3` electrically-accurate.
- **oracle** — the external source of truth. Required before a cell may leave
  `planned`.
- **tolerance** — `exact`, or a numeric bound such as `abs=2`.
- **status** — `planned`, `in-progress`, `done`.
- **fixture** — path to the conformance test. Required at `done`.

Ledgers are emitted by the `feature-strategy` skill, not written by hand.
```

- [ ] **Step 6: Write the rule document**

Create `.claude/rules/conformance-fixtures.md`:

```markdown
---
rule: conformance-fixtures
mechanisms:
  - tier: PARSER-ENFORCED
    checker: tools/ledger.py
    armed: true
  - tier: TEST-ENFORCED
    checker: tests/rules/test_fixtures_pass.py
    armed: false
    blocked_by: >-
      No fixtures exist yet. Requires the NOGUI build and a resolved
      PICSimLab_rcontrol dependency; spec sections 8.3 and 8.4 are open.
---

# Conformance fixtures

A feature is done when it matches an oracle within a declared tolerance. Not
when it looks right.

## 1. 2026-08-09 — PARSER-ENFORCED: every row carries six columns

`tools/ledger.py` raises `LedgerError` on any row that is not
`id · tier · oracle · tolerance · status · fixture`.

`PARSER-ENFORCED` is the dangerous tier: a parser that skips what it cannot
read deletes data silently. So this parser raises where a lenient one would
`continue`, and `test_wrong_column_count_raises` pins the difference.

## 2. 2026-08-09 — PARSER-ENFORCED: a cell with no oracle cannot be scheduled

Status `in-progress` or `done` with an empty oracle raises. Ground truth for a
simulator is always obtainable — real silicon, a reference emulator, vendor
test vectors, `ngspice` on the same netlist, datasheet timing diagrams. A cell
whose author could not name one has not been specified.

## 3. 2026-08-09 — PARSER-ENFORCED: `done` requires a fixture

An empty fixture at `done` raises. Otherwise `done` means "someone said so".

## 4. 2026-08-09 — CRITICAL: a fixture that cannot reach its oracle must fail

Upstream's `tests/python/test_blink.py` wraps its assertions in
`except ConnectionError: print(e)`. When PICSimLab is not listening, the
exception is caught, nothing is asserted, and **the test passes**. A suite of
such tests reports green on a machine where the simulator never started.

Never catch a connection or setup failure around an assertion. An unreachable
oracle is a failure, not a skip, and never a pass.

This is why every checker in this repository raises on empty input rather than
returning an empty result — the same defect wearing different clothes.

## 5. 2026-08-09 — CONVENTION: most cells ship at F0

The failure mode is not shipping low fidelity. It is shipping low fidelity
while implying high. Declare `F0` and move on; promote a cell only when a
fixture and oracle justify it.
```

- [ ] **Step 7: Run the full suite**

Run: `pytest tests/rules/ -v`
Expected: PASS — 43 passed

- [ ] **Step 8: Commit**

```bash
git add .claude/rules/conformance-fixtures.md tools/ledger.py \
        docs/features/README.md tests/rules/test_ledger.py
git commit -m "feat(rules): add feature ledger parser and conformance rule

Records upstream test_blink.py's vacuous-pass defect as the worked example."
```

---

### Task 7: The feature-strategy skill

**Files:**
- Create: `.claude/skills/feature-strategy/SKILL.md`

**Interfaces:**
- Consumes: `tools/ledger.py` (the emitted ledger must parse), all five rule files.
- Produces: no code. The skill's output artifacts are `docs/features/<area>.md` ledgers and a strategy document per area.

- [ ] **Step 1: Write the skill document**

Create `.claude/skills/feature-strategy/SKILL.md`:

```markdown
---
name: feature-strategy
description: Use when deciding what to build next in OpenHardware — derives a feature ledger and implementation strategy for a simulator capability gap, with every feature bound to an external oracle. Use before starting any new core, solver, peripheral, or UI area.
---

# Feature strategy

Turn a vague capability gap into an ordered ledger of features, each defined by
a conformance test against ground truth.

**Announce at start:** "Using feature-strategy to derive the ledger for <area>."

## The premise

Features are cells in a capability matrix, and every cell is defined by a
conformance test against an external oracle. A simulator is the rare domain
where ground truth is always obtainable, so "done because it looks right" is
never necessary and never acceptable.

## Phase 0 — inventory the base, with evidence

Before enumerating anything, establish what the fork already does. PICSimLab
ships six CPU engines, 21 boards, and roughly 95 parts; rebuilding any of it is
pure loss.

**Read the source, not the file names.** This project has already been burned
once: the design document rated the analog solver "invasive, needs a new layer
between parts and boards" based on a directory listing. Reading the source
showed parts reach pins through the `SpareParts` mediator and a pure-virtual
pin API that already carries float voltages. The rating was wrong by an entire
architectural layer.

Record each finding with the file and construct that proves it. A rating with
no citation is a hypothesis.

**Output:** a list of what exists, each entry citing a path.

## Phase 1 — build the capability matrix

Enumerate the axes of the gap. For a CPU core: instruction groups × addressing
modes × flag effects × interrupts × timing. For the analog solver: element
types × solver modes (DC operating point, transient, convergence) × tolerance.
For a peripheral: registers × operating modes × error conditions.

Prefer many small cells to few large ones. A cell that cannot be finished in a
day is two cells.

**Output:** the cross product, before any filtering.

## Phase 2 — assign a fidelity tier

| Tier | Meaning |
|---|---|
| `F0` | functional — right result, wrong timing |
| `F1` | timing-approximate — instruction counts right, sub-cycle wrong |
| `F2` | cycle-accurate — matches hardware cycle counts |
| `F3` | electrically-accurate — matches SPICE within tolerance |

Default to `F0`. Promote only with a reason recorded in the strategy document.

## Phase 3 — bind an oracle to every cell

Each cell names its oracle and tolerance:

- CPU cores — vendor ISA manual tables, a reference emulator, real silicon
- analog — `ngspice` on the same netlist
- peripherals — datasheet timing diagrams
- regression — a previously captured VCD

**A cell with no oracle cannot be scheduled.** Leave it `planned` and say so.
`tools/ledger.py` enforces this.

Tolerance is `exact` or a numeric bound. Upstream's `tests/python/test_blink.py`
shows the shape: `assert pcyc == pytest.approx(20, abs=2)`.

## Phase 4 — order into slices

Topologically sort by dependency, then group into slices that each end in
something demoable. A slice with no demo is a slice nobody can review.

## Phase 5 — emit

Two artifacts:

1. `docs/features/<area>.md` — the ledger. Must parse under `tools/ledger.py`.
2. `docs/superpowers/plans/<date>-<area>.md` — the strategy: slice order,
   promotion reasons, and every Phase 0 finding with its citation.

Verify before finishing:

```bash
python -c "from tools.ledger import parse_ledger; import pathlib; \
print(len(parse_ledger(pathlib.Path('docs/features/<area>.md'))), 'cells')"
pytest tests/rules/ -v
```

## Rules that bind this work

- `.claude/rules/conformance-fixtures.md` — oracle and fixture requirements
- `.claude/rules/core-interface.md` — where a new architecture may live
- `.claude/rules/upstream-sync.md` — additive by default
- `.claude/rules/determinism.md` — no nondeterministic calls in new code
- `.claude/rules/gpl-hygiene.md` — headers and dependency licences

## Red flags

| Thought | Reality |
|---|---|
| "The oracle is obvious, I'll add it later" | A cell with no oracle cannot be scheduled. Write it now. |
| "This is clearly cycle-accurate" | Declare `F0` until a fixture proves otherwise. |
| "The directory listing shows..." | Read the source. This project has been wrong that way before. |
| "I'll skip the fixture, the test passes" | A test that cannot reach its oracle passes vacuously. |
| "This cell is big but cohesive" | If it takes more than a day, it is two cells. |
```

- [ ] **Step 2: Verify the skill's frontmatter parses**

Run:

```bash
python -c "import yaml,pathlib; t=pathlib.Path('.claude/skills/feature-strategy/SKILL.md').read_text(encoding='utf-8'); e=t.find(chr(10)+'---'+chr(10),3); d=yaml.safe_load(t[4:e+1]); print(d['name'], '|', d['description'][:60])"
```

Expected: `feature-strategy | Use when deciding what to build next in OpenHardware — der`

- [ ] **Step 3: Run the full suite**

Run: `pytest tests/rules/ -v`
Expected: PASS — 43 passed

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/feature-strategy/SKILL.md
git commit -m "feat(skill): add feature-strategy derivation skill

Six phases from capability gap to oracle-bound ledger."
```

---

### Task 8: Wire the rules into context and CI

**Files:**
- Create: `CLAUDE.md`, `.github/workflows/rules.yml`
- Test: `tests/rules/test_claude_md_lists_every_rule.py`

**Interfaces:**
- Consumes: `load_rules` from `tools.rules_meta`.
- Produces: no code. Final integration task.

- [ ] **Step 1: Write the failing test**

Create `tests/rules/test_claude_md_lists_every_rule.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from tools.rules_meta import load_rules

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_claude_md_references_every_rule():
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    missing = [
        rule.name
        for rule in load_rules(REPO / ".claude" / "rules")
        if rule.name not in text
    ]
    assert not missing, f"CLAUDE.md does not mention: {missing}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/rules/test_claude_md_lists_every_rule.py -v`
Expected: FAIL — `FileNotFoundError: ... CLAUDE.md`

- [ ] **Step 3: Write CLAUDE.md**

Create `CLAUDE.md`:

```markdown
# OpenHardware

A fork of [PICSimLab](https://github.com/lcgamboa/picsimlab) extended toward
simulating every class of hardware in one tool: MCU firmware with virtual
peripherals, CPU/ISA simulation, and analog circuit solving.

Upstream is GPL-2-or-later. **So is everything here.**

## Rules

`.claude/rules/` is not auto-loaded. These are listed so they enter context;
the checkers named in each file are what actually enforce them.

- `.claude/rules/gpl-hygiene.md` — no v2-only headers; dependency licences
- `.claude/rules/upstream-sync.md` — additive by default; log every upstream edit
- `.claude/rules/core-interface.md` — backends never include parts or UI
- `.claude/rules/determinism.md` — no nondeterministic calls in new code
- `.claude/rules/conformance-fixtures.md` — oracle and fixture requirements

## Before you commit

```bash
python tools/check_layering.py
python tools/check_licenses.py
python tools/check_deltas.py
python tools/check_banned_symbols.py
pytest tests/rules/ -v
```

Never run bare `pytest` from the repo root: upstream's `tests/python/` imports
the out-of-tree module `PICSimLab_rcontrol` and needs a built binary.

## Deciding what to build

Use the `feature-strategy` skill. Do not add features to a ledger by hand.

## Fork point

Tag `fork-point` = `cd92747b1a04cab56c17f4e9ac35a1406c9935f7` (2026-07-30).
Every modification to a file that existed then must appear in
`docs/upstream-deltas.md`.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/rules/test_claude_md_lists_every_rule.py -v`
Expected: PASS — 1 passed

- [ ] **Step 5: Add the CI workflow**

Create `.github/workflows/rules.yml`:

```yaml
name: rules

on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Fetch fork-point tag
        run: git fetch --tags --force

      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"

      - name: Install dependencies
        run: pip install pytest==9.0.2 PyYAML==6.0.3

      - name: check_layering
        run: python tools/check_layering.py

      - name: check_licenses
        run: python tools/check_licenses.py

      - name: check_deltas
        run: python tools/check_deltas.py

      - name: check_banned_symbols
        run: python tools/check_banned_symbols.py

      - name: rules test suite
        run: pytest tests/rules/ -v
```

- [ ] **Step 6: Run every checker and the full suite locally**

Run:

```bash
python tools/check_layering.py && \
python tools/check_licenses.py && \
python tools/check_deltas.py && \
python tools/check_banned_symbols.py && \
pytest tests/rules/ -v
```

Expected: four `OK` lines, then PASS — 44 passed.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md .github/workflows/rules.yml \
        tests/rules/test_claude_md_lists_every_rule.py
git commit -m "feat: wire rules into agent context and CI

CLAUDE.md must name every rule; a test enforces it."
```

---

## Done criteria

- [ ] Five rule files parse, each declaring at least one mechanism.
- [ ] Four checkers exit 0 on the clean tree.
- [ ] `pytest tests/rules/ -v` reports 44 passed.
- [ ] Every armed mechanism names a checker that exists.
- [ ] Every unarmed mechanism carries a `blocked_by`.
- [ ] `docs/upstream-deltas.md` is empty of entries — no upstream file modified.
- [ ] `git diff --name-only fork-point HEAD` lists only new files.

## Deliberately deferred

| Deferred | Why | Unblocked by |
|---|---|---|
| `tests/rules/test_replay_determinism.py` | Needs a verified NOGUI build | Spec §8.4 |
| `tests/rules/test_fixtures_pass.py` | No fixtures exist; `PICSimLab_rcontrol` is out-of-tree | Spec §8.3 |
| A `PreToolUse` hook for `HOOK-ENFORCED` | No rule needs it until the analog work edits `spareparts.cc` | Slice 3 |
| Any simulator code | This slice is machinery only | Slice 2 |
