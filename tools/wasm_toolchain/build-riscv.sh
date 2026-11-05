#!/bin/bash
# OpenHardware - riscv32-esp-elf GCC 8.4.0 and binutils 2.35.1 compiled to WebAssembly (OH-244).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Run inside tools/wasm_toolchain/Dockerfile by tools/build_compiler.py, which
# fetches and sha256-checks every source first. Mounts as build-avr.sh's:
#
#   /src    the pinned sources, read-only (tools/build_compiler.py's RISCV_SOURCES)
#   /build  scratch; a docker volume, so a second run resumes at its stamps
#   /out    what is kept: one <tool>.mjs and <tool>.wasm per tool
#
# ## The sources are Espressif's, and that is the point
#
# webui/compile.py builds an ESP32-C3, C5 or C6 sketch with PlatformIO's
# toolchain-riscv32-esp 8.4.0+2021r2-patch5, which is Espressif's own
# crosstool-NG build esp-2021r2-patch5 (`riscv32-esp-elf-gcc -v`). That build
# takes GCC and binutils from Espressif's forks at esp-2021r2-patch4 and
# esp-2021r2-patch4-binutils, where its ct-ng.config points them, and
# RISCV_SOURCES pins those commits. The GCC configure arguments below are the
# ones its gcc -v prints. What differs is what a WebAssembly host has to
# differ in, each line saying why.
#
# ## What is built, and what is not
#
# cc1, cc1plus and the two drivers, xgcc and xg++; as, ld and objcopy. Of
# all-gcc, gcov does not build: it includes <vector> after safe-ctype.h, the
# libc++ trouble build-arm.sh describes, and nothing here runs it. NOT
# libgcc, newlib or libstdc++: the ESP32 rows link bare (-nostdlib), and the
# one archive the link opens, libm.a, and the headers come from Espressif's
# own release, as tools/build_compiler.py's RISCV_RELEASE says.

set -euo pipefail

SRC=/src
B=/build
OUT=/out
JOBS="$(nproc)"
HOSTLIBS="$B/hostlibs"
PREFIX=/opt/riscv
TARGET=riscv32-esp-elf

# As in build-avr.sh: Emscripten is the host, introduced as i686 because the
# config.sub files predate wasm32; the image's gcc is the build compiler.
HOST=i686-pc-linux-gnu
BUILD=x86_64-pc-linux-gnu

OLD_C="-O2 -g0 -w -Wno-error=implicit-function-declaration -Wno-error=implicit-int -Wno-error=incompatible-pointer-types -Wno-error=int-conversion"
# C++11, as for GCC 12: GCC 8 itself is C++98, but Espressif's fork carries
# the top-level configure that refuses a host compiler without C++11
# (configure.ac's AX_CXX_COMPILE_STDCXX(11)), and -std=gnu++98 here would
# override the -std=gnu++11 that check adds.
OLD_CXX="-O2 -g0 -w -std=gnu++11"

EMLINK="-O2 -sMODULARIZE=1 -sEXPORT_ES6=1 -sEXPORT_NAME=createTool \
 -sENVIRONMENT=web,worker,node -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=33554432 \
 -sMAXIMUM_MEMORY=2147483648 -sSTACK_SIZE=16777216 -sINVOKE_RUN=0 -sEXIT_RUNTIME=1 \
 -sFORCE_FILESYSTEM=1 -sEXPORTED_RUNTIME_METHODS=callMain,FS"

stamp() { [[ -f "$B/stamp-$1" ]]; }
done_() { touch "$B/stamp-$1"; }

mkdir -p "$B" "$OUT" "$HOSTLIBS"
cd "$B"

