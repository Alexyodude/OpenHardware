#!/bin/bash
# OpenHardware - arm-none-eabi GCC 12.3.1 and binutils 2.40 compiled to WebAssembly (OH-244).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Run inside tools/wasm_toolchain/Dockerfile by tools/build_compiler.py, which
# fetches and sha256-checks every source first. Mounts as build-avr.sh's:
#
#   /src    the pinned sources, read-only (tools/build_compiler.py's ARM_SOURCES)
#   /build  scratch; a docker volume, so a second run resumes at its stamps
#   /out    what is kept: one <tool>.mjs and <tool>.wasm per tool
#
# ## The sources are xPack's, and that is the point
#
# webui/compile.py builds a SAMD21 sketch with PlatformIO's
# toolchain-gccarmnoneeabi 1.120301.0, which is xPack's GNU Arm Embedded GCC
# 12.3.1 (its README; `arm-none-eabi-gcc -v`), not Arm's own binaries: Arm's
# release links different Cortex-M0+ libraries. xPack builds GCC and binutils
# from Arm's own per-component archives for 12.3.Rel1, which xPack's scripts
# name (scripts/versioning.sh at 2fcd97d). The configure arguments below are
# xPack's, as its gcc -v prints them. What differs is what a WebAssembly host
# has to differ in, each line saying why, and the languages: Fortran is not
# built.
#
# ## What is built, and what is not
#
# cc1, cc1plus and the two drivers, xgcc and xg++; as, ld and objcopy. NOT
# libgcc, newlib or libstdc++: tools/build_compiler.py takes those from xPack's
# own release, whose archives are the ones the server links.

set -euo pipefail

SRC=/src
B=/build
OUT=/out
JOBS="$(nproc)"
HOSTLIBS="$B/hostlibs"
PREFIX=/opt/arm
TARGET=arm-none-eabi

# As in build-avr.sh: Emscripten is the host, introduced as i686 because the
# config.sub files predate wasm32; the image's gcc is the build compiler.
HOST=i686-pc-linux-gnu
BUILD=x86_64-pc-linux-gnu

OLD_C="-O2 -g0 -w -Wno-error=implicit-function-declaration -Wno-error=implicit-int -Wno-error=incompatible-pointer-types -Wno-error=int-conversion"
# GCC 12 is C++11.
OLD_CXX="-O2 -g0 -w -std=gnu++11"

EMLINK="-O2 -sMODULARIZE=1 -sEXPORT_ES6=1 -sEXPORT_NAME=createTool \
 -sENVIRONMENT=web,worker,node -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=33554432 \
 -sMAXIMUM_MEMORY=2147483648 -sSTACK_SIZE=16777216 -sINVOKE_RUN=0 -sEXIT_RUNTIME=1 \
 -sFORCE_FILESYSTEM=1 -sEXPORTED_RUNTIME_METHODS=callMain,FS"

stamp() { [[ -f "$B/stamp-$1" ]]; }
done_() { touch "$B/stamp-$1"; }

mkdir -p "$B" "$OUT" "$HOSTLIBS"
cd "$B"

# --- GMP, MPFR, MPC ----------------------------------------------------------
if ! stamp hostlibs; then
  rm -rf gmp-6.2.1 mpfr-3.1.6 mpc-1.0.3
  tar xJf "$SRC/gmp-6.2.1.tar.xz"
  (cd gmp-6.2.1 && CFLAGS="$OLD_C" HOST_CC=gcc CC_FOR_BUILD=gcc emconfigure ./configure \
     --build="$BUILD" --host=none-unknown-linux-gnu --prefix="$HOSTLIBS" \
     --disable-shared --enable-static --disable-assembly \
   && emmake make -j"$JOBS" && emmake make install)
  tar xJf "$SRC/mpfr-3.1.6.tar.xz"
  (cd mpfr-3.1.6 && CFLAGS="$OLD_C" HOST_CC=gcc CC_FOR_BUILD=gcc emconfigure ./configure \
     --build="$BUILD" --host="$HOST" --prefix="$HOSTLIBS" --with-gmp="$HOSTLIBS" \
     --disable-shared --enable-static \
   && emmake make -j"$JOBS" && emmake make install)
  tar xzf "$SRC/mpc-1.0.3.tar.gz"
  (cd mpc-1.0.3 && CFLAGS="$OLD_C" HOST_CC=gcc CC_FOR_BUILD=gcc emconfigure ./configure \
     --build="$BUILD" --host="$HOST" --prefix="$HOSTLIBS" --with-gmp="$HOSTLIBS" \
     --with-mpfr="$HOSTLIBS" --disable-shared --enable-static \
   && emmake make -j"$JOBS" && emmake make install)
  done_ hostlibs
