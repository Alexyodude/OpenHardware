---
id: OH-37
title: A board may claim it runs only when a named test watched real firmware execute
status: done
priority: P1
created: '2026-08-25'
touches:
- rules/board-claims.md
- tools/check_board_claims.py
- tests/rules/test_board_claims.py
- .github/workflows/rules.yml
---

catalogue.py already carries the mechanism, as a dict and a docstring: FIRMWARE_VERIFIED maps a chip to the test that watched a real compiled image execute, and its comment is the principle -- 'Having a built core and a board description means a board *could* run something; it is not evidence that anything has. The distinction is small on a good day and the whole difference on a bad one.'

Today that is one entry, RP2040 -> tests/cortexm0/test_blink.py, and one test checking the file exists. As boards multiply the pressure to relax it multiplies with them: a chip whose core is built and whose siblings work will look runnable, and nothing outside that dict stops the word appearing next to it.

Promote it to a rule with a checker, the shape rules/ already uses -- frontmatter declaring the tier and the checker, armed, run before commit alongside the other six. It fails when any surface says a board runs without a named test, when a named test is missing, and when a named test exists but never loads an image.

The counter-pressure is real and the repository has already resisted it twice: OH-13 refused to call 25 unwired boards supported, and OH-19 refused a selector entry for surveyed-but-unbuilt chips because 'an option you can never pick is a promise the repo has not made.' This makes that refusal structural instead of remembered.

Done when the checker fails on a fabricated claim, passes on RP2040, and is listed in CLAUDE.md's pre-commit block.

**Note 2026-08-25:** REGRESSION, found within minutes of arming: ungrounded_code_claims fires on webui/boards/samd21.py:54, which is a false positive. The matched prose is 'PM_APBBMASK_PORT ... so the bit is set before firmware runs', a statement about a clock-enable bit at power-on, and the very next sentence names tests/cortexm0/test_samd21_blink.py as what turns the claim into a measurement. That is the discipline this rule exists to encourage, and the checker fails it. The matcher is keying on the substring rather than on a claim that a board or chip runs. Because the rule is armed and in CI, this blocks another session's OH-39 work. Tighten what counts as a claim; the negative control must include this exact sentence.
