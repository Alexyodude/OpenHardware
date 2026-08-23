#!/bin/bash
# OpenHardware - apply this project's patches to a PICSimLab checkout.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# The patches themselves are GPL-2-or-later; see patches/README.md. This
# script is not.
#
#   tools/apply_patches.sh                     # resolved reference checkout
#   tools/apply_patches.sh /path/to/picsimlab  # explicit
#
# Refuses a dirty tree and refuses to apply twice, because a half-patched
# checkout that still builds is worse than one that never got touched.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_DIR="$HERE/patches"

if [ $# -ge 1 ]; then
  TARGET="$1"
else
  TARGET="$(python -c 'from webui import picsimlab; print(picsimlab.source_root())' 2>/dev/null)" || {
    echo "error: no PICSimLab source checkout found." >&2
    echo "       Set \$PICSIMLAB_ROOT, pass a path, or see docs/picsimlab-reference.md." >&2
    exit 1
  }
fi

if [ ! -f "$TARGET/src/lib/board.h" ]; then
  echo "error: $TARGET is not a PICSimLab source checkout (no src/lib/board.h)." >&2
  exit 1
fi

cd "$TARGET"

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  echo "error: $TARGET has uncommitted changes." >&2
  echo "       Commit, stash, or reset them first -- applying onto a dirty tree" >&2
  echo "       makes it impossible to tell our changes from yours." >&2
  exit 1
fi

shopt -s nullglob
patches=("$PATCH_DIR"/*.patch)
if [ ${#patches[@]} -eq 0 ]; then
  echo "no patches in $PATCH_DIR -- nothing to do."
  exit 0
fi

for patch in "${patches[@]}"; do
  name="$(basename "$patch")"
  if git apply --reverse --check "$patch" 2>/dev/null; then
    echo "already applied: $name"
    continue
  fi
  if ! git apply --check "$patch" 2>/dev/null; then
    echo "error: $name does not apply cleanly to $TARGET" >&2
    echo "       Upstream has probably moved. Re-cut the patch against this" >&2
    echo "       revision and update patches/README.md with what changed." >&2
    exit 1
  fi
  git apply "$patch"
  echo "applied: $name"
done

echo
echo "PICSimLab at $TARGET is patched. Rebuild it for the changes to take effect."
