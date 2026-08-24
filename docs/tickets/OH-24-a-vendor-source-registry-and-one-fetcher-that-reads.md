---
id: OH-24
title: A vendor source registry, and one fetcher that reads it
status: done
priority: P1
created: '2026-08-25'
touches:
- tools/board_sources.py
- tools/get_board_sources.py
- tests/rules/test_board_sources.py
parent: OH-23
---

tools/get_seeed_hardware.sh is one vendor hard-coded into one shell script: the repository URL, the library directory name and the --all flag are all Seeed-specific. A second vendor written the same way is a second script, and fifteen is fifteen.

Replace it with a cited Python table plus one fetcher, the shape webui/boards/catalogue.py already uses for CHIPS: the table is the only hand-written thing, every row cites the survey row it came from, and the fetcher is generic over the table.

Per source: repository URL, licence, the globs worth fetching, and the globs deliberately not fetched with the reason. Fetch, do not vendor -- downloads land in git-ignored third_party/, so rules/licence-hygiene.md is untouched by a vendor whose files are not MIT. That distinction is the whole reason this can cover vendors Seeed's licence would not have allowed.

Keep the retiring script's reasoning: its header explains that vendoring Seeed's tree was *permitted* and rejected on size. That paragraph should survive into the new tool rather than being lost with the file.

Done when three vendors fetch from the same code path with no vendor-specific branch, tools/check_licenses.py still reports zero stray licences, and get_seeed_hardware.sh is deleted rather than left beside its replacement.

Depends on the survey ticket for the rows.
