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

## Why the build type is read back, not assumed

Until OH-220 every core built here on Windows was Debug -- measured through
`session.run` at 39% to 73% of a Release core's rate -- while this file said
`--config Release` and CMakeLists.txt said Release too. Neither was true: Ninja ignores `--config`, and MSVC's platform
module had cached Debug before CMakeLists.txt's default ran. CMakeLists.txt
now sets that default early enough, but a cache written before then still
holds Debug, and a cached value outlives any default. So `configure` reads the
type back out of the cache and reconfigures a tree that is not Release, rather
than building whatever it finds.
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

#: How each platform decorates a library name. `{}` is the core's name.
#:
#: This was three literals naming i8086 directly. It is a pattern now because
#: `core/` is about to hold more than one architecture, and a hardcoded name
#: is the kind of thing a second core discovers by failing to build.
LIB_NAME_PATTERNS = {
    "Windows": "{}.dll",
    "Darwin": "lib{}.dylib",
    "Linux": "lib{}.so",
}

#: The directory every core lives under. A core is any subdirectory of it with
#: a CMakeLists.txt, which is also exactly what the top-level CMakeLists adds.
CORE_DIR = REPO / "core"

#: The core to build when a caller does not say. Every existing caller means
#: this one, and naming it here beats threading a default through five
#: signatures.
DEFAULT_CORE = "i8086"

_VSWHERE = pathlib.Path(
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"


class BuildError(Exception):
    """The core could not be built."""


def cores() -> list[str]:
    """Every architecture under `core/`, discovered rather than listed.

    Discovered so that adding one is adding a directory, and so that this file
    and the top-level CMakeLists cannot disagree about which cores exist --
    they answer the question the same way.
    """
    if not CORE_DIR.is_dir():
        return []
    return sorted(
        child.name for child in CORE_DIR.iterdir()
        if (child / "CMakeLists.txt").is_file()
    )


def library_path(core: str = DEFAULT_CORE) -> pathlib.Path:
    pattern = LIB_NAME_PATTERNS.get(platform.system())
    if pattern is None:
        raise BuildError(f"no library name known for {platform.system()!r}")
    return LIB_DIR / pattern.format(core)


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


def cached_build_type(build_dir: pathlib.Path) -> str | None:
    """The build type `build_dir`'s CMakeCache.txt holds.

    None for a multi-configuration generator (Visual Studio, Ninja
    Multi-Config), whose cache lists CMAKE_CONFIGURATION_TYPES instead and
    which picks one per build -- `--config Release` in `build`. "" for a
    single-configuration cache that names no type, which CMake builds with no
    optimisation flags at all.
    """
    entries: dict[str, str] = {}
    for line in (build_dir / "CMakeCache.txt").read_text(encoding="utf-8").splitlines():
        # `KEY:TYPE=VALUE`. `//` and `#` lines are CMake's own comments, and
        # the header's `# KEY:TYPE=VALUE` is one of them.
        if line.startswith(("//", "#")):
            continue
        key, sep, value = line.partition("=")
        if sep:
            entries[key.partition(":")[0]] = value
    if "CMAKE_CONFIGURATION_TYPES" in entries:
        return None
    return entries.get("CMAKE_BUILD_TYPE", "")


def configure(build_dir: pathlib.Path, env: dict[str, str]) -> None:
    """Configure `build_dir` for a Release build, whatever its cache held.

    The first configure names no type: CMakeLists.txt's default is what makes
    a fresh tree Release, and it is what a configure by hand gets too. Then the
    cache is read back, and a single-configuration tree holding anything else
    is reconfigured Release, saying so -- a Debug cached before OH-220, a type
    somebody set by hand, or the CMAKE_BUILD_TYPE environment variable.

    Reconfigured rather than refused, because `build_dir` is this script's
    tree and this script builds Release. A Debug build belongs in a directory
    of its own, where nothing here will touch it.
    """
    command = ["cmake", "-S", str(REPO), "-B", str(build_dir)]
    if shutil.which("ninja"):
        command += ["-G", "Ninja"]
    _run(command, env)
    found = cached_build_type(build_dir)
    if found in (None, "Release"):
        return
    print(
        f"build_core: {build_dir} is configured {found!r}, not Release; "
        f"reconfiguring it Release",
        file=sys.stderr,
    )
    _run([*command, "-DCMAKE_BUILD_TYPE=Release"], env)
    found = cached_build_type(build_dir)
    if found not in (None, "Release"):
        raise BuildError(
            f"configured {build_dir} with -DCMAKE_BUILD_TYPE=Release and its "
            f"CMakeCache.txt still says {found!r}"
        )


def build(clean: bool = False, verbose: bool = False) -> pathlib.Path:
    if shutil.which("cmake") is None:
        raise BuildError("cmake is not on PATH (pip install cmake ninja)")
    if clean and BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    env = build_environment()
    configure(BUILD_DIR, env)
    # `--config` is read by a multi-configuration generator only. Ninja builds
    # whatever `configure` cached, which is why that is checked there.
    _run(["cmake", "--build", str(BUILD_DIR), "--config", "Release"], env)

    # Every core is checked, not just the default one. A build that reports
    # success while producing nothing is the failure this guards against, and
    # it is per-core: one architecture can build while another silently emits
    # no library at all.
    built = []
    missing = []
    for core in cores():
        path = library_path(core)
        (built if path.is_file() else missing).append(path)
    if missing:
        found = sorted(p.name for p in LIB_DIR.glob("*")) if LIB_DIR.is_dir() else []
        raise BuildError(
            f"build reported success but {[p.name for p in missing]} "
            f"{'is' if len(missing) == 1 else 'are'} not in {LIB_DIR}. Found: {found}"
        )
    if verbose:
        for path in built:
            print(f"{path}  ({path.stat().st_size} bytes)")
    return library_path(DEFAULT_CORE)


def ensure_built(core: str = DEFAULT_CORE) -> pathlib.Path:
    """The library path for one core, building everything first if it is absent.

    A library that exists is returned as it is: not rebuilt when its source
    changes, and not when its tree's build type is wrong either (OH-220).
    Rebuilding from inside a load would relink a DLL that the server or another
    test session may hold open, and a failed build here reaches a suite as a
    skip. `tests/rules/test_build_core.py` fails instead, on a build/ that is
    not Release, and `python tools/build_core.py` is the fix for both.
    """
    path = library_path(core)
    if path.is_file():
        return path
    build()
    return library_path(core)


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
