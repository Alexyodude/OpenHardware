#!/bin/bash
# OpenHardware - avr-gcc 7.3.0 and binutils 2.26 compiled to WebAssembly (OH-244).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Run inside tools/wasm_toolchain/Dockerfile by tools/build_compiler.py, which
# fetches and sha256-checks every source first. Mounts:
#
#   /src    the pinned sources, read-only (tools/build_compiler.py's AVR_SOURCES)
#   /build  scratch; a docker volume, so a second run resumes at its stamps
#   /out    what is kept: one <tool>.mjs and <tool>.wasm per tool
#
# ## The sources are Arduino's, and that is the point
#
# webui/compile.py runs PlatformIO's toolchain-atmelavr 3.70300.220127, whose
# cc1plus, as, ld and objcopy are byte-identical to Arduino's
# 7.3.0-atmel3.6.1-arduino7 release. That release is built by
# github.com/arduino/toolchain-avr at that tag: GNU gcc-7.3.0 with
# atmel-patches-gcc.7.3.0-arduino2.patch, and Atmel's 3.6.1 binutils snapshot
# with 00-binutils-data_region_length.patch, against GMP 5.0.2, MPFR 3.1.0 and
# MPC 0.9 (what its cc1plus -v names). The configure arguments below are its
# gcc.build.bash's and binutils.build.bash's. What differs is only what a
# WebAssembly host has to differ in, each line saying why.
#
# ## What is built, and what is not
#
# The compilers proper and the two drivers -- cc1, cc1plus, xgcc and xg++ (the
# C++ driver, avr-g++, which links as compile.py's does) -- and as, ld and
# objcopy. NOT libgcc or avr-libc: tools/build_compiler.py takes those from
# Arduino's own release, whose objects are the ones the server links (the
# libgcc members differ from PlatformIO's in debug relocations only). A
# target library built here would be a second copy of the same source to
# keep right.

set -euo pipefail

SRC=/src
B=/build
OUT=/out
JOBS="$(nproc)"
HOSTLIBS="$B/hostlibs"
# The prefix the tools are configured with, and where the page lays out their
# files in each tool's in-memory filesystem: cc1plus finds its own headers
# under it with no -iprefix needed.
PREFIX=/opt/avr

# Emscripten is the HOST compiler; i686-pc-linux-gnu is the triple it is
# introduced as, because none of these 2016-2018 config.sub files knows
# wasm32. Both are ILP32 with a 64-bit long long, which is what GCC's
# HOST_WIDE_INT asks of a host. The BUILD compiler is the image's own gcc,
# for GCC's generator programs, which run here and not in a browser.
HOST=i686-pc-linux-gnu
BUILD=x86_64-pc-linux-gnu

# -w and the implicit-* demotions: clang 21 makes errors of what these sources
# were written to be warnings (implicit declarations in configure tests among
# them, which would otherwise misdetect features rather than fail).
OLD_C="-O2 -g0 -w -Wno-error=implicit-function-declaration -Wno-error=implicit-int -Wno-error=incompatible-pointer-types -Wno-error=int-conversion"
# GCC 7 is C++98; clang's default C++17 refuses its `register` variables.
OLD_CXX="-O2 -g0 -w -std=gnu++98"

# How each tool is linked: an ES module exporting a factory, a fresh instance
# per invocation (exit() ends an instance -- GCC's static state is not
# re-entrant), argv through callMain, files through FS.
#
# 16 MB of stack, because GCC recurses: Emscripten's default of 64 KB is a
# segfault in the first non-trivial C++ parse.
EMLINK="-O2 -sMODULARIZE=1 -sEXPORT_ES6=1 -sEXPORT_NAME=createTool \
 -sENVIRONMENT=web,worker,node -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=33554432 \
 -sMAXIMUM_MEMORY=2147483648 -sSTACK_SIZE=16777216 -sINVOKE_RUN=0 -sEXIT_RUNTIME=1 \
 -sFORCE_FILESYSTEM=1 -sEXPORTED_RUNTIME_METHODS=callMain,FS"

