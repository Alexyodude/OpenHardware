# OpenHardware - the i8086 core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

add_library(i8086 SHARED
  cpu.cc
  abi.cc
)

target_include_directories(i8086 PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

# One predictable filename per platform, in one predictable directory.
# tests/i8086/conftest.py locates the library by globbing for it, and a
# per-configuration subdirectory (which MSVC adds by default) is the usual
# reason that glob comes back empty on Windows and not on Linux.
set_target_properties(i8086 PROPERTIES
  OUTPUT_NAME i8086
  LIBRARY_OUTPUT_DIRECTORY        ${CMAKE_BINARY_DIR}/lib
  RUNTIME_OUTPUT_DIRECTORY        ${CMAKE_BINARY_DIR}/lib
  ARCHIVE_OUTPUT_DIRECTORY        ${CMAKE_BINARY_DIR}/lib
)
foreach(config IN ITEMS DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
  set_target_properties(i8086 PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY_${config} ${CMAKE_BINARY_DIR}/lib
    RUNTIME_OUTPUT_DIRECTORY_${config} ${CMAKE_BINARY_DIR}/lib
    ARCHIVE_OUTPUT_DIRECTORY_${config} ${CMAKE_BINARY_DIR}/lib
  )
endforeach()

if(MSVC)
  target_compile_options(i8086 PRIVATE /W4 /permissive-)
else()
  target_compile_options(i8086 PRIVATE -Wall -Wextra -Wpedantic)
endif()
