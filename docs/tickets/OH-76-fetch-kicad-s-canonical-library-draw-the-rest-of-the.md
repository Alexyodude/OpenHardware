---
id: OH-76
title: Fetch KiCad's canonical library, draw the rest of the Uno, and model the USB-B
  nobody publishes
status: open
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
