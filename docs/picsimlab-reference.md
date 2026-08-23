# The PICSimLab reference

OpenHardware drives [PICSimLab](https://github.com/lcgamboa/picsimlab). It
does not contain it. This is how to get a copy and how the code finds it.

## The layout

```
Code/Github/
├── OpenHardware/            <- this repository
│   ├── webui/  tools/  tests/  docs/
│   └── patches/             <- our changes to upstream, as diffs
└── picsimlab-reference/     <- a plain clone of lcgamboa/picsimlab
```

The reference is a **sibling**, not a submodule and not a subdirectory. Three
reasons:

1. A submodule pins a revision, and a pinned revision is a dependency to be
   upgraded on a schedule — most of the cost of being a fork with none of the
   benefit.
2. It keeps upstream's 89 MB out of every clone of this repository.
3. `.gitignore` covers `/picsimlab/` and `/picsimlab-reference/` anyway, so
   putting it inside still cannot commit it by accident.

## Getting it

```bash
git clone https://github.com/lcgamboa/picsimlab ../picsimlab-reference
```

That is enough for the rule checkers and the test suite. To actually run the
simulator you need it built — follow upstream's `INSTALL`, or install a
release from
[upstream's releases page](https://github.com/lcgamboa/picsimlab/releases),
which is simpler and is all the web UI needs.

## Applying our patches

Only if you need the x86-16 work. Everything else runs against stock
PICSimLab.

```bash
tools/apply_patches.sh                     # uses the resolved reference
tools/apply_patches.sh /path/to/picsimlab  # or an explicit checkout
```

Then rebuild. The script refuses a dirty tree and refuses to apply twice, so
a half-patched checkout is not a state you can reach by accident. See
`patches/README.md`.

## How the code finds it

Everything goes through `webui/picsimlab.py`, in this order:

| order | location |
|---|---|
| 1 | `$PICSIMLAB_ROOT` |
| 2 | `../picsimlab-reference/` |
| 3 | `../picsimlab/` |

`$PICSIMLAB_ROOT` is an instruction, not a hint: if it is set and wrong, that
is an error rather than a reason to fall back to a sibling. Silently checking
a different tree than the one you named is worse than failing.

### Two roots, deliberately separate

**`install_root()`** finds `share/` — board and part artwork. A *binary*
install has this, so the web UI runs against a packaged PICSimLab with no
source checkout anywhere.

**`source_root()`** finds `src/` — the C++ itself. Only a source checkout has
it, and only the dev-time rule checkers want it:

| checker | reads |
|---|---|
| `tools/check_board_contract.py` | `src/lib/board.h` |
| `tools/check_layering.py` | `src/sim_backend/` |
| `tools/check_part_schemas.py` | the paths each schema cites |
| `tools/draft_part_schemas.py` | `src/parts/*.cc` |

Keeping them apart is what lets a user run the UI without ever cloning
upstream, while CI still checks our schemas against the source they were read
from.

## When it is missing

Checkers **exit 3 and print `SKIPPED`**. Not 0, because a skip that looks like
a pass is how a suite goes green while checking nothing. Not 1, because
"could not run" is not "found a problem".

```
$ python tools/check_layering.py
check_layering: SKIPPED - no PICSimLab source checkout. Set $PICSIMLAB_ROOT
or see docs/picsimlab-reference.md.
$ echo $?
3
```

Tests skip through the `upstream` fixture in `tests/conftest.py`, so pytest
names them as skipped rather than failing.

CI clones the reference, so the skip never happens there — exit 3 fails the
job, which is the intended behaviour if the clone step ever breaks.

## Which revision

There is no pinned revision, deliberately.
`rules/upstream-sync.md` §4 explains why, and what to do when a patch
stops applying.
