# How heypcb.ai has 11,030 open-source boards — NOT adopted

Research output for OH-205, read 2026-10-08. Like
`docs/research/board-sources/`, this is a set of dated claims about somebody
else's server. Nothing loads it, nothing checks it, and every number in it will
be wrong by the time it is next read. What it is for is the method, which does
not rot as fast as the counts.

Evidence class per claim, on the board-source survey's pattern. `S` means what
it means there; the other two are this note's own, and use letters the survey
does not, because its `O` is "opened" and its `U` is "unreachable":

| Class | Means |
|---|---|
| `S` stated | heypcb's own page says it; quoted, and the page is named |
| `R` requested | a request was made from here and its answer read |
| `N` not established | looked for and not found; what was tried is said |

## The answer in one paragraph

**They searched one host for one format, and asked nobody.** heypcb imports
"from public repositories that contain KiCad projects — today, public GitHub
repositories — and hold[s] each one under a placeholder profile until its
author claims it" (`S`, https://heypcb.ai/privacy §8). It copies "the project
files, the repository URL, the commit we copied, the owner's GitHub login and
the licence the repository declares" (`S`, same section). The terms say they do
not claim to own an imported board or to have been given permission to publish
it (`S`, https://heypcb.ai/terms, as quoted by the research pass; not re-read
here). An author claims a board by signing in with the GitHub account it was
published from, and anyone can have a design removed by email, after which "we
keep only the record that we removed it, which is what stops it being
re-imported" (`S`, privacy §8).

That is the whole trick. There is no vendor list, no per-board curation, and no
second format: EAGLE, Altium and EasyEDA are outside the stated scope, and
searching their gallery for `sparkfun` and `adafruit` turned up only a handful
of other people's KiCad repositories (`R`, research pass, `/world?q=`).
SparkFun and Adafruit publish EAGLE, which is why.

## The numbers, as they state them

- **11,030 boards**, "every count is over the whole directory as of 03:18 UTC"
  (`S`, https://heypcb.ai/world, read 2026-10-08). The homepage says "8,800+
  published open-hardware boards" (`S`, https://heypcb.ai/) — a stale banner or
  a different count; which is `N`.
- **Platform filters**, described as "Boards that name the part they are built
  around" (`S`, /world):

| Filter | Boards |
|---|---|
| Arduino / AVR | 752 |
| ESP32 | 647 |
| RP2040 | 374 |
| STM32 | 358 |
| Raspberry Pi | 268 |
| FPGA | 187 |
| ESP8266 | 169 |
| RISC-V | 103 |
| nRF52 | 100 |
| PIC | 44 |
| Teensy | 43 |
| CH32 | 39 |
| SAMD | 27 |
| MSP430 | 11 |

  They sum to 3,122 — about 28% of 11,030, before allowing for any board that
  sits under two filters. **Roughly seven boards in ten name no chip that any
  filter catches.**

- **Shelves** are filed "by its author's own words — the title, the description
  and the repository's topics" (`S`, /world): Keyboards 941, IoT 873, Retro
  732, Audio 653, RF 606, Robotics 548, Power 436, and "Great starting points"
  3,183, defined as "Under 30 parts, with a description and a licence that lets
  you copy the files".

## What a board page carries

A server-rendered picture, the board's size in millimetres, a part count and a
net count, tags, the repository's licence with a sentence on what it means, a
link back to the repository, and a `kicad.zip` (`S`, e.g.
https://heypcb.ai/world/b/95a558864569 and /world/b/525d37b68b03). ERC and DRC
read "not recorded" on imported boards (`S`).

"Where a repository declares no licence, we say 'All rights reserved' … [and
offer] no copy option" (`S`, terms, as quoted by the research pass).

## What is not available

- **No API and no dataset.** `robots.txt` disallows `/api/` and `/world`, and
  the sitemap carries 14 marketing URLs (`R`). A signed-out request for
  `/api/world/asset/525d37b68b03/kicad.zip` answered
  `401 {"error":"Unauthorized","code":"auth_required"}` (`R`).
- **Whether anything is parsed beyond part and net counts** — netlists, a BOM,
  which part is the chip — is `N`. No design zip could be opened signed out.
- **Whether a model classifies boards** is `N`. The page says shelves come from
  the author's words; nothing says a model reads the files.
- **When the service launched** is `N`. Coverage dates Circuit World to an X
  post on 2026-09-23; the article that says so answered 404 here.

## Read against this repository

Three things in it are already this repository's position, arrived at
separately:

1. **Licence per repository, not per vendor.** heypcb records the licence each
   repository declares, and refuses a copy where none is declared.
   `tools/board_sources.py` carries `Licence.sampled` for the same finding.
2. **Pin the revision.** They record "the commit we copied".
3. **A removal is remembered**, so it is not undone by the next crawl.

Two are not, and should not become so:

1. **They redistribute the files.** `tools/get_board_sources.py` fetches into
   the git-ignored `third_party/` and ships none of it. That is what lets this
   repository read any public repository without making a licence claim, and
   copying heypcb here would give that up.
2. **The chip comes from the author's words.** A filter that reads "the title,
   the description and the repository's topics" is enough for a gallery and is
   not enough for an emulator, which needs to know which pin is on which net.
   Of the eleven boards `tools/board_manifest.py` was written against by hand,
   two put their module on a footprint named for a different part — see
   `docs/superpowers/plans/2026-10-08-intake.md` §1.3. A chip read from the
   netlist, and confirmed by where its supply pins land, is the only reading
   this repository's evidence classes allow.

And one is the reason they have 11,030 boards and this repository has 37:
**they enumerate a format on a host; this repository finds one vendor's boards
by name and writes a row by hand for every other** — eleven so far.
That is what OH-205's ledger takes.
