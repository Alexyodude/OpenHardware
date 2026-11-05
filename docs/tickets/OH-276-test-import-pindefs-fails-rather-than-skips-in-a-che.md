---
id: OH-276
title: test_import_pindefs fails rather than skips in a checkout that fetched the
  BSPs but not every board source
status: open
priority: P3
created: '2026-11-05'
---

Found 2026-11-05 under OH-64, in a worktree whose third_party/ held only bsp/ (arduino-esp32, arduino-pico, seeed-nrf52, seeed-samd, silabs-arduino, zephyr). _needs_the_fetched_packages skips only when the BSPs are absent, so with them present and the rest absent:

- test_the_committed_modules_match_the_generator and test_the_committed_board_files_match_the_generator raise PindefError for third_party/seeed-pcb and third_party/adafruit-feather-esp32-c6 (the C5's and C6's blocks, and the Feather's file);
- test_the_real_tree_never_resolves_a_pad_from_nothing fails on ('MTMS', 4) and test_the_s3s_usb_pads_rest_on_the_same_five_variants_as_its_jtag fails too. These two may be the S3's arduino-esp32 variant moving at today's HEAD rather than the partial fetch: unverified.

The same class as OH-250 (composer tests), in another file. Done when: each test that needs a source skips by name with the fetch command when that source is absent, and still fails when it is present and wrong; the two S3 failures are reproduced on a full fetch and either fixed or filed.
