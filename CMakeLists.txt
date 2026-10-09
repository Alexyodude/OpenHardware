# OpenHardware
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Only the native core is built here. Everything else in this repository is
# Python and needs no build step; PICSimLab is external and builds itself
# (docs/picsimlab-reference.md).

cmake_minimum_required(VERSION 3.20)

# Release unless the configure names a build type -- and BEFORE project(),
# which is the whole fix (OH-220).
#
# project() is where CMake loads the compiler's platform module, and on MSVC
# that module answers this question first. Modules/Platform/Windows-MSVC.cmake
# says, at line 150 in CMake 4.4.2:
#
#     # default to Debug builds
#     set(CMAKE_BUILD_TYPE_INIT Debug)
#
# and CMakeInitializeConfigs.cmake:22 caches CMAKE_BUILD_TYPE from it, still
# inside project(). This default used to sit after project(), where
# `NOT CMAKE_BUILD_TYPE` found that Debug and did nothing, so every core built
# on Windows was `/Od /RTC1`. GCC, and Clang off Windows, set no such INIT,
# which is why only Windows was affected. Clang on Windows sets it whenever it
# targets the MSVC ABI: clang-cl by including this same Windows-MSVC.cmake
# (Platform/Windows-Clang.cmake:230), and clang++ itself at
# Platform/Windows-Clang.cmake:272, `set(CMAKE_BUILD_TYPE_INIT Debug)`.
#
# Before project(), a type already in the cache is one somebody asked for --
# `-DCMAKE_BUILD_TYPE=<type>`, or an earlier configure of the same tree -- and
# is kept. So is the CMAKE_BUILD_TYPE environment variable, which CMake applies
# inside project() and which a default here would otherwise beat. An empty
# value counts as unset, in the cache and in the environment alike, and gets
# Release.
#
# The environment variable is yielded to only where CMake applies it: from
# 3.22 (Help/envvar/CMAKE_BUILD_TYPE.rst: "versionadded:: 3.22"; the 3.22
# release notes: "The CMAKE_BUILD_TYPE environment variable was added"), and
# only when it is not empty. Yielding where CMake ignores it hands the type to
# the platform's INIT, which on MSVC is Debug again: under the check this
# replaced, `NOT DEFINED ENV{CMAKE_BUILD_TYPE}`, CMake 3.21.4 with
# RelWithDebInfo in the environment and CMake 4.4.2 with an empty one each
# cached Debug. Gated here rather than raising the minimum to 3.22,
# because that would also turn CMP0121 to CMP0128 NEW for the whole project,
# and CMP0128 changes how the C++ standard and extension flags are chosen --
# every core's compile line, for a reason that is not the build type.
#
# A multi-configuration generator (Visual Studio, Ninja Multi-Config) has no
# CMAKE_BUILD_TYPE and picks the type per build; `tools/build_core.py` asks it
# for Release with `--config Release`.
#
# Why here and not `-DCMAKE_BUILD_TYPE=Release` passed by tools/build_core.py:
# a default in this file holds for every configure that names no type -- by
# hand, from an IDE, in CI -- and one passed by the script holds for the script
# alone. What no default can reach is a tree configured before this fix, whose
# cached Debug outlives it; that is the script's job, in `configure` there.
get_property(multi_config GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)
set(env_build_type "")
if(CMAKE_VERSION VERSION_GREATER_EQUAL 3.22)
  set(env_build_type "$ENV{CMAKE_BUILD_TYPE}")
endif()
if(NOT multi_config AND NOT CMAKE_BUILD_TYPE AND env_build_type STREQUAL "")
  set(CMAKE_BUILD_TYPE Release CACHE STRING
    "Choose the type of build: Debug Release RelWithDebInfo MinSizeRel" FORCE)
endif()

project(openhardware_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Hidden by default so the shared library exports exactly what abi.h marks,
# and nothing else. Without this, a Linux build exports every symbol and the
# surface Python binds to stops being the surface we designed.
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
set(CMAKE_VISIBILITY_INLINES_HIDDEN ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Every core under core/ with a CMakeLists.txt, discovered rather than listed.
# `tools/build_core.py` finds them the same way, so the two cannot disagree
# about which architectures exist.
#
# CONFIGURE_DEPENDS so that adding a core re-runs cmake on the next build
# rather than being silently absent until someone deletes build/.
file(GLOB core_builds CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/core/*/CMakeLists.txt")
if(NOT core_builds)
  message(FATAL_ERROR "no cores found under core/ -- nothing to build")
endif()
foreach(core_build IN LISTS core_builds)
  get_filename_component(core_dir "${core_build}" DIRECTORY)
  add_subdirectory("${core_dir}")
endforeach()
