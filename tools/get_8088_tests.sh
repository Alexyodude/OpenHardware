#!/bin/bash
# OpenHardware — fetch the SingleStepTests/8088 conformance corpus.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Fetch, do not vendor. The corpus is ~2 GB -- putting it in this repository
# would dwarf the source several times over and make every clone pay for it.
# It is MIT licensed, so vendoring would be *permitted*; it is size, not
# licence, that decides here.
#
# The corpus is hardware ground truth: captured from a physical AMD D8088
# (8441DMA, 1982) in Maximum Mode via the Arduino8088 interface. It is the only
# non-software oracle this project has.
#
#   bash tools/get_8088_tests.sh                    # v2, the whole suite (~2 GB)
#   bash tools/get_8088_tests.sh v2_undefined       # undefined-opcode behaviour
#   bash tools/get_8088_tests.sh --opcodes 00 88 90 # just these, a few MB each
#
# `--opcodes` exists because the whole suite is ~2 GB and a run usually cares
# about the handful of opcodes being worked on. Each file is 10,000 cases, so
# even three of them is far stronger evidence than the eleven committed
# fixtures -- it was a targeted fetch that found the AF-on-logicals
# divergence, which the fixtures could not see.
#
# Downloads land in third_party/sst8088/<set>/ which is git-ignored.

set -euo pipefail

SET="v2"
REPO="https://github.com/SingleStepTests/8088.git"
RAW="https://raw.githubusercontent.com/SingleStepTests/8088/main"
DEST="third_party/sst8088"

# --- targeted fetch -------------------------------------------------------
if [ "${1:-}" = "--opcodes" ]; then
  shift
  if [ $# -eq 0 ]; then
    echo "--opcodes needs at least one opcode, e.g. --opcodes 00 88 90" >&2
    exit 2
  fi
  mkdir -p "$DEST/$SET"
  fetched=0
  for op in "$@"; do
    upper=$(printf '%s' "$op" | tr '[:lower:]' '[:upper:]')
    out="$DEST/$SET/${upper}.json.gz"
    if [ -s "$out" ]; then
      fetched=$((fetched + 1))
      continue
    fi
    if curl -sfL "$RAW/$SET/${upper}.json.gz" -o "$out"; then
      fetched=$((fetched + 1))
    else
      rm -f "$out"
      echo "no corpus file for opcode ${upper}" >&2
    fi
  done
  if [ "$fetched" -eq 0 ]; then
    echo "ERROR: fetched nothing. A conformance run over zero cases reports" >&2
    echo "zero failures, which is indistinguishable from a pass." >&2
    exit 1
  fi
  echo "$fetched opcode file(s) in $DEST/$SET"
  exit 0
fi

SET="${1:-v2}"

case "$SET" in
  v2|v2_undefined|v2_binary|v1) ;;
  *)
    echo "unknown set '$SET'. Known: v2, v2_undefined, v2_binary, v1" >&2
    exit 2
    ;;
esac

if ! command -v git >/dev/null 2>&1; then
  echo "git is required" >&2
  exit 2
fi

mkdir -p "$DEST"

# A sparse, blobless checkout: only the requested set's files are transferred,
# not all four sets. A full clone is several times larger than any one set.
if [ ! -d "$DEST/.git" ]; then
  echo "cloning $REPO (blobless, sparse) into $DEST"
  git clone --filter=blob:none --no-checkout --depth 1 "$REPO" "$DEST"
  git -C "$DEST" sparse-checkout init --cone
fi

echo "fetching set '$SET' -- this is large, expect a wait"
git -C "$DEST" sparse-checkout set "$SET"
git -C "$DEST" checkout

COUNT=$(find "$DEST/$SET" -name '*.json.gz' -o -name '*.json' | wc -l)
if [ "$COUNT" -eq 0 ]; then
  echo "ERROR: $DEST/$SET holds no corpus files after checkout." >&2
  echo "A silent empty fetch would make a conformance run report zero" >&2
  echo "failures over zero tests, so this is an error, not a warning." >&2
  exit 1
fi

echo
echo "$COUNT corpus files in $DEST/$SET"
echo "LICENCE: MIT, (c) Daniel Balsom -- see $DEST/LICENSE"
