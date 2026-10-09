# OpenHardware — the cores build Release, on every generator (OH-220).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Until OH-220 every core built on Windows was Debug -- `/Od /RTC1` -- and
# nothing here noticed, because every test counts steps and a slow step counts
# the same as a fast one. Two things were wrong at once: CMakeLists.txt's
# Release default ran after project(), by which time MSVC's platform module had
# cached Debug, and `tools/build_core.py`'s `--config Release` means nothing to
# Ninja, the generator it prefers.
#
# Each test holds one link, and none of them builds anything:
#
#   * `cached_build_type` reads a cache right -- synthesised caches, no CMake;
#   * a configure that names no type is Release -- CMakeLists.txt, configured
#     for real into tmp_path;
#   * a type in the environment is kept where CMake applies it, and an empty
#     one gets Release -- configured for real, the variable set;
#   * a tree already cached Debug is reconfigured, not built Debug --
#     `build_core.configure`, for real, on a tree made the way build/ was made
#     before the fix;
#   * this checkout's own build/ is Release. It is the one that matters, and
#     an existing checkout FAILS it until `python tools/build_core.py` is run
#     once, because `ensure_built` never rebuilds a library that exists;
#   * `debug_runtime` tells a Debug library from a Release one -- synthesised
#     import names, no compiler -- and `ensure_built` says so on loading one;
#   * this checkout's own libraries are Release, whatever the cache says: a
#     multi-config build/ caches no type, and a tree configured Release and
#     not yet built still holds Debug DLLs. Windows only, where MSVC's runtime
#     names the build type; elsewhere the cache test above is what holds.

import platform
import shutil
import subprocess

import pytest

from tools import build_core

#: The head of a real cache, from `build/` configured by `build_core.py
#: --clean` on 2026-10-09 before the fix, trimmed. The comment lines are kept
#: because a real cache has them, and the key is `CMAKE_BUILD_TYPE:STRING`, so
#: a parser that forgot the `:TYPE` would find no build type at all.
NINJA_CACHE = """\
# This is the CMakeCache file.
# The syntax for the file is as follows:
# KEY:TYPE=VALUE
# KEY is the name of a variable in the cache.

########################
# EXTERNAL cache entries
########################

//Choose the type of build, options are: None Debug Release RelWithDebInfo
// MinSizeRel ...
CMAKE_BUILD_TYPE:STRING={build_type}

//Flags used by the CXX compiler during DEBUG builds.
CMAKE_CXX_FLAGS_DEBUG:STRING=/Zi /Ob0 /Od /RTC1

//Flags used by the CXX compiler during RELEASE builds.
CMAKE_CXX_FLAGS_RELEASE:STRING=/O2 /Ob2 /DNDEBUG

//Name of generator.
CMAKE_GENERATOR:INTERNAL=Ninja
"""

#: The same, from a Visual Studio 17 2022 configure of a scratch project on
#: the same day: no CMAKE_BUILD_TYPE at all, and the list instead.
VISUAL_STUDIO_CACHE = """\
# This is the CMakeCache file.
# KEY:TYPE=VALUE

//Semicolon separated list of supported configuration types, only
// supports Debug, Release, MinSizeRel, and RelWithDebInfo, anything
// else will be ignored.
CMAKE_CONFIGURATION_TYPES:STRING=Debug;Release;MinSizeRel;RelWithDebInfo

//Name of generator.
CMAKE_GENERATOR:INTERNAL=Visual Studio 17 2022
"""


def write_cache(directory, text):
    directory.mkdir()
    (directory / "CMakeCache.txt").write_text(text, encoding="utf-8")
    return directory


def test_a_cache_says_which_build_type_it_holds(tmp_path):
    cases = {
        "Debug": (NINJA_CACHE.format(build_type="Debug"), "Debug"),
        "Release": (NINJA_CACHE.format(build_type="Release"), "Release"),
        # Single-config with no type named: CMake's "no flags at all".
        "untyped": (NINJA_CACHE.replace("CMAKE_BUILD_TYPE:STRING={build_type}\n", ""), ""),
        "visual-studio": (VISUAL_STUDIO_CACHE, None),
    }
    for name, (text, expected) in cases.items():
        found = build_core.cached_build_type(write_cache(tmp_path / name, text))
        assert found == expected, f"{name}: expected {expected!r}, read {found!r}"