# --- GMP, MPFR, MPC: the versions its cc1 -v names ---------------------------
if ! stamp hostlibs; then
  rm -rf gmp-6.2.1 mpfr-4.1.0 mpc-1.2.1
  tar xJf "$SRC/gmp-6.2.1.tar.xz"
  (cd gmp-6.2.1 && CFLAGS="$OLD_C" HOST_CC=gcc CC_FOR_BUILD=gcc emconfigure ./configure \
     --build="$BUILD" --host=none-unknown-linux-gnu --prefix="$HOSTLIBS" \
     --disable-shared --enable-static --disable-assembly \
   && emmake make -j"$JOBS" && emmake make install)
  tar xJf "$SRC/mpfr-4.1.0.tar.xz"
  (cd mpfr-4.1.0 && CFLAGS="$OLD_C" HOST_CC=gcc CC_FOR_BUILD=gcc emconfigure ./configure \
     --build="$BUILD" --host="$HOST" --prefix="$HOSTLIBS" --with-gmp="$HOSTLIBS" \
     --disable-shared --enable-static \
   && emmake make -j"$JOBS" && emmake make install)
  tar xzf "$SRC/mpc-1.2.1.tar.gz"
  (cd mpc-1.2.1 && CFLAGS="$OLD_C" HOST_CC=gcc CC_FOR_BUILD=gcc emconfigure ./configure \
     --build="$BUILD" --host="$HOST" --prefix="$HOSTLIBS" --with-gmp="$HOSTLIBS" \
     --with-mpfr="$HOSTLIBS" --disable-shared --enable-static \
   && emmake make -j"$JOBS" && emmake make install)
  done_ hostlibs
fi

# --- the sources --------------------------------------------------------------
if ! stamp sources; then
  rm -rf gcc binutils
  mkdir gcc binutils
  tar xzf "$SRC/espressif-gcc-3b3d328ad0df.tar.gz" -C gcc --strip-components=1
  tar xzf "$SRC/espressif-binutils-gdb-df444b49d425.tar.gz" -C binutils --strip-components=1
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
   && make -j"$JOBS" configure-host MAKEINFO=true \
   && make -j"$JOBS" all-gas all-ld all-binutils MAKEINFO=true \
   && make install-gas install-ld install-binutils MAKEINFO=true)
  done_ binutils-native
fi

# --- GCC ---------------------------------------------------------------------
if ! stamp gcc-configure; then
  rm -rf gcc-build && mkdir gcc-build
  # Espressif's arguments, as its gcc -v prints them, but for the paths of its
  # build machine and the host's: the arithmetic libraries above, no isl
  # (graphite, which no flag in the recipe turns on), no plugins. Its
  # --enable-threads appears twice, =no then =posix; the last is what
  # configure takes, and what `gcc -v`'s "Thread model: posix" says it took.
  (cd gcc-build && \
   PATH="$NATIVE/bin:$PATH" \
   CFLAGS="$OLD_C" CXXFLAGS="$OLD_CXX" \
   CC_FOR_BUILD=gcc CXX_FOR_BUILD=g++ \
   CFLAGS_FOR_BUILD="-O2 -g0 -w" CXXFLAGS_FOR_BUILD="-O2 -g0 -w -std=gnu++11" \
   emconfigure ../gcc/configure \
     --build="$BUILD" --host="$HOST" --target="$TARGET" --prefix="$PREFIX" \
     --with-newlib --disable-shared --with-arch=rv32gc --with-abi=ilp32 \
     --with-pkgversion='crosstool-NG esp-2021r2-patch5' --disable-__cxa_atexit \
     --enable-cxx-flags=-ffunction-sections --disable-libgomp --disable-libmudflap \
     --disable-libmpx --disable-libssp --disable-libquadmath --disable-libquadmath-support \
     --disable-libstdcxx-verbose --enable-lto --enable-target-optspace \
     --without-long-double-128 --disable-nls --enable-multiarch --enable-languages=c,c++ \
     --enable-threads=posix --enable-gcov-custom-rtio --enable-libstdcxx-time=yes \
     --with-gnu-ld \
     --with-gmp="$HOSTLIBS" --with-mpfr="$HOSTLIBS" --with-mpc="$HOSTLIBS" \
     --without-isl --disable-plugin)
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
  # crosstool-NG's arguments for it (scripts/build/binutils/binutils.sh at
  # esp-2021r2-patch5, with that release's ct-ng.config), then this host's.
  (cd binutils-build && \
   CFLAGS="$OLD_C" CXXFLAGS="$OLD_CXX" CC_FOR_BUILD=gcc \
   emconfigure ../binutils/configure \
     --build="$BUILD" --host="$HOST" --target="$TARGET" --prefix="$PREFIX" \
     --with-pkgversion='crosstool-NG esp-2021r2-patch5' --disable-werror \
     --enable-ld=yes --enable-gold=no --disable-relro --enable-deterministic-archives \
     --enable-multilib --disable-sim --disable-gdb --disable-nls \
     --disable-doc --disable-gdbserver --disable-readline --disable-libdecnumber \
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
