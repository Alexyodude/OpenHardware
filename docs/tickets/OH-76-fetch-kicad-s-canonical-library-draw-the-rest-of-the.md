---
id: OH-76
title: Fetch KiCad's canonical library, draw the rest of the Uno, and model the USB-B
  nobody publishes
status: done
priority: P2
created: '2026-08-27'
touches:
- tools/compose_board_3d.py
- tools/import_3d_model.py
- tools/model_from_datasheet.py
- tests/rules/test_compose_board_3d.py
- tests/rules/test_import_3d_model.py
- webui/static/board3d-panel.js
- tests/webui/test_board3d.py
- third_party/modelled
---

ASKED FOR BY THE USER, 2026-08-27: "GET IT 1,2,3. if there isn't a part in any of those then look at the datasheet and make it in blender." The three being the canonical KiCad library, the manufacturers' own STEP, and Arduino's Eagle libraries.

THE SOURCE OH-75 USED IS A PARTIAL MIRROR, which is the finding that started this. tools/compose_board_3d.py and tools/import_3d_model.py both fetch from `KiCad/kicad-packages3D` on GitHub. KiCad's canonical home is GitLab, and it is NOT the same tree. Counted 2026-08-27:

  Connector_USB          github  5 entries   gitlab 13
  Connector_BarrelJack   github  4           gitlab  5
  Button_Switch_THT      github 127          gitlab 82

So the mirror diverges in BOTH directions and is not simply older. For the six models OH-75 actually uses it is byte-for-byte identical -- 885,081 / 356,629 / 286,283 / 215,953 / 185,520 / 125,561 -- so nothing already drawn is wrong. What the mirror costs is COVERAGE, and OH-75's note that "Connector_USB holds five entries" is the mirror's count rather than the library's. That sentence needs correcting whatever else happens here.

THE CONCLUSION IT WAS EVIDENCE FOR SURVIVES THE BETTER SOURCE. GitLab's Connector_USB is three USB-A, seven USB-C, one Micro-B and one Mini-B. **There is no type-B receptacle in KiCad's library at all**, so the Uno's most recognisable feature after the headers still has no published mesh.

EVERY OTHER UNDRAWN PART DOES HAVE ONE, which is the substance of this ticket. Surveyed against the canonical library 2026-08-27, with each element's own pad span measured by eagle.Element.pad_extent:

  X1   POWERSUPPLY_DC-21MM  9 THT  5.99 x 5.77   Connector_BarrelJack/BarrelJack_Horizontal
  U3   MLF32               33 SMD  4.90 x 4.90   Package_DFN_QFN/QFN-32-1EP_5x5mm_P0.5mm_EP3.3x3.3mm
  U1   SOT223               4 SMD  6.20 x 4.62   Package_TO_SOT_SMD/SOT-223
  PC1  PANASONIC_D          2 SMD  0.00 x 4.80   Capacitor_SMD/CP_Elec_6.3x5.4
  PC2  PANASONIC_D          same
  Y1   QS                   2 THT  5.08 x 0.00   Crystal/Crystal_HC49-U_Vertical
  RESET TS42                5 SMD  8.40 x 4.50   Button_Switch_SMD/SW_SPST_B3S-1000

Each is a proposal and none is trusted: confirm() re-measures the mesh against the pads on every run and refuses one that does not fit, which is what caught the header orientation in OH-75.

Y2 (RESONATOR, 3 SMD pads spanning 2.00 mm) is expected to FAIL that check and that is the right outcome: every Resonator-*Pin in KiCad's Crystal library is through-hole, and a through-hole resonator standing on surface-mount pads is a different part in the right place. It is drawn only if the numbers agree.

THE USB-B, IN THE ORDER THE USER GAVE. (1) KiCad canonical: none, above. (2) The manufacturer: X2's package comes from Arduino's own `SmartPrj` EAGLE library and PN61729 is a through-hole type-B receptacle; Wurth, Molex, TE and Amphenol publish free STEP for their own connectors and one of them is the part. (3) Arduino's Eagle libraries: footprints only, no 3D -- checked, and recorded here so nobody looks twice. If (2) yields nothing usable under a licence this repository can take -- the standing objection that ruled out GrabCAD for the ESP32-C3 -- then it is modelled from the datasheet in Blender 4.5.4, which is installed here and runs headless.

A MODELLED PART IS A FOURTH KIND OF SOURCE and must say so. OH-75 established three captions because a composed model may not claim to be a vendor's. A part whose geometry came from a drawing rather than from CAD is further still from the vendor's own mesh, and every dimension in it has to cite the datasheet line it came from -- otherwise it is exactly the invented-height defect that whole ticket was built to avoid.

Done when tools fetch from KiCad's canonical library rather than the GitHub mirror; the Uno draws its barrel jack, its USB-B, both electrolytics, the 16U2, the regulator, the crystal and the reset button; every part still absent says why in the panel; and no dimension anywhere is unsourced -- a mesh, or a datasheet page cited beside the number.