fi

# --- the sources --------------------------------------------------------------
# Arm's own archives for its 12.3.Rel1, as xPack's scripts/versioning.sh names
# them. xPack's one GCC patch is for a mingw host and changes nothing here;
# its binutils is a fork tag whose every file a build reads is Arm's.
if ! stamp sources; then
  rm -rf gcc binutils-gdb binutils
  tar xJf "$SRC/arm-12.3.rel1-gcc.tar.xz"
  tar xJf "$SRC/arm-12.3.rel1-binutils-gdb.tar.xz"
  mv binutils-gdb binutils
  # GCC's fix for PR 111632 (tools/build_compiler.py's ARM_SOURCES says why):
  # its 12 branch's system.h, put in place only over the 12.3 one it was
  # measured to differ from by that fix alone.
  echo "db86f0266b015140768c3bfaee14b67f82da7d46fdd52644aff192a8b533d329  gcc/gcc/system.h" \
    | sha256sum -c -
  cp "$SRC/gcc-12-a995fded34fe-system.h" gcc/gcc/system.h
  done_ sources
fi

# --- binutils, for this container: what GCC's configure asks ----------------
# build-avr.sh says why: the answers change what cc1plus emits.
NATIVE="$B/native"
if ! stamp binutils-native; then
  rm -rf binutils-native "$NATIVE" && mkdir binutils-native
  (cd binutils-native && CFLAGS="-O2 -g0 -w" ../binutils/configure \
     --target="$TARGET" --prefix="$NATIVE" --disable-nls --disable-doc --disable-werror \
     --disable-gdb --disable-gdbserver --disable-sim --disable-readline --disable-libdecnumber \
     --disable-gprofng \
   && make -j"$JOBS" configure-host MAKEINFO=true \
   && make -j"$JOBS" all-gas all-ld all-binutils MAKEINFO=true \
   && make install-gas install-ld install-binutils MAKEINFO=true)
  done_ binutils-native
fi

# --- GCC ---------------------------------------------------------------------
if ! stamp gcc-configure; then
  rm -rf gcc-build && mkdir gcc-build
  # xPack's arguments, but for fortran, mingw-wildcard and system zlib, which
  # are about its host; then this host's: the arithmetic libraries above, no
  # isl (graphite, which no flag in the recipe turns on), no plugins.
  (cd gcc-build && \
   PATH="$NATIVE/bin:$PATH" \
   CFLAGS="$OLD_C" CXXFLAGS="$OLD_CXX" \
   CC_FOR_BUILD=gcc CXX_FOR_BUILD=g++ \
   CFLAGS_FOR_BUILD="-O2 -g0 -w" CXXFLAGS_FOR_BUILD="-O2 -g0 -w" \
   emconfigure ../gcc/configure \
     --build="$BUILD" --host="$HOST" --target="$TARGET" --prefix="$PREFIX" \
     --with-sysroot="$PREFIX/$TARGET" --with-native-system-header-dir=/include \
     --disable-libgomp --disable-libmudflap --disable-libquadmath --disable-libsanitizer \
     --disable-libssp --disable-nls --disable-shared --disable-threads --disable-tls \
     --enable-checking=release --enable-languages=c,c++ \
     --with-newlib --with-gnu-as --with-gnu-ld --disable-libatomic \
     --enable-multilib --with-multilib-list=aprofile,rmprofile \
     --with-gmp="$HOSTLIBS" --with-mpfr="$HOSTLIBS" --with-mpc="$HOSTLIBS" \
     --without-isl --disable-plugin --without-zstd)
  done_ gcc-configure
fi

export ac_cv_func_psignal=yes

