#!/usr/bin/env python3
# OpenHardware — verify a backend/board pair covers board.h's pure virtuals.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Checker for rules/core-interface.md.

``src/lib/board.h`` declares the contract a board must satisfy as pure
virtuals. A concrete board is assembled from two halves — a ``bsim_*`` backend
supplying the simulation surface, and a ``board_*`` supplying the UI surface —
so the union of the pair must cover every pure virtual.

A C++ compiler enforces this far better than a regex does, and where a compiler
is available it should be trusted over this tool. The reason this exists anyway
is that a toolchain is not always available: this fork's own development machine
has none, and CI cannot build until the NOGUI probe in
``.github/workflows/nogui-probe.yml`` succeeds. A fast structural check that
catches a forgotten method in milliseconds is worth having in the gap, and it
stays useful afterwards as a pre-compile smoke test.

**It proves coverage, not correctness.** A pair that passes this check may still
fail to compile for a dozen other reasons, and a method that is declared but
wrongly implemented passes trivially. Never report a passing run as evidence
that a backend works.
"""

from __future__ import annotations

import pathlib
import re
import sys


try:
    from webui import picsimlab
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from webui import picsimlab

#: Exit code meaning "did not run", distinct from 0 (ran, clean) and 1 (found
#: problems). A checker that needs upstream source and cannot find it must be
#: distinguishable from one that checked and was happy; collapsing the two is
#: how a suite goes green while checking nothing.
SKIPPED = 3


def _skip(checker: str) -> int:
    print(
        f"{checker}: SKIPPED - no PICSimLab source checkout. "
        f"Set ${picsimlab.ENV_VAR} or see docs/picsimlab-reference.md.",
        file=sys.stderr,
    )
    return SKIPPED


def board_h_default() -> pathlib.Path:
    """`src/lib/board.h` inside the PICSimLab source checkout."""
    return picsimlab.source_root() / "src" / "lib" / "board.h"



# `virtual void MStep(void) = 0;` -> MStep
_PURE_VIRTUAL = re.compile(
    r"^\s*virtual\s+[^;{]*?\b(\w+)\s*\([^;{]*\)\s*(?:const\s*)?=\s*0\s*;", re.MULTILINE
)

# `void MStep(void) override;` and `std::string GetName(void) override { ... }`
_OVERRIDE = re.compile(
    r"^\s*(?:virtual\s+)?[^;{]*?\b(\w+)\s*\([^;{]*\)\s*(?:const\s*)?override\b",
    re.MULTILINE,
)


class ContractError(Exception):
    """A header could not be read, or declares nothing at all."""


def contract_methods(header: pathlib.Path | None = None) -> set[str]:
    """Names of every pure virtual declared in board.h."""
    board_h = board_h_default() if header is None else header
    if not board_h.is_file():
        raise ContractError(f"{board_h}: not found")
    names = set(_PURE_VIRTUAL.findall(board_h.read_text(encoding="utf-8", errors="replace")))
    if not names:
        # An empty contract would make every pair pass, which is the vacuous
        # green this project exists to prevent.
        raise ContractError(f"{board_h}: no pure virtuals found; the regex is wrong")
    return names


def overridden_methods(paths: list[pathlib.Path]) -> set[str]:
    """Names declared with `override` across the given headers."""
    if not paths:
        raise ContractError("no headers given")
    names: set[str] = set()
    for path in paths:
        if not path.is_file():
            raise ContractError(f"{path}: not found")
        names |= set(_OVERRIDE.findall(path.read_text(encoding="utf-8", errors="replace")))
    if not names:
        raise ContractError(
            f"{[str(p) for p in paths]}: no overrides found; a pair declaring "
            f"nothing must not report full coverage"
        )
    return names


def missing_methods(
    headers: list[pathlib.Path], board_h: pathlib.Path | None = None
) -> set[str]:
    """Pure virtuals that the given pair of headers does not override."""
    return contract_methods(board_h) - overridden_methods(headers)


# Pairs this fork owns or uses as a reference. Upstream pairs are listed because
# they demonstrably compile, so a failure against them means the checker is
# wrong rather than the code.
def pairs() -> dict[str, list[pathlib.Path]]:
    """Header pairs to check, resolved against the PICSimLab source checkout."""
    root = picsimlab.source_root()
    return {
        "uCboard (upstream reference)": [
            root / "src" / "sim_backend" / "bsim_ucsim.h",
            root / "src" / "boards" / "board_uCboard.h",
        ],
    }


def main() -> int:
    if picsimlab.find_source() is None:
        return _skip("check_board_contract")
    failed = False
    for label, headers in pairs().items():
        try:
            missing = missing_methods(headers)
        except ContractError as exc:
            print(f"check_board_contract: {exc}", file=sys.stderr)
            return 2
        if missing:
            failed = True
            print(f"{label}: {len(missing)} pure virtual(s) not overridden:", file=sys.stderr)
            for name in sorted(missing):
                print(f"  {name}", file=sys.stderr)
        else:
            print(f"{label}: covers all {len(contract_methods())} pure virtuals")
    if failed:
        print(
            "check_board_contract: incomplete board contract, per "
            "rules/core-interface.md",
            file=sys.stderr,
        )
        return 1
    print("check_board_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
