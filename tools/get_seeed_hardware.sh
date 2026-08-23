#!/bin/bash
# OpenHardware - fetch Seeed Studio's open-source XIAO hardware files.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Fetch, do not vendor. The repository is ~196 MB -- larger than the PICSimLab
# fork this project was extracted from -- and almost all of that is `pinout/`,
# which holds two 2-5 MB marketing PNGs per board. Those are pictures of a
# pinout, not a pinout.
#
# It is MIT licensed (Seeed-Studio/OSHW-XIAO-Series), so vendoring would be
# **permitted**; as with the 8088 corpus, it is size that decides, not licence.
#
# What is actually useful is small and machine-readable:
#
#   Seeed Studio XIAO Series Library/*.kicad_mod   exact pad coordinates, mm
#   Seeed Studio XIAO Series Library/*.kicad_sym   pin names and numbers
#   document/**.md                                 board notes
#
# Joining a footprint to its symbol yields everything `webui/boards/<name>.json`
# needs, measured rather than eyeballed. `webui/pinmap.py` records that the
# Arduino Uno's pad centres had to be extracted from `board.svg` by hand; for
# these boards the vendor publishes the real geometry.
#
#   bash tools/get_seeed_hardware.sh          # library + docs (~2 MB)
#   bash tools/get_seeed_hardware.sh --all    # everything, including pinout PNGs
#
# Downloads land in third_party/seeed-xiao/, which is git-ignored.

set -euo pipefail

REPO="https://github.com/Seeed-Studio/OSHW-XIAO-Series.git"
DEST="third_party/seeed-xiao"
LIBRARY="Seeed Studio XIAO Series Library"

WANT_ALL=0
if [ "${1:-}" = "--all" ]; then
  WANT_ALL=1
elif [ $# -gt 0 ]; then
  echo "unknown argument '$1'. Use --all, or no argument." >&2
  exit 2
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required" >&2
  exit 2
fi

mkdir -p "$DEST"

# Blobless and sparse: without this the pinout PNGs alone are ~180 MB, and
# nothing here reads them.
if [ ! -d "$DEST/.git" ]; then
  echo "cloning $REPO (blobless, sparse) into $DEST"
  git clone --filter=blob:none --no-checkout --depth 1 "$REPO" "$DEST"
  git -C "$DEST" sparse-checkout init --cone
fi

if [ "$WANT_ALL" -eq 1 ]; then
  echo "fetching everything -- this pulls ~196 MB of pinout images, expect a wait"
  git -C "$DEST" sparse-checkout disable
else
  echo "fetching the KiCad library and documents"
  git -C "$DEST" sparse-checkout set "$LIBRARY" "document"
fi
git -C "$DEST" checkout

# A silent empty fetch would make the board importer report zero boards over
# zero footprints, which reads exactly like success.
MODS=$(find "$DEST" -name '*.kicad_mod' | wc -l)
SYMS=$(find "$DEST" -name '*.kicad_sym' | wc -l)
if [ "$MODS" -eq 0 ] || [ "$SYMS" -eq 0 ]; then
  echo "ERROR: $DEST holds $MODS footprint(s) and $SYMS symbol librar(y/ies)." >&2
  echo "The importer needs both. Refusing to report success over an empty tree." >&2
  exit 1
fi

echo
echo "$MODS footprints, $SYMS symbol library, $(du -sh "$DEST" | cut -f1) on disk"
echo "Licence: MIT, (c) Seeed Studio. See $DEST/LICENSE."
echo "Next: python tools/import_kicad_board.py --list"