stamp() { [[ -f "$B/stamp-$1" ]]; }
done_() { touch "$B/stamp-$1"; }

mkdir -p "$B" "$OUT" "$HOSTLIBS"
cd "$B"

# --- GMP, MPFR, MPC: the arithmetic GCC folds constants with ---------------
#
# Built for the host and installed into $HOSTLIBS. GMP's CPU is `none`: its
# generic C, since there is no WebAssembly assembly for it. -std=gnu89 because
# GMP 5.0.2's gmp.h predates C99 inline semantics. HOST_CC and CC_FOR_BUILD
# are the image's gcc: emconfigure points them at its own clang, which builds
# for WebAssembly too, and GMP's generator programs have to run here.
if ! stamp hostlibs; then
  rm -rf gmp-5.0.2 mpfr-3.1.0 mpc-0.9
  tar xjf "$SRC/gmp-5.0.2.tar.bz2"
  (cd gmp-5.0.2 && CFLAGS="$OLD_C -std=gnu89" HOST_CC=gcc CC_FOR_BUILD=gcc emconfigure ./configure \
     --build="$BUILD" --host=none-unknown-linux-gnu --prefix="$HOSTLIBS" \
     --disable-shared --enable-static \
   && emmake make -j"$JOBS" && emmake make install)
  tar xjf "$SRC/mpfr-3.1.0.tar.bz2"
  (cd mpfr-3.1.0 && CFLAGS="$OLD_C -std=gnu89" HOST_CC=gcc CC_FOR_BUILD=gcc emconfigure ./configure \
     --build="$BUILD" --host="$HOST" --prefix="$HOSTLIBS" --with-gmp="$HOSTLIBS" \
     --disable-shared --enable-static \
   && emmake make -j"$JOBS" && emmake make install)
  tar xzf "$SRC/mpc-0.9.tar.gz"
  (cd mpc-0.9 && CFLAGS="$OLD_C -std=gnu89" HOST_CC=gcc CC_FOR_BUILD=gcc emconfigure ./configure \
     --build="$BUILD" --host="$HOST" --prefix="$HOSTLIBS" --with-gmp="$HOSTLIBS" \
     --with-mpfr="$HOSTLIBS" --disable-shared --enable-static \
   && emmake make -j"$JOBS" && emmake make install)
  done_ hostlibs
fi

# --- binutils, for this container: what GCC's configure asks ----------------
#
# GCC's configure runs the target assembler and linker to learn what they
# support, and the answers change what cc1plus EMITS. With no avr-as to ask it
# assumed no COMDAT groups and no mergeable strings, and cc1plus put inline
# member functions in .gnu.linkonce sections and every string literal in plain
# .rodata (measured: Print.cpp, Stream.cpp, WString.cpp and Wire.cpp
# disassembled differently from the server's objects, and the Serial and
# OH-135 idiom images differed from its images). Arduino's scripts install
# binutils into the prefix before configuring GCC, which is how theirs asked.
# So the same binutils is built here first, for this container, and is on
# PATH while GCC configures. It is never shipped.
NATIVE="$B/native"
if ! stamp binutils-src; then
  rm -rf binutils
  tar xjf "$SRC/avr-binutils.tar.bz2"
  (cd binutils && patch -p1 < "$SRC/00-binutils-data_region_length.patch")
  done_ binutils-src
fi

if ! stamp binutils-native; then
  rm -rf binutils-native "$NATIVE" && mkdir binutils-native
  (cd binutils-native && CFLAGS="-O2 -g0 -w" ../binutils/configure \
     --target=avr --prefix="$NATIVE" --disable-nls --disable-doc --disable-werror \
     --disable-libdecnumber --disable-gdb --disable-readline --disable-sim \
   && make -j"$JOBS" configure-host MAKEINFO=true \
   && make -j"$JOBS" all-gas all-ld all-binutils MAKEINFO=true \
   && make install-gas install-ld install-binutils MAKEINFO=true)
  done_ binutils-native
fi

