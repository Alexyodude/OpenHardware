# OpenHardware - the RV32 core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

add_library(riscv32 SHARED
  cpu.cc
  exec.cc
  abi.cc
)

target_include_directories(riscv32 PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

# One predictable filename per platform, in one predictable directory.
# tools/build_core.py locates the library by that name, and a
# per-configuration subdirectory (which MSVC adds by default) is the usual
# reason the lookup comes back empty on Windows and not on Linux.
set_target_properties(riscv32 PROPERTIES
  OUTPUT_NAME riscv32
  LIBRARY_OUTPUT_DIRECTORY        ${CMAKE_BINARY_DIR}/lib
  RUNTIME_OUTPUT_DIRECTORY        ${CMAKE_BINARY_DIR}/lib
  ARCHIVE_OUTPUT_DIRECTORY        ${CMAKE_BINARY_DIR}/lib
)
foreach(config IN ITEMS DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
  set_target_properties(riscv32 PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY_${config} ${CMAKE_BINARY_DIR}/lib
    RUNTIME_OUTPUT_DIRECTORY_${config} ${CMAKE_BINARY_DIR}/lib
    ARCHIVE_OUTPUT_DIRECTORY_${config} ${CMAKE_BINARY_DIR}/lib
  )
endforeach()

if(MSVC)
  target_compile_options(riscv32 PRIVATE /W4 /permissive-)
else()
  target_compile_options(riscv32 PRIVATE -Wall -Wextra -Wpedantic)
endif()
