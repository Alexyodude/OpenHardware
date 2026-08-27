---
id: OH-82
title: Every material in every model is the same material, and metal has nothing to
  reflect
status: open
priority: P2
created: '2026-08-27'
touches:
- tools/import_3d_model.py
- webui/static/board3d.js
- tests/rules/test_import_3d_model.py
- tests/webui/test_board3d.py
---

ASKED FOR BY THE USER 2026-08-27: "how would we make the 3d view more realistic?
Render engine issue?" It is not a render engine issue, and the measurements say
where it actually is.

WHAT WAS MEASURED FIRST, because the previous handoff's section 6.2 said the
scene clips to white and that tone mapping was the top fix. Read back out of the
framebuffer with `gl.readPixels` on a drawn Arduino Uno: of 132,961 board
pixels, **ZERO clipped channels**; brightest channel 237 of 255; mean peak
132.6; and 55% of every board pixel inside a single 16-value band. The scene is
not blown out. It is under-exposed and flat, and tone mapping alone would make
it darker. That item drops down the list -- and it is the second time a
handoff's advice has aged worse than its numbers.

THE ACTUAL CAUSE, AND IT IS IN THE IMPORTER RATHER THAN THE RENDERER.
`tools/import_3d_model.py` writes `metallicFactor: 0.1, roughnessFactor: 0.6`
for EVERY material of EVERY model. All ten of the Arduino Uno's colours -- the
gold header contacts, the nickel USB shell, the tin-plated IC legs, the black
epoxy, the blue solder mask -- are the same substance as far as the renderer is
concerned. Nothing in the scene has a material identity, which is why it reads
as a diagram.

AND THE TWO HALVES CANNOT BE SPLIT. Raising metalness with no environment map
makes metals go BLACK, because a metal's colour IS its reflection and there is
nothing to reflect. So the finish table and the image-based light are one
change or they are a regression.

NOTHING NEEDS VENDORING. Checked in `webui/static/vendor/three.core.js`:
`PMREMGenerator`, `ACESFilmicToneMapping`, `AgXToneMapping`, `DataTexture` and
`EquirectangularReflectionMapping` are all exported already. `RoomEnvironment`
is an addon and is NOT vendored -- and does not need to be, because
`PMREMGenerator.fromScene()` takes any scene and RoomEnvironment is a handful of
emissive boxes.

WHICH COLOUR IS WHICH MATERIAL, DERIVED RATHER THAN GUESSED. This is the part
worth getting right, and the precedent is `Part.lens`, whose comment already
settled the same argument: "Stated per part rather than guessed: the least grey
group works on an LED and not on a black buzzer, and a rule that works on one
file is a rule that will be wrong on the next one somebody adds."

Three independent sources of evidence, gathered 2026-08-27:

1. **THIS REPOSITORY'S OWN SOURCE NAMES THREE OF THEM.**
   `tools/blender/usb_b_receptacle.py` builds the USB-B out of materials it
   calls `shell`, `cavity` and `pin`, and those come out as `#9ea1a8`,
   `#0d0d0f` and `#b8994c`. Not inference at all -- the file says so.

2. **WHICH PACKAGE CONTRIBUTES WHICH COLOUR, from the composer.** Loading each
   of `compose_board_3d.CORRESPONDENCE`'s KiCad models and tallying its colour
   groups:

     #a5a392  8,497 tri  DIL28, MLF32, PANASONIC_D, BARREL JACK, SOT223, TS42
     #050505  3,598 tri  the bodies of those same six
     #b58136  1,224 tri  1X10, 1X08, 1X06, 2X03, 2X02 -- HEADERS AND NOTHING ELSE
     #c6c4a0    440 tri  TS42 only
     #383838    422 tri  TS42 only
     #6f6651    100 tri  MLF32 and SOT223 only

   `#b58136` appearing on the five pin-header packages and on nothing else is
   the strongest single result here: that colour is header contact geometry by
   construction, so it is gold plating. `#a5a392` is every component's LEG --
   and it is also what `lead_tips` already treats as metal by rule ("every
   group that is not the lens is metal"), on the LEDs and the buzzer.

3. **WHAT THE TREE ALREADY RECORDS.** `board3d.js`'s `refreshTheme` names two
   outright: "#116517 for that board's solder mask, #ff9f37 for the gold on its
   castellated pads."

THE ONE THAT MUST NOT BE GIVEN A MATERIAL, and it is the biggest group in the
whole corpus: `#808080` is `UNSTYLED`, 48,301 triangles across four vendor
models, and its own comment says it is "the one colour in this file that is not
the vendor's ... rather than pretending to be a material." A face the vendor
did not style is a face whose material nobody here knows. It keeps the neutral
default, explicitly, and the four XIAO models will therefore improve LESS than
the Uno. That is the honest outcome rather than a shortfall to fix.

METALNESS IS DERIVED; ROUGHNESS IS A STATED CHOICE. Worth keeping separate in
the table and in the reader's head. Whether a material is a conductor is a fact
about what the thing is, and 0 or 1 is the only physically meaningful pair. A
roughness of 0.30 for a plated contact is a choice inside a sensible band -- the
same register as the USB-B's `wall`, which its own citation calls "not a
measurement -- it is a drawing thickness". Each entry says which of the two it
is.

WHAT LANDS:
  * `Finish(metalness, roughness, why)` in `tools/import_3d_model.py`, and a
    `FINISHES` table keyed by the colour, covering the colours above.
  * anything not in it keeps today's 0.1/0.6, and the importer PRINTS which
    finish each colour group got and how many triangles it covers, so a reader
    can audit the assignment against the picture rather than trusting it.
  * a studio environment built procedurally in `board3d.js` and installed as
    `scene.environment`, with the lights rebalanced -- an IBL replaces an
    ambient light rather than adding to one.
  * the background stays the palette's `ground`; the environment is
    illumination, which is the exemption `NEUTRAL_LIGHT` already claims in that
    file for exactly this reason.

MEASURE IT AGAIN AFTERWARDS. The same `readPixels` histogram, before and after.
If adding IBL energy pushes the scene over 1.0 then tone mapping becomes
relevant and can be decided on the number rather than on the received wisdom.

LEAST CONFIDENT, while changing it still costs a sentence:
  1. `#c6c4a0` and `#383838` are both TS42, the B3S-1000 tactile switch, and
     which is the metal cover and which the plastic actuator is read off their
     values rather than off anything named. Lowest-evidence pair in the table.
  2. `#e7c863` and `#edbe51` are large gold-family groups on the ESP32-S3,
     nRF52840 and RP2040 and are called gold BY ANALOGY with `#ff9f37`, which
     the tree names. Analogy across one vendor's model set, not a record.
  3. Whether the environment should follow the theme. It stands for the light in
     the room rather than for the page's palette, so it does not -- but a
     bright studio reflected in a dark-theme scene is a choice, not a fact.

NOT IN THIS TICKET: shadows and baked ambient occlusion; the PCB artwork as a
texture, which needs the licence question about PICSimLab's `board.svg` settled
first; the tessellation angular tolerance; bloom, which is the only item that
needs a new dependency.

DONE WHEN the Uno's gold contacts, nickel shell and tin legs read as three
different metals, `#808080` is demonstrably untouched, the importer prints its
assignment for every group, and the before/after histogram is in the commit.
