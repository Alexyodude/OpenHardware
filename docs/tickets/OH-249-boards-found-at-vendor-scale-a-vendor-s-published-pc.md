---
id: OH-249
title: 'Boards found at vendor scale: a vendor''s published PCB repositories joined
  to the BSP variants that name the same board, so a new board is found and not hand-picked'
status: open
priority: P2
created: '2026-11-05'
---

Slice of OH-174 (its sixth: 'discovery at vendor scale'). Filed 2026-11-05 with no claims; take it and claim with tickets.py set --touches.

Every board added since OH-176 was picked by hand and given a row in tools/board_manifest.py: the registry in tools/board_sources.py names each source one at a time. OH-174's bound on 'all' is sources, not boards (docs/research/board-sources/README.md), and the pin side is not the constraint: third_party/bsp/arduino-esp32/variants holds 404 variants and arduino-pico/variants 151 (counted 2026-11-05 in a checkout that has fetched them; third_party/ is git-ignored). The registry's own rows state the scale on the CAD side: Adafruit 'one repository per board; 634 match PCB in the name under org:adafruit', SparkFun 1,413 repositories under org:sparkfun, Olimex 144 under org:OLIMEX, PCBCUPID 46.

WHAT THIS IS. A tool that, per vendor, lists the published PCB repositories (or archives), reads which board each is from what the vendor states (repository name, board file title, README), and joins it to the variant directory that names the same board, then prints three lists: joined (a candidate row, with its CAD file, licence file and variant), CAD with no variant (three layers at best), and variant with no CAD (cannot join; geometry has no source). A join is evidence for a row, not a row: adding a board stays a manifest row checked by board_manifest.py --check, and a candidate whose chip is not in catalogue.FIRMWARE_VERIFIED is listed as reaching three layers, in OH-174's order.

OPEN QUESTIONS, for the ticket to settle with evidence. (1) What a join is allowed to rest on: a name match is a guess, and rules/board-claims.md and the repository's habit (a claim is read from a file, or it says why not) mean each join cites what it matched, and an ambiguous one is printed as ambiguous, not chosen. (2) The licence per repository, not per organisation: the olimex-esp32-poe row already found a sibling repository with no LICENSE at all, so an organisation's licence is never inherited. (3) Network: listing hundreds of repositories through the GitHub API is rate-limited; whether the listing is cached, pinned and replayable offline, as fetches are pinned by commit and sha256 elsewhere here, so the output is reproducible and a test can hold it. (4) Do not write the list down: CLAUDE.md forbids a maintained inventory, so the tool prints it and nothing commits its counts.

DONE WHEN the tool runs for at least one vendor (Adafruit or SparkFun, whose rows are EAGLE and read today) from a pinned listing, every joined candidate names what it matched, and a test fails when a join is made on a name the listing does not hold.
