#!/bin/sh
# OpenHardware - fetch the oracle and generate the Armv6-M corpus.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why this exists beside tools/get_8088_tests.sh
#
# The 8088 corpus is FETCHED: SingleStepTests publishes it, hardware-captured
# from a real AMD D8088, and that script downloads a slice. There is no
# equivalent to download here -- SingleStepTests has 22 repositories and not
# one is M-profile -- so this GENERATES instead, from rp2040js.
#
# Same contract either way, and it is the contract that matters:
#
#   * the corpus is never committed. `third_party/` is gitignored, so a clone
#     of this repository does not carry thirteen thousand JSON cases.
#   * one command produces it, so "regenerate the corpus" is not a paragraph
#     of instructions somebody has to follow correctly.
#   * a suite with no corpus SKIPS and says how to get one, rather than
#     passing on nothing.
#
# ## What you are trusting when you run this
#
# **rp2040js is a simulator, not silicon.** Its instructions were diffed
# against a real RP2040 once, via gdbdiff, and that caught real bugs in ADCS
# overflow, CMP carry and LSRS edges -- but it was a one-off rather than a
# continuously-checked claim. A case here means "agrees with rp2040js", which
# is weaker than the 8088 corpus's "agrees with an AMD D8088", and three of
# rp2040js's shift-carry answers are known wrong: see `oracle_carry_bug` in
# tests/cortexm0/test_conformance.py, which predicts each of them rather than
# tolerating them.
set -eu

HERE=$(cd "$(dirname "$0")/.." && pwd)
ORACLE=${RP2040JS_ROOT:-"$HERE/../rp2040js"}

# 500 per family, which is what tests/cortexm0/test_conformance.py's floor
# expects. Raising it is always safe; lowering it silently is what the floor
# exists to catch.
COUNT=${COUNT:-500}

if [ ! -d "$ORACLE" ]; then
    echo "get_armv6m_tests: no rp2040js at $ORACLE" >&2
    echo "  git clone https://github.com/wokwi/rp2040js \"$ORACLE\"" >&2
    exit 3
fi

if [ ! -d "$ORACLE/dist" ]; then
    echo "get_armv6m_tests: $ORACLE is not built" >&2
    echo "  (cd \"$ORACLE\" && npm install && npm run build)" >&2
    exit 3
fi

cd "$HERE"
node tools/gen_armv6m_tests.mjs --count "$COUNT"
