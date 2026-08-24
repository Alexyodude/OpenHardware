// OpenHardware — build Hazard3's rvcpp with MSVC.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// rvcpp is written for g++ and this machine has no g++ — only MSVC, which is
// also what tools/build_core.py drives. Three incompatibilities, all of them
// in the vendor source and none worth patching there: a patched vendor tree
// is a tree nobody can re-fetch.
//
// Force-included with /FI, so the vendor checkout stays exactly as cloned.
#pragma once

#include <intrin.h>

// main.cpp declares `void exit_help(std::string errtext = "")` and never
// includes <string>. libstdc++ drags it in transitively; MSVC does not.
#include <string>

// rv_mem.h marks unused virtual parameters with __attribute__((unused)),
// which MSVC does not accept in any form. Nothing here depends on the
// attribute having an effect -- it only silences a warning under -Wextra.
#define __attribute__(x)

// The four GCC builtins rvcpp uses, in rv_core.cpp (clz/popcount/ctz/bswap32,
// for Zbb's CLZ, CPOP, CTZ and REV8) and rv_csr.cpp (ctz, three times).
//
// Zero is undefined for clz and ctz under GCC too, and every call site here
// either guards it or passes a non-zero constant, so these match the builtins
// they replace over the whole domain that is actually reached.
static inline int __builtin_clz(unsigned int x) {
    unsigned long index;
    _BitScanReverse(&index, x);
    return 31 - (int)index;
}

static inline int __builtin_ctz(unsigned int x) {
    unsigned long index;
    _BitScanForward(&index, x);
    return (int)index;
}

static inline int __builtin_popcount(unsigned int x) {
    return (int)__popcnt(x);
}

static inline unsigned int __builtin_bswap32(unsigned int x) {
    return _byteswap_ulong(x);
}
