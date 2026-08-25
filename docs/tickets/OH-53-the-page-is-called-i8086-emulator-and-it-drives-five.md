---
id: OH-53
title: The page is called i8086 Emulator and it drives five boards across three architectures
status: done
priority: P2
created: '2026-08-25'
touches:
- webui/static/emulator.html
- webui/emulator_server.py
- tests/webui/test_emulator_session.py
---

The browser tab says "i8086 Emulator" while a person loads an ATmega328P into it. That is a wrong label on real data, which this repository ranks above a fault.

The name is not stale so much as never revisited. The page began as OH-7, a UI for core/i8086 when that was the only core, and boards, targets, the board picker and OH-52's Arduino Uno were all added into it. Six places still carry the old identity:

  webui/static/emulator.html:3    header comment, "the i8086 emulator, in a browser"
  webui/static/emulator.html:17   <title>i8086 Emulator</title>
  webui/static/emulator.html:22   favicon SVG, which draws the text "86"
  webui/static/emulator.html:27   <div class="brand">i8086 - OpenHardware</div>
  webui/emulator_server.py:1      header comment
  webui/emulator_server.py:504    server_version = "OpenHardware-i8086"
  webui/emulator_server.py:650    startup banner, "i8086 emulator on http://..."

NOT A FIND-AND-REPLACE, and this is the whole care of the ticket. The Emulator tab hosts TWO machines sharing the same panes:

 - the i8086 session -- webui/emulator.py, the sample-program controls at emulator.html:60-74, DRIVING = "i8086" and DRIVABLE = {"i8086"} in the server. Those names are CORRECT. That half really is an 8086, and renaming them would replace a true specific name with a false general one, which is the opposite error and the worse one.
 - the board path -- webui/api.py, #board-pick, 26 boards and 5 runnable across cortexm0 and avr.

So what is wrong is that one half's name sits on the whole window. Scope is page identity only: title, brand, favicon, server_version, banner, and the two file header comments. DRIVING, DRIVABLE, webui/emulator.py and every "this pane is showing an 8086" explanation stay exactly as they are.

Name chosen: "OpenHardware", plain, matching what the repo, the README and every ticket already call it. Rejected "OpenHardware Emulator" as carrying a word that will date the same way "i8086" did once the page grows past emulating.

No test pins any of these strings today, which is itself the reason this drifted for so long. Done when the strings are right AND a test pins the page-level name against the i8086-specific one, so the next capability added to this page cannot quietly leave the label behind again.
