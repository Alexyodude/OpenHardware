---
id: OH-250
title: Five composer tests fail rather than skip in a checkout with no third_party
  fetched
status: open
priority: P3
created: '2026-11-05'
---

Found 2026-11-05 under OH-174, in a fresh worktree where third_party/ (git-ignored) was never fetched. tests/rules/test_compose_board_3d.py: 5 failed, 155 passed, 135 skipped. The file's convention is to skip by name what is not fetched (_fetched, 'SKIPPED: <file> is not fetched. Run: ...'), and these five do not:

- test_every_composed_board_draws_its_routing: AssertionError 'only 0 layouts are fetched, so this is thin' (line ~3933).
- test_the_usb_c_shell_is_an_obround_and_not_a_box: AssertionError '0 sockets are built, and there are three' (line ~4132).
- test_a_curved_wire_on_the_silkscreen_is_read_as_a_pin_one_marker, test_a_circle_on_the_silkscreen_is_read_as_a_pin_one_marker, test_a_curved_outline_is_not_a_pin_one_marker: tools.eagle.EagleError, FileNotFoundError on third_party/arduino-uno/UNO-TH_Rev3e.brd.

So python tools/checkall.py reports 'FAILED: the test suites pass' on any checkout that has not run the fetches, and a real failure in that row is indistinguishable from an unfetched tree. OH-216's closing note saw a neighbouring set (usb_b paddle, rounding the shell) fail the same way and put it down to a stale cache, unverified.

Done when: each of the five skips naming the file and the command that fetches it when that file is absent, and still fails when it is present and wrong (a thin-coverage assertion such as 'only 0 layouts' should fail only when some layout is fetched); a test shows the skip, red with the old behaviour.
