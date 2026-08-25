# OpenHardware - the enforcement that has to survive a fresh clone.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Guards on `tools/install_hooks.py` and the tracked pre-commit hook.

`rules/ticket-claims.md` section 7 records why these exist: the strongest
check in the claim system, `tools/ticket_guard.py`, is registered in
`.claude/settings.json`, which is git-ignored -- so it protects one machine and
no clone. The tracked git hook is the rung that ships.

Nothing here mutates the repository's git config. `install_git_hooks` writes,
so it is exercised only through `check_only=True`, and the parts that decide
*whether* to write are pure functions given synthetic settings.
"""

from __future__ import annotations

import pathlib

from tools import check_ticket_claims as C
from tools import install_hooks as H

REPO = pathlib.Path(__file__).resolve().parents[2]
HOOK = REPO / "tools" / "githooks" / "pre-commit"


def test_the_pre_commit_hook_is_a_tracked_file():
    """The whole point: its content is in git, unlike the PreToolUse hook."""
    assert HOOK.is_file(), f"{HOOK} does not exist"
    text = HOOK.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: MIT" in text
    assert "check_ticket_claims.py" in text and "--staged" in text, (
        "the hook must invoke the claim checker over staged files; without "
        "--staged it would ask what the branch changed, which is the question "
        "CI already asks after the fact"
    )


def test_the_hook_survives_a_machine_without_python_on_path():
    """It degrades to a warning rather than blocking every commit.

    A hook that hard-fails where python is missing makes the repository
    uncommittable on that machine, which gets it uninstalled -- and an
    uninstalled check protects nothing.
    """
    text = HOOK.read_text(encoding="utf-8")
    assert "python3" in text, "no fallback interpreter"
    assert "exit 0" in text, "no non-blocking path when python is absent"


def test_staged_files_reads_the_index_not_the_branch():
    """`changed_files` and `staged_files` answer different questions."""
    staged = C.staged_files()
    assert isinstance(staged, list)
    assert all(isinstance(p, str) for p in staged)
    assert all("\\\\" not in p for p in staged), "paths must be normalised"


def test_an_existing_registration_is_recognised_rather_than_duplicated():
    """Idempotence, at the level that decides whether to write."""
    registered = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit|Write|NotebookEdit",
                    "hooks": [{"type": "command", "command": "python tools/ticket_guard.py"}],
                }
            ]
        }
    }
    assert H._already_registered(registered)
    assert not H._already_registered({})
    assert not H._already_registered({"hooks": {"PreToolUse": []}})
    other_hook = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
            ]
        }
    }
    assert not H._already_registered(other_hook), (
        "someone else's PreToolUse entry must not be mistaken for ours"
    )


def test_check_only_never_reports_a_mutation():
    """`--check` is safe to run anywhere, including in CI."""
    for line in (H.install_git_hooks(check_only=True), H.install_claude_hook(check_only=True)):
        assert not line.startswith("set "), line
        assert not line.startswith("registered "), line


def test_the_ticket_docs_name_no_tool_that_does_not_exist():
    """Documentation that names a missing tool is worse than none.

    This is the failure that started the thread these hooks came out of:
    `tickets check` was documented under Housekeeping and had never run once,
    and OH-40 found error messages telling a reader to run a script that had
    been deleted. A doc naming a tool that is not there is believed.

    Matched in **command position** -- after `python` or `bash` -- rather than
    anywhere the string appears. The first draft matched any path and failed
    immediately on `tools/sub/x.py`, which is not a tool at all: it is the
    example in the claim-pattern table of a path `tools/*.py` does *not*
    match. Keying on the substring rather than on the instruction is the same
    error `rules/board-claims.md` records for the word "firmware".
    """
    import re

    docs = REPO / "docs" / "tickets" / "README.md"
    text = docs.read_text(encoding="utf-8")
    pattern = r"(?:python|bash)\s+(tools/[A-Za-z0-9_/]+\.(?:py|sh))\b"
    named = set(re.findall(pattern, text))
    assert named, "no runnable tools referenced; the pattern likely stopped matching"

    missing = sorted(n for n in named if not (REPO / n).exists())
    assert not missing, f"{docs.name} says to run tools that do not exist: {missing}"

    # Negative control, against a string really in that file rather than a
    # hypothetical: a path used to explain a glob is not an instruction.
    assert "tools/sub/x.py" in text, "the claim-pattern example vanished"
    assert "tools/sub/x.py" not in named


def test_the_install_step_is_a_command_not_a_json_block():
    """The install step used to be a JSON block a person retyped.

    It could not be verified, could not be re-run, and drifted from the hook
    it was meant to register. `install_hooks.py` replaced it precisely so the
    instruction is executable, so the docs must not fall back to prose.
    """
    text = (REPO / "docs" / "tickets" / "README.md").read_text(encoding="utf-8")
    section = text[text.index("## Installing"):text.index("## The file format")]
    assert "tools/install_hooks.py" in section, "the install step is not the installer"
    assert '"PreToolUse": [' not in section, (
        "the hand-typed registration block is back in the docs; it drifts from "
        "install_hooks.py's GUARD_HOOK and cannot be checked"
    )
