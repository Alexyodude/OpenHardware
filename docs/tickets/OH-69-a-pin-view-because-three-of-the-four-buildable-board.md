---
id: OH-69
title: A pin view, because two of the three buildable boards cannot print
status: open
priority: P1
created: '2026-08-26'
touches:
- webui/static/emulator.html
- webui/static/emulator.js
- webui/static/emulator.css
- tests/webui/test_pin_view.py
---

THE BROWSER FOUND THIS, on 2026-08-26, while closing OH-66. A sketch was built and run on a XIAO SAMD21 and there is nowhere on the page a pin appears. The board panel has a report line, an error line and a UART console, and that is all -- so on a board whose Serial is USB CDC the only feedback a person gets is 'XIAO-SAMD21-DIP: 200,000 instructions. pc 0x00000386'.

THE CONSOLE PANE IS ALREADY HONEST ABOUT IT, in these words: 'webui.boards.samd21 models no UART, so nothing on a SAMD21 can print. This is a gap in the board description, not silence from the program.' That is the right sentence and it is not a substitute for showing the pin.

WHY IT MATTERS MORE NOW THAN IT DID. Until OH-66 the IDE built for one board, and that board has a modelled USART -- so Serial.print WAS the feedback and a pin view looked optional. Three boards can be built for now and two of them cannot print at all -- corrected the same day from 'four and three', which came from adding the recipe rows to the boards instead of counting the boards. The user asked twice for 'standard development workflows like platformio and arduino style', and watching an LED is the first thing anybody does in that workflow.

WHAT EXISTS TO BUILD ON, and it is more than it looks. Every board carries a pin map: webui/boards/*.json has label-to-chip-pin from tools/import_pindefs.py, and webui/boards/samd21.py already exports LED_PIN with a citation to Seeed's own variant table. tests/webui/test_compile.py watches PA17 through exactly those constants. So the data is there and what is missing is the pane.

WHAT WOULD MAKE THIS WRONG RATHER THAN INCOMPLETE. A pin view that showed a pin as low because the board does not model its port would be the failure class this repository ranks worst -- the same argument webui/boards/samd21.py makes for leaving PORT.IN unmapped. A pin the board cannot answer for must read as unknown and say so, not as off.

NOT A 3D VIEW AND NOT A PAD MAP. OH-30 is blocked on source material -- no board here has a mesh -- and this needs none: a list of pin names with a state each is enough to watch a blink, and it is what the Arduino IDE's own serial plotter is not.

Done when a sketch built in the browser for a XIAO SAMD21 makes something on the page change twice, when a pin the board does not model reads as unknown rather than as low, and when a named test drives it in a real browser.