# --- GCC ---------------------------------------------------------------------
if ! stamp gcc-src; then
  rm -rf gcc
  tar xJf "$SRC/gcc-7.3.0.tar.xz"
  mv gcc-7.3.0 gcc
  (cd gcc && patch -p1 < "$SRC/atmel-patches-gcc.7.3.0-arduino2.patch")
  done_ gcc-src
fi

if ! stamp gcc-configure; then
  rm -rf gcc-build && mkdir gcc-build
  # Arduino's CONFARGS, then the host's three: the arithmetic libraries
  # above, and no plugin support (a plugin is a dlopen, which a tab has not
  # got). Neither changes what cc1plus emits for a translation unit.
  (cd gcc-build && \
   PATH="$NATIVE/bin:$PATH" \
   CFLAGS="$OLD_C" CXXFLAGS="$OLD_CXX" \
   CC_FOR_BUILD=gcc CXX_FOR_BUILD=g++ \
   CFLAGS_FOR_BUILD="-O2 -g0 -w" CXXFLAGS_FOR_BUILD="-O2 -g0 -w -std=gnu++98" \
   emconfigure ../gcc/configure \
     --build="$BUILD" --host="$HOST" --target=avr \
     --enable-fixed-point --enable-languages=c,c++ --prefix="$PREFIX" \
     --disable-nls --disable-libssp --disable-libada --disable-shared \
     --with-avrlibc=yes --with-dwarf2 --disable-doc \
     --with-gmp="$HOSTLIBS" --with-mpfr="$HOSTLIBS" --with-mpc="$HOSTLIBS" \
     --disable-plugin --without-isl)
  done_ gcc-configure
fi

# Emscripten's signal.h declares psignal() and its libc has no definition,
# so libiberty's link test says "missing" and its own definition then
# conflicts with that declaration. Nothing in GCC calls it.
export ac_cv_func_psignal=yes

if ! stamp gcc-make; then
  # all-gcc builds the generator programs with the build compiler and the
  # compilers with emcc. Its last steps run ./xgcc (the specs file, the
  # fixed headers), which is now a WebAssembly module and not a program this
  # container can exec; -k carries on past them (and past gcov-tool, which
  # wants ftw() and is not wanted), and the binaries that ARE wanted are
  # checked for by name below rather than trusted to exit 0.
  #
  # gcc/ is configured here, by make, and not by the configure above: that is
  # where the target assembler is asked, so the PATH holds for make as well.
  # The two answers measured to change the objects are then checked: a
  # configure that could not ask builds a compiler whose images differ from
  # the server's.
  (cd gcc-build && PATH="$NATIVE/bin:$PATH" emmake make configure-gcc)
  for feature in HAVE_GAS_SHF_MERGE HAVE_COMDAT_GROUP; do
    grep -q "^#define $feature 1" gcc-build/gcc/auto-host.h \
      || { echo "gcc/configure did not find $feature in $NATIVE/bin/avr-as"; exit 1; }
  done
  (cd gcc-build && PATH="$NATIVE/bin:$PATH" emmake make -k -j"$JOBS" all-gcc) || true
  for tool in cc1 cc1plus xgcc xg++; do
    [[ -f "gcc-build/gcc/$tool.wasm" ]] || { echo "gcc-build/gcc/$tool.wasm was not built"; exit 1; }
  done
  done_ gcc-make
fi

if ! stamp gcc-link; then
  # Relinked with $EMLINK, which configure must not see: its link tests make
  # a.out-style programs and an ES module factory is not one.
  (cd gcc-build/gcc && rm -f cc1 cc1.wasm cc1plus cc1plus.wasm xgcc xgcc.wasm xg++ xg++.wasm \
   && emmake make cc1 cc1plus xgcc xg++ LDFLAGS="$EMLINK")
  done_ gcc-link
fi

