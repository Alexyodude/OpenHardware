#!/usr/bin/env python3
# OpenHardware - build the native i8086 core, on any of the three platforms.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Configure and build `core/` with CMake, and report where the library landed.

    python tools/build_core.py            # configure + build
    python tools/build_core.py --clean    # from scratch
    python tools/build_core.py --path     # print the library path, build if absent

## Why this is not just `cmake --build`

On Linux and macOS it very nearly is. On Windows it cannot be.

MSVC needs four environment variables that its installer deliberately does not
set globally -- `PATH`, `INCLUDE`, `LIB` and `LIBPATH`. Visual Studio ships
`vcvarsall.bat` to set them, and a shell that has not run it gets a compiler
that compiles and a linker that cannot find `kernel32.lib`. That is exactly
how this failed the first time, and the failure reads as a broken toolchain
rather than a missing environment:

    LINK : fatal error LNK1104: cannot open file 'kernel32.lib'

Adding the SDK to `PATH` by hand is not enough either -- that fixes `rc.exe`
and leaves the library path still missing, which is a second, near-identical
error a few lines further on.

So on Windows this runs `vcvarsall.bat`, captures the environment it produces,
and hands that to CMake. The alternative is telling every contributor to
launch a Developer Command Prompt, which works right up until CI or an agent
session does not.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import platform
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
BUILD_DIR = REPO / "build"
LIB_DIR = BUILD_DIR / "lib"

#: What the shared library is called, per platform.
LIB_NAMES = {
    "Windows": "i8086.dll",
    "Darwin": "libi8086.dylib",
    "Linux": "libi8086.so",
}

_VSWHERE = pathlib.Path(
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"


class BuildError(Exception):
    """The core could not be built."""


def library_path() -> pathlib.Path:
    name = LIB_NAMES.get(platform.system())
    if name is None:
        raise BuildError(f"no library name known for {platform.system()!r}")
    return LIB_DIR / name


def _find_vcvarsall() -> pathlib.Path | None:
    if _VSWHERE.is_file():
        result = subprocess.run(
            [
                str(_VSWHERE),
                "-latest",
                "-products",
                "*",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property",
                "installationPath",
            ],
            capture_output=True,
            text=True,
        )
        root = result.stdout.strip().splitlines()
        if root:
            candidate = pathlib.Path(root[0]) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
            if candidate.is_file():
                return candidate

    # vswhere is itself optional; fall back to the standard install paths.
    for base in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ):
        for edition in ("Enterprise", "Professional", "Community", "BuildTools"):
            for year in ("2022", "2019"):
                candidate = (
                    pathlib.Path(base)
                    / "Microsoft Visual Studio"
                    / year
                    / edition
                    / "VC"
                    / "Auxiliary"
                    / "Build"
                    / "vcvarsall.bat"
                )
                if candidate.is_file():
                    return candidate
    return None


def msvc_environment(arch: str = "x64") -> dict[str, str]:
    """The environment `vcvarsall.bat` produces, as a dict.

    Run through `cmd /c "call ... && set"` and parsed back, because a batch
    file cannot export into this process any other way.
    """
    vcvarsall = _find_vcvarsall()
    if vcvarsall is None:
        raise BuildError(
            "no vcvarsall.bat found. Install Visual Studio's C++ tools, or "
            "run this from a Developer Command Prompt."
        )

    # Through a temporary batch file rather than `cmd /c "call ... && set"`.
    #
    # cmd's quoting rules are their own thing, and a path containing spaces --
    # which every default Visual Studio install has -- comes out the far side
    # with the quotes escaped into the command name itself:
    #
    #   '\"C:\Program Files (x86)\...\vcvarsall.bat\"' is not recognized
    #
    # A batch file has no such problem: the shell reads it as a file, not as
    # an argument that survived two layers of escaping.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        script = pathlib.Path(tmp) / "capture_env.bat"
        script.write_text(
            f'@echo off\r\ncall "{vcvarsall}" {arch} >nul\r\nif errorlevel 1 exit /b 1\r\nset\r\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            ["cmd", "/c", str(script)], capture_output=True, text=True
        )
    if result.returncode != 0:
        raise BuildError(
            f"vcvarsall.bat {arch} failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()[:300]}"
        )

    env: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            env[key] = value
    if "LIB" not in env:
        raise BuildError("vcvarsall.bat ran but set no LIB; the toolchain is incomplete")
    return env


def build_environment() -> dict[str, str]:
    if platform.system() != "Windows":
        return dict(os.environ)
    # Already inside a Developer Command Prompt? Then leave it alone.
    if os.environ.get("LIB") and os.environ.get("INCLUDE"):
        return dict(os.environ)
    return msvc_environment()


def _run(command: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(command, cwd=REPO, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise BuildError(
            f"{' '.join(command[:2])} failed:\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )


def build(clean: bool = False, verbose: bool = False) -> pathlib.Path:
    if shutil.which("cmake") is None:
        raise BuildError("cmake is not on PATH (pip install cmake ninja)")
    if clean and BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    env = build_environment()
    generator = ["-G", "Ninja"] if shutil.which("ninja") else []
    _run(["cmake", "-S", str(REPO), "-B", str(BUILD_DIR), *generator], env)
    _run(["cmake", "--build", str(BUILD_DIR), "--config", "Release"], env)

    path = library_path()
    if not path.is_file():
        found = sorted(p.name for p in LIB_DIR.glob("*")) if LIB_DIR.is_dir() else []
        raise BuildError(
            f"build reported success but {path.name} is not in {LIB_DIR}. Found: {found}"
        )
    if verbose:
        print(f"{path}  ({path.stat().st_size} bytes)")
    return path


def ensure_built() -> pathlib.Path:
    """The library path, building it first if it is not there."""
    path = library_path()
    return path if path.is_file() else build()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clean", action="store_true", help="delete build/ first")
    parser.add_argument("--path", action="store_true", help="print the library path only")
    args = parser.parse_args()

    try:
        path = ensure_built() if args.path else build(clean=args.clean, verbose=True)
    except BuildError as exc:
        print(f"build_core: {exc}", file=sys.stderr)
        return 1
    if args.path:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