@pytest.fixture(scope="module")
def toolchain():
    """The environment `build_core` configures with, or skip saying why not.

    CMAKE_BUILD_TYPE is taken out of it: the environment variable is a
    configure that names a type, and these tests are about one that does not.
    """
    if shutil.which("cmake") is None:
        pytest.skip("SKIPPED: cmake is not on PATH, so nothing can be configured")
    try:
        env = build_core.build_environment()
    except build_core.BuildError as exc:
        pytest.skip(f"SKIPPED: no C++ toolchain to configure with: {exc}")
    env.pop("CMAKE_BUILD_TYPE", None)
    return env


def configure_by_hand(build_dir, env, *extra):
    """`cmake -S <repo> -B <build_dir>` with build_core's generator, plus `extra`.

    Not `build_core.configure`, which would reconfigure whatever this left:
    these are the configures that function has to cope with.
    """
    command = ["cmake", "-S", str(build_core.REPO), "-B", str(build_dir)]
    if shutil.which("ninja"):
        command += ["-G", "Ninja"]
    result = subprocess.run([*command, *extra], env=env, capture_output=True, text=True)
    assert result.returncode == 0, f"{command + list(extra)} failed:\n{result.stdout}\n{result.stderr}"


def test_a_configure_that_names_no_build_type_is_release(tmp_path, toolchain):
    build_dir = tmp_path / "build"
    configure_by_hand(build_dir, toolchain)
    found = build_core.cached_build_type(build_dir)
    if found is None:
        pytest.skip("SKIPPED: no ninja, so the generator is multi-config; it caches no "
                    "build type and takes `--config Release` at build time instead")
    assert found == "Release", (
        f"a configure of CMakeLists.txt naming no build type cached {found!r}. On MSVC "
        f"that is Windows-MSVC.cmake's CMAKE_BUILD_TYPE_INIT, which project() caches: "
        f"the Release default must run before project() to win (OH-220)"
    )


def test_a_build_type_in_the_environment_is_kept_and_an_empty_one_is_not(tmp_path, toolchain):
    """CMakeLists' default yields to $CMAKE_BUILD_TYPE only where CMake applies it.

    That is from CMake 3.22, and only when it is not empty. Yielding anywhere
    else hands the type to the platform's INIT, which on MSVC is Debug: an
    empty variable did exactly that under CMake 4.4.2, and RelWithDebInfo did
    under 3.21.4, which ignores the variable.
    """
    version = subprocess.run(["cmake", "--version"], capture_output=True, text=True,
                             check=True).stdout.split()[2]  # "cmake version 4.4.2"
    applied = tuple(int(part) for part in version.split(".")[:2]) >= (3, 22)
    cases = {
        "RelWithDebInfo": "RelWithDebInfo" if applied else "Release",
        "": "Release",
    }
    for value, expected in cases.items():
        build_dir = tmp_path / (value or "empty")
        configure_by_hand(build_dir, {**toolchain, "CMAKE_BUILD_TYPE": value})
        found = build_core.cached_build_type(build_dir)
        if found is None:
            pytest.skip("SKIPPED: no ninja, so the generator is multi-config; it caches no "
                        "build type for the environment to set")
        assert found == expected, (
            f"CMake {version} with CMAKE_BUILD_TYPE={value!r} in the environment cached "
            f"{found!r}, expected {expected!r}"
        )


def test_a_tree_cached_debug_is_reconfigured_release_and_says_so(tmp_path, toolchain, capsys):
    build_dir = tmp_path / "build"
    configure_by_hand(build_dir, toolchain, "-DCMAKE_BUILD_TYPE=Debug")
    if build_core.cached_build_type(build_dir) is None:
        pytest.skip("SKIPPED: no ninja, so the generator is multi-config and has no "
                    "cached build type to be left wrong")
    assert build_core.cached_build_type(build_dir) == "Debug", "the tree was not made Debug"

    build_core.configure(build_dir, toolchain)

    found = build_core.cached_build_type(build_dir)
    assert found == "Release", (
        f"build_core.configure left {build_dir} cached {found!r}; the build after it "
        f"would have been that, not Release"
    )
    said = capsys.readouterr().err
    assert "'Debug'" in said, f"reconfigured without saying what it found: {said!r}"


