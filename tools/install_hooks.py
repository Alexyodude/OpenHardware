#!/usr/bin/env python3
# OpenHardware - install the enforcement that cannot ship in a tracked file.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Point git at the tracked hooks, and register the Claude write-time guard.

`rules/ticket-claims.md` section 7 records the hole this closes: the claim
system's best check, `tools/ticket_guard.py`, refuses a bad write *before* it
lands -- and nothing invokes it on a fresh clone, because the only thing that
can is a `PreToolUse` entry in `.claude/settings.json`, and `.claude/` is
git-ignored. So the check that mattered most was the one least likely to be
running.

`.claude/` stays ignored. The comment above it in `.gitignore` says it is
installed from a personal template and deliberately not committed per-project;
un-ignoring it to smuggle a hook in would commit one machine's settings to fix
a repository's problem. So the registration is *generated* here instead of
tracked, and the thing that is tracked is the git hook, whose content ships and
whose installation is one command rather than a JSON block someone retypes.

Two rungs, deliberately different in strength:

* **`tools/githooks/pre-commit`** -- weaker and universal. It sees the write
  after it happened, but it catches any tool's commit and its content is in
  git. This is what makes enforcement survive a clone.
* **the Claude `PreToolUse` hook** -- stronger and local. It refuses the write
  itself, and it can only ever exist on one machine at a time.

Both are idempotent. Run it twice and the second run reports that there was
nothing to do, which is the property that lets it go in a setup script.

    python tools/install_hooks.py            # install both
    python tools/install_hooks.py --check    # report, change nothing
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Where the tracked hooks live, relative to the repository root. `git config`
#: takes a path relative to the working directory, and this is what makes the
#: hook's *content* a tracked file rather than an untracked copy under .git/.
HOOKS_PATH = "tools/githooks"

#: The Claude Code registration, generated rather than tracked.
GUARD_HOOK = {
    "matcher": "Edit|Write|NotebookEdit",
    "hooks": [{"type": "command", "command": "python tools/ticket_guard.py"}],
}


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    return done.stdout.strip()


def git_hooks_state() -> str:
    """What `core.hooksPath` is set to, or the empty string."""
    return _git("config", "--get", "core.hooksPath")


def install_git_hooks(check_only: bool = False) -> str:
    """Point git at the tracked hooks directory. Returns what happened."""
    current = git_hooks_state()
    if current == HOOKS_PATH:
        return f"core.hooksPath is already {HOOKS_PATH}"
    if current:
        return (
            f"REFUSED: core.hooksPath is {current!r}, not unset. Something else "
            f"owns your hooks; set it to {HOOKS_PATH!r} by hand if you mean to "
            f"replace it, rather than having this tool silently take it over."
        )
    if check_only:
        return f"WOULD SET core.hooksPath to {HOOKS_PATH}"
    _git("config", "core.hooksPath", HOOKS_PATH)
    return f"set core.hooksPath to {HOOKS_PATH}"


def claude_settings_path() -> pathlib.Path:
    return REPO / ".claude" / "settings.json"


def _already_registered(settings: dict) -> bool:
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        for hook in entry.get("hooks", []):
            if "ticket_guard.py" in hook.get("command", ""):
                return True
    return False


def install_claude_hook(check_only: bool = False) -> str:
    """Merge the PreToolUse registration into .claude/settings.json."""
    path = claude_settings_path()
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return (
                f"REFUSED: {path} is not valid JSON ({exc}). Fix it by hand -- "
                f"overwriting a settings file this tool cannot read would "
                f"destroy whatever else is in it."
            )
    else:
        settings = {}

    if _already_registered(settings):
        return "the Claude write-time guard is already registered"
    if check_only:
        return f"WOULD register the write-time guard in {path}"

    settings.setdefault("hooks", {}).setdefault("PreToolUse", []).append(GUARD_HOOK)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return f"registered the write-time guard in {path}"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    check_only = "--check" in argv

    lines = [install_git_hooks(check_only), install_claude_hook(check_only)]
    for line in lines:
        print(f"install_hooks: {line}")

    if any(line.startswith("REFUSED") for line in lines):
        return 1
    if check_only and any(line.startswith("WOULD") for line in lines):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
