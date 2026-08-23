# Patches to PICSimLab

Changes this project needs in upstream's C++, kept as diffs rather than as a
copy of the files they change.

## Licence

**These patches are licensed under the GNU General Public License, version 2
or (at your option) any later version -- not MIT.** A diff against a GPL file is a
derivative of it, and the rest of this repository being MIT does not change
that. `LICENSE` covers the repository's own code; this directory is the stated
exception, and `tools/check_licenses.py` enforces the split rather than
trusting anyone to remember it.

That is not a problem to solve. It is the honest description of what a patch
to somebody else's GPL source is.

## Why patches and not a fork

This repository used to *be* a fork, carrying all of PICSimLab so that one
enum member could be added to one header. A patch file states the same change
in 24 lines, is reviewable at a glance, and cannot drift silently the way a
vendored tree does. See `docs/picsimlab-reference.md`.

## Applying them

    tools/apply_patches.sh                    # uses the resolved reference
    tools/apply_patches.sh /path/to/picsimlab # or an explicit checkout

The script refuses to apply a patch twice and refuses to apply to a dirty
tree, so a half-applied checkout is not a state you can reach by accident.

## The patches

### `0001-board-arch-x86.patch`

Adds `ARCH_X86` to the architecture enum in `src/lib/board.h`, for the x86-16
core (`i8086.int.arch-enum` in `docs/features/i8086.md`).

`MGetArchitecture()` is a pure virtual returning one of these values, so a new
architecture cannot be added without extending the enum. There is no registry
and no extension point: this is the one edit the i8086 work cannot avoid.

Inserted before `ARCH_UNKNOWN`, which renumbers that member. Checked before
making the change: `ARCH_*` values appear only as symbolic return values from
`MGetArchitecture()` implementations across `src/sim_backend/` and
`src/boards/board_Breadboard.cc`, and are never serialised. A `.pzw` workspace
is a zip storing board and processor **by name**, so no saved workspace
carries an architecture integer that renumbering could invalidate.

The enum is also reflowed one-member-per-line. That is cosmetic and enlarges
the diff by nine lines; it was done so future additions are one-line diffs
rather than edits to a 100-column single line.

**This patch should not be permanent.** One enum member is an obvious upstream
contribution. Offering it to `lcgamboa/picsimlab` would retire this file and
leave the project with no patches at all, which is the goal.
