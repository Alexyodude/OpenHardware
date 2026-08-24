#!/usr/bin/env python3
# OpenHardware - build Hazard3's rvcpp, the RV32 oracle.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Build `third_party/hazard3/test/sim/rvcpp` into `third_party/rvcpp-build`.

    git clone --depth 1 https://github.com/Wren6991/Hazard3 third_party/hazard3
    python tests/riscv32/oracle/build_rvcpp.py

## Why this exists rather than `make`

rvcpp ships a Makefile that calls `g++`. The development machine for this
project is Windows with MSVC and has neither, which is also why
`tools/build_core.py` exists in the shape it does. Three source-level
incompatibilities stand between MSVC and that Makefile, and all three are
handled by force-including `rvcpp_msvc_shim.h` rather than by patching the
vendor tree: a patched checkout is one nobody can re-fetch, and this oracle's
value depends on being upstream's code rather than ours.

docs/architectures.md 2.1b records that this was done once before, by hand, in
a temporary directory. The recipe was described in prose and the shim was
thrown away. This is that recipe, kept.

## Where g++ exists, it is used

Not for portability points -- because the vendor Makefile is the reference
build, and a machine that can run it should. The shim path is the fallback,
and its output is checked the same way either way: by running the oracle.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
SOURCE = REPO / "third_party" / "hazard3" / "test" / "sim" / "rvcpp"
OUTPUT = REPO / "third_party" / "rvcpp-build"
SHIM = pathlib.Path(__file__).resolve().parent / "rvcpp_msvc_shim.h"

SOURCES = ("main.cpp", "rv_core.cpp", "rv_csr.cpp")


class OracleBuildError(Exception):
    """The oracle could not be built, with the compiler output that says why."""


def binary() -> pathlib.Path:
    return OUTPUT / ("rvcpp.exe" if sys.platform == "win32" else "rvcpp")


def _sources() -> list[str]:
    missing = [name for name in SOURCES if not (SOURCE / name).is_file()]
    if missing:
        raise OracleBuildError(
            f"{SOURCE} is missing {missing}. Clone the oracle:\n"
            f"  git clone --depth 1 https://github.com/Wren6991/Hazard3 "
            f"third_party/hazard3"
        )
    return [str(SOURCE / name) for name in SOURCES]


def _run(command: list[str], env: dict[str, str] | None = None) -> None:
    result = subprocess.run(
        command, cwd=OUTPUT, env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise OracleBuildError(
            f"{command[0]} exited {result.returncode}:\n"
            f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
        )


def build_with_gpp(compiler: str) -> pathlib.Path:
    """The vendor Makefile's own command line, minus make."""
    _run([compiler, "-std=c++17", "-O3", "-Wall", "-Wextra",
          "-I", str(SOURCE / "include"), *_sources(), "-o", str(binary())])
    return binary()


def build_with_msvc() -> pathlib.Path:
    """MSVC, with the shim force-included so the vendor tree stays as cloned."""
    try:
        from tools import build_core
    except ModuleNotFoundError:
        sys.path.insert(0, str(REPO))
        from tools import build_core

    if not SHIM.is_file():
        raise OracleBuildError(f"{SHIM}: the MSVC shim is missing")
    try:
        env = build_core.msvc_environment()
    except build_core.BuildError as exc:
        raise OracleBuildError(str(exc)) from exc

    _run(["cl", "/nologo", "/std:c++17", "/O2", "/EHsc", "/W3",
          f"/I{SOURCE / 'include'}", f"/FI{SHIM}", *_sources(),
          f"/Fo{OUTPUT}" + "\\", f"/Fe{binary()}"], env=env)
    return binary()


def build() -> pathlib.Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is not None:
        return build_with_gpp(compiler)
    if sys.platform != "win32":
        raise OracleBuildError(
            "no g++ or clang++ on PATH, and MSVC is Windows-only. Install a "
            "C++17 compiler; the oracle is 1,562 lines and needs nothing else."
        )
    return build_with_msvc()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="rebuild even if the binary is already there")
    args = parser.parse_args()

    if binary().is_file() and not args.force:
        print(f"{binary()} already built; --force to rebuild")
        return 0
    try:
        path = build()
    except OracleBuildError as exc:
        print(f"build_rvcpp: {exc}", file=sys.stderr)
        return 1
    print(f"built {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