NOT IN THIS TICKET: the 61 test points and the 0603/0805 passives, which are 1.6 mm long and not what anybody looks at; and any other board -- the three XIAO ESP32-C3s keep their footprint and their GrabCAD note.

**Note 2026-08-27:** CLOSED 2026-08-27 in 7f6e3bf. All three of the sources the user named, and then the fourth, which is the one that made the Uno look finished.

(1) THE SOURCE WAS A PARTIAL MIRROR, and this is the finding worth carrying. Both mesh tools fetched from KiCad/kicad-packages3D on GitHub; the library lives on GitLab and the trees differ -- Connector_USB 5 against 13, Connector_BarrelJack 4 against 5, Button_Switch_THT 127 against 82. It diverges in BOTH directions, so it is not simply older. Every model already imported was byte-for-byte identical, so nothing drawn was wrong; the cost was coverage. THE GENERALISATION: OH-75's sentence 'Connector_USB holds five entries' was a claim about the mirror wearing the library's name -- the same defect as OH-29's census of Seeed's git repository, which closed a question for a day by stating a conclusion without its scope. A negative result inherits the authority of whatever you searched, and a mirror has less than it looks like.

(2) THE MANUFACTURER. Wurth publish a STEP for the 61729 series the Uno's USB package is named for. It is behind a site search this cannot reach by URL, and that is recorded in why_not_fetched with the note that a hand-fetched copy is strictly better than what replaced it.

(3) SO IT IS MODELLED. tools/model_from_datasheet.py drives Blender 4.5.4 headless. The rule that makes a hand-built part safe to have: every number is either the vendor's or cited. All the plan geometry is READ out of Arduino's package at build time rather than retyped -- four signal pins, two 2.2 mm shell posts 12 mm apart, a body of 11.80 x 15.75 mm -- so it cannot drift from the board file the way a copied pad table would. Five numbers are in no file here and each carries its source; the load-bearing one is the 10.44 mm shell height, which is the USB Series-B standard rather than a guess, because a plug from any vendor has to enter a socket from any other.

SEVEN MORE PARTS CAME OUT OF THE BETTER LIBRARY: barrel jack, the ATmega16U2 as a QFN-32, the SOT-223 regulator, both electrolytics and the reset button. Fifteen components against eight.

THREE FINDINGS, AND TWO OF THEM WERE MY OWN CHECKS BEING WEAK RATHER THAN THE CODE BEING WRONG.

  (a) confirm() accepted a through-hole resonator standing on surface-mount pads. 7 mm of body against 2 mm of pads is inside a tolerance that HAS to allow a body wider than its pins, so no tightening of the size check could have caught it. It checks MOUNTING now: a mesh says which kind of part it is by whether it has geometry below the board. The same observation gave (b) for free.

  (b) The anchor moved from the body to the LEGS. Centring a body on its pads is right for a DIP and a header, whose shrouds are symmetric about their pins, and wrong for a barrel jack, whose barrel is entirely to one side. A through-hole model says where its own pins are, and that is exactly what the pads describe -- so the assumption OH-75 had to STATE is now derived. This is what puts the jack and the socket over the board's edge instead of buried in it.

  (c) 'Nothing hangs off the edge' was the wrong invariant wearing the right answer's clothes. It passed for a day because every part happened to be an interior one -- and a connector is edge-mounted PRECISELY so it can overhang. The USB shell stands 5.94 mm proud and the barrel jack 0.07, both correctly. What may never leave the outline is the geometry below the board, and the tighter test asserts each part's legs land on the pads it is soldered to. That distinction is what caught the anchor mutation the loose test slept through.

TWO PARTS ARE STILL NOT DRAWN and each entry carries the measurement that rules the obvious candidate out, so nobody repeats the search. Y1's body is 6.86 x 4.57 mm by Arduino's own silkscreen and every through-hole crystal in KiCad's library is an HC49 at 10.90 or 11.05 -- near enough to PASS the footprint check and half as long again as the real can, so it is the vendor's drawing that says no rather than the check. Y2 is a 3.20 x 1.60 mm surface-mount resonator against KiCad's 7 mm through-hole cans. Both are timing parts a few millimetres across; they were offered to the user as a follow-up rather than modelled, and that offer is open.

A FOURTH KIND OF SOURCE NEEDED A FOURTH SENTENCE. OH-75 established three captions because a composed model may not claim to be a vendor's. A part built here is further still, so the panel NAMES it -- 'X2 (USB_B_PN61729)' -- rather than counting it. Saying 'one part was modelled' would tell a reader something in the picture is less trustworthy without telling them which, which is the worst of both.

9 new tests. Seven mutations, all caught, after one round in which the anchor revert survived -- which is what produced (c).

NOT IN THIS TICKET: the 61 test points and the 0603/0805 passives, which are 1.6 mm long; and any other board -- the three XIAO ESP32-C3s keep their footprint and their GrabCAD note.