if ! stamp gcc-make; then
  (cd gcc-build && PATH="$NATIVE/bin:$PATH" emmake make configure-gcc)
  for feature in HAVE_GAS_SHF_MERGE HAVE_COMDAT_GROUP; do
    grep -q "^#define $feature 1" gcc-build/gcc/auto-host.h \
      || { echo "gcc/configure did not find $feature in $NATIVE/bin/$TARGET-as"; exit 1; }
  done
  (cd gcc-build && PATH="$NATIVE/bin:$PATH" emmake make -k -j"$JOBS" all-gcc) || true
  for tool in cc1 cc1plus xgcc xg++; do
    [[ -f "gcc-build/gcc/$tool.wasm" ]] || { echo "gcc-build/gcc/$tool.wasm was not built"; exit 1; }
  done
  done_ gcc-make
fi

if ! stamp gcc-link; then
  (cd gcc-build/gcc && rm -f cc1 cc1.wasm cc1plus cc1plus.wasm xgcc xgcc.wasm xg++ xg++.wasm \
   && emmake make cc1 cc1plus xgcc xg++ LDFLAGS="$EMLINK")
  done_ gcc-link
fi

# --- binutils, for WebAssembly -----------------------------------------------
if ! stamp binutils-configure; then
  rm -rf binutils-build && mkdir binutils-build
  (cd binutils-build && \
   CFLAGS="$OLD_C" CXXFLAGS="$OLD_CXX" CC_FOR_BUILD=gcc \
   emconfigure ../binutils/configure \
     --build="$BUILD" --host="$HOST" --target="$TARGET" --prefix="$PREFIX" \
     --with-sysroot="$PREFIX/$TARGET" \
     --disable-nls --disable-doc --disable-werror --disable-gdb --disable-gdbserver \
     --disable-sim --disable-readline --disable-libdecnumber --disable-gprofng \
     --disable-plugins --disable-shared)
  done_ binutils-configure
fi

if ! stamp binutils-make; then
  (cd binutils-build && emmake make -j"$JOBS" configure-host MAKEINFO=true \
   && emmake make -j"$JOBS" all-gas all-ld all-binutils MAKEINFO=true)
  done_ binutils-make
fi

if ! stamp binutils-link; then
  BINUTILS_LINK="$EMLINK -sEMULATE_FUNCTION_POINTER_CASTS=1"
  (cd binutils-build/gas && rm -f as-new as-new.wasm && emmake make as-new LDFLAGS="$BINUTILS_LINK" MAKEINFO=true)
  (cd binutils-build/ld && rm -f ld-new ld-new.wasm && emmake make ld-new LDFLAGS="$BINUTILS_LINK" MAKEINFO=true)
  (cd binutils-build/binutils && rm -f objcopy objcopy.wasm && emmake make objcopy LDFLAGS="$BINUTILS_LINK" MAKEINFO=true)
  done_ binutils-link
fi

keep() {  # <built js> <built wasm> <name>
  cp "$1" "$OUT/$3.mjs"
  cp "$2" "$OUT/$3.wasm"
}
keep gcc-build/gcc/cc1 gcc-build/gcc/cc1.wasm cc1
keep gcc-build/gcc/cc1plus gcc-build/gcc/cc1plus.wasm cc1plus
keep gcc-build/gcc/xgcc gcc-build/gcc/xgcc.wasm "$TARGET-gcc"
keep gcc-build/gcc/xg++ gcc-build/gcc/xg++.wasm "$TARGET-g++"
keep binutils-build/gas/as-new binutils-build/gas/as-new.wasm "$TARGET-as"
keep binutils-build/ld/ld-new binutils-build/ld/ld-new.wasm "$TARGET-ld"
keep binutils-build/binutils/objcopy binutils-build/binutils/objcopy.wasm "$TARGET-objcopy"

EMSCRIPTEN="$EMSDK/upstream/emscripten"
mkdir -p "$OUT/licenses"
cp "$EMSCRIPTEN/LICENSE" "$OUT/licenses/Emscripten-LICENSE.txt"
cp "$EMSCRIPTEN/system/lib/libc/musl/COPYRIGHT" "$OUT/licenses/musl-COPYRIGHT.txt"
cp "$EMSCRIPTEN/system/lib/libcxx/LICENSE.TXT" "$OUT/licenses/libcxx-LICENSE.txt"
cp "$EMSCRIPTEN/system/lib/libcxxabi/LICENSE.TXT" "$OUT/licenses/libcxxabi-LICENSE.txt"
cp "$EMSCRIPTEN/system/lib/compiler-rt/LICENSE.TXT" "$OUT/licenses/compiler-rt-LICENSE.txt"
ls -la "$OUT"
