# OpenHardware
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Only the native core is built here. Everything else in this repository is
# Python and needs no build step; PICSimLab is external and builds itself
# (docs/picsimlab-reference.md).

cmake_minimum_required(VERSION 3.20)
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

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

add_subdirectory(core/i8086)
