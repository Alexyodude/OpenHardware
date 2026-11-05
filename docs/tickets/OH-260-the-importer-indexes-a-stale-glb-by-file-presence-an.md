---
id: OH-260
title: The importer indexes a stale .glb by file presence and fetches the MSOP-8 STEP
  unpinned
status: open
priority: P3
created: '2026-11-05'
---

Carried through OH-163 from OH-199's and OH-161's reviews. (1) write_index lists every entry, with file None where no .glb is on disk, while the composer (since OH-199) leaves a skipped board out of the index; and an 'import_3d_model.py --all' run re-indexes a stale .glb by file presence alone, so a board whose import now fails keeps an index entry for an old mesh. (2) part_pads parses the footprint twice after the pin check. (3) The MSOP-8 STEP (the MCP9808's, OH-161 step 5 slice 4d) is fetched from KiCad master without a pinned revision or digest, unlike the models fetched by tag.

Paths it will want, claimed when it is started rather than now (open tickets may not share a claim): `tools/import_3d_model.py`, `tests/rules/test_import_3d_model.py`.