# --- binutils, for WebAssembly -----------------------------------------------
if ! stamp binutils-configure; then
  rm -rf binutils-build && mkdir binutils-build
  # Arduino's CONFARGS, plus --disable-plugins (dlopen again).
  (cd binutils-build && \
   CFLAGS="$OLD_C" CXXFLAGS="$OLD_CXX" CC_FOR_BUILD=gcc \
   emconfigure ../binutils/configure \
     --build="$BUILD" --host="$HOST" --target=avr --prefix="$PREFIX" \
     --enable-languages=c,c++ --disable-nls --disable-doc --disable-werror \
     --disable-libdecnumber --disable-gdb --disable-readline --disable-sim \
     --disable-plugins --disable-shared)
  done_ binutils-configure
fi

if ! stamp binutils-make; then
  (cd binutils-build && emmake make -j"$JOBS" configure-host MAKEINFO=true \
   && emmake make -j"$JOBS" all-gas all-ld all-binutils MAKEINFO=true)
  done_ binutils-make
fi

if ! stamp binutils-link; then
  # Binutils calls through function pointers whose types do not match their
  # targets' (gas's pseudo-op table: handlers of (void) called with an int).
  # A native ABI shrugs; WebAssembly's call_indirect traps, measured on the
  # first .s gas read. Emscripten's cast emulation is the fix that touches no
  # source.
  BINUTILS_LINK="$EMLINK -sEMULATE_FUNCTION_POINTER_CASTS=1"
  (cd binutils-build/gas && rm -f as-new as-new.wasm && emmake make as-new LDFLAGS="$BINUTILS_LINK" MAKEINFO=true)
  (cd binutils-build/ld && rm -f ld-new ld-new.wasm && emmake make ld-new LDFLAGS="$BINUTILS_LINK" MAKEINFO=true)
  (cd binutils-build/binutils && rm -f objcopy objcopy.wasm && emmake make objcopy LDFLAGS="$BINUTILS_LINK" MAKEINFO=true)
  done_ binutils-link
fi

# --- what is kept ------------------------------------------------------------
#
# Each JS glue file is renamed .mjs (it is an ES module) and told its wasm by
# the page rather than finding it beside itself, so the names below are the
# only ones that matter.
keep() {  # <built js> <built wasm> <name>
  cp "$1" "$OUT/$3.mjs"
  cp "$2" "$OUT/$3.wasm"
}
keep gcc-build/gcc/cc1 gcc-build/gcc/cc1.wasm cc1
keep gcc-build/gcc/cc1plus gcc-build/gcc/cc1plus.wasm cc1plus
keep gcc-build/gcc/xgcc gcc-build/gcc/xgcc.wasm avr-gcc
keep gcc-build/gcc/xg++ gcc-build/gcc/xg++.wasm avr-g++
keep binutils-build/gas/as-new binutils-build/gas/as-new.wasm avr-as
keep binutils-build/ld/ld-new binutils-build/ld/ld-new.wasm avr-ld
keep binutils-build/binutils/objcopy binutils-build/binutils/objcopy.wasm avr-objcopy

# The licence texts of what Emscripten linked into every tool above -- its
# runtime, which is the .mjs glue, musl, and LLVM's C++ runtime and builtins --
# from the tree that linked them. No tool is linked with exceptions, so
# libunwind is not among them. tools/build_compiler.py's EMSCRIPTEN_LICENCES
# names these files and puts them in the bundle's licenses/.
EMSCRIPTEN="$EMSDK/upstream/emscripten"
mkdir -p "$OUT/licenses"
cp "$EMSCRIPTEN/LICENSE" "$OUT/licenses/Emscripten-LICENSE.txt"
cp "$EMSCRIPTEN/system/lib/libc/musl/COPYRIGHT" "$OUT/licenses/musl-COPYRIGHT.txt"
cp "$EMSCRIPTEN/system/lib/libcxx/LICENSE.TXT" "$OUT/licenses/libcxx-LICENSE.txt"
cp "$EMSCRIPTEN/system/lib/libcxxabi/LICENSE.TXT" "$OUT/licenses/libcxxabi-LICENSE.txt"
cp "$EMSCRIPTEN/system/lib/compiler-rt/LICENSE.TXT" "$OUT/licenses/compiler-rt-LICENSE.txt"
ls -la "$OUT"