def test_this_checkouts_build_is_release():
    cache = build_core.BUILD_DIR / "CMakeCache.txt"
    if not cache.is_file():
        pytest.skip(f"SKIPPED: no {cache} in this checkout; python tools/build_core.py "
                    f"configures and builds one")
    found = build_core.cached_build_type(build_core.BUILD_DIR)
    if found is None:
        pytest.skip(f"SKIPPED: {cache} is multi-config, which caches no build type; "
                    f"build_core.py builds it with --config Release")
    assert found == "Release", (
        f"{cache} says CMAKE_BUILD_TYPE={found!r}, so the cores in "
        f"{build_core.LIB_DIR} are not Release builds and run at a fraction of the "
        f"speed. Run: python tools/build_core.py -- it reconfigures the tree (OH-220)"
    )


#: The DLL names in a core's import table, read out of i8086.dll and
#: cortexm0.dll from a Debug build/lib and a Release one on 2026-10-10, and
#: NUL-separated as an import table's are. The DLLs are build outputs and not
#: committed; these are what `debug_runtime` reads in them.
RELEASE_IMPORTS = b"\0".join([
    b"KERNEL32.dll", b"MSVCP140.dll", b"VCRUNTIME140.dll", b"VCRUNTIME140_1.dll",
    b"api-ms-win-crt-heap-l1-1-0.dll", b"api-ms-win-crt-runtime-l1-1-0.dll",
])
DEBUG_IMPORTS = b"\0".join([
    b"KERNEL32.dll", b"MSVCP140D.dll", b"VCRUNTIME140D.dll", b"VCRUNTIME140_1D.dll",
    b"ucrtbased.dll",
])


def test_a_library_says_whether_it_is_a_debug_build(tmp_path):
    # Either debug runtime alone is enough to say so: a real Debug core
    # imports both, but each name is checked, not only the first one found.
    cases = {
        "debug.dll": (DEBUG_IMPORTS, "VCRUNTIME140D.dll"),
        "ucrt-only.dll": (b"KERNEL32.dll\0ucrtbased.dll", "ucrtbased.dll"),
        "release.dll": (RELEASE_IMPORTS, None),
    }
    for name, (imports, expected) in cases.items():
        library = tmp_path / name
        library.write_bytes(b"MZ\0" + imports + b"\0")
        found = build_core.debug_runtime(library)
        assert found == expected, f"{name}: expected {expected!r}, read {found!r}"


def test_a_debug_library_is_loaded_with_a_warning_and_not_rebuilt(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_core, "LIB_DIR", tmp_path)
    monkeypatch.setattr(build_core, "build", lambda *a, **k: pytest.fail("ensure_built rebuilt"))
    library = build_core.library_path("i8086")

    library.write_bytes(b"MZ\0" + RELEASE_IMPORTS + b"\0")
    assert build_core.ensure_built("i8086") == library
    said = capsys.readouterr().err
    assert said == "", f"warned of a Release library: {said!r}"

    library.write_bytes(b"MZ\0" + DEBUG_IMPORTS + b"\0")
    assert build_core.ensure_built("i8086") == library
    said = capsys.readouterr().err
    assert f"{library.name} imports VCRUNTIME140D.dll" in said, (
        f"loaded a Debug library without saying so: {said!r}"
    )


def test_this_checkouts_libraries_are_release():
    if platform.system() != "Windows":
        pytest.skip("SKIPPED: only MSVC's runtime names the build type in a library; "
                    "off Windows the cache says it, and "
                    "test_this_checkouts_build_is_release reads that")
    built = [path for path in map(build_core.library_path, build_core.cores())
             if path.is_file()]
    if not built:
        pytest.skip(f"SKIPPED: no core built in {build_core.LIB_DIR}; "
                    f"python tools/build_core.py builds them")
    debug = [f"{path.name} imports {runtime}" for path in built
             if (runtime := build_core.debug_runtime(path)) is not None]
    assert not debug, (
        f"{build_core.LIB_DIR} holds Debug builds whatever its CMakeCache.txt says -- "
        f"{'; '.join(debug)} -- and they run at a fraction of Release's speed. "
        f"Run: python tools/build_core.py (OH-220)"
    )
