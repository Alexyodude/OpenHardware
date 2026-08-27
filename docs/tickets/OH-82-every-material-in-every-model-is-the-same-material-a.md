---
id: OH-82
title: Every material in every model is the same material, and metal has nothing to
  reflect
status: done
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

**Note 2026-08-27:** CLOSED 2026-08-27 in 2c9d891. The Uno's gold contacts, nickel USB shell and tin legs read as three different metals, and the brightest pixel on the board went from 237 to 255 -- nothing in the old scene could produce a specular highlight, because there was nothing to reflect.

THE ANSWER TO THE QUESTION WAS 'NO'. It was never a render engine issue. three.js r185 already does everything wanted here and the vendored core already exported PMREMGenerator and the tone mapping constants; the limits were a constant in the IMPORTER and an absent environment. Worth remembering before the next 'should we change renderer' -- measure what the scene is asking the renderer for first.

AND THE PLAN WAS OVERTURNED BY THE FIRST MEASUREMENT. The previous handoff said the scene clips to white and that tone mapping was the top fix. `gl.readPixels` said 0 of 132,961 board pixels clipped and the brightest was 237: under-exposed, not blown out. After the change 0.01% clip, so tone mapping is STILL not wanted. Second time this session a handoff's advice has aged worse than its own numbers.

THE EVIDENCE FOR THE TABLE, because the assignment is the part that could be wrong. Loading every model in `compose_board_3d.CORRESPONDENCE` and tallying colour groups: #b58136 appears on 1X10, 1X08, 1X06, 2X03 and 2X02 and on NOTHING ELSE, so that colour is contact geometry by construction rather than by my opinion of a hex value. #a5a392 is every component's leg across six packages AND is what `lead_tips` already treats as metal by rule on the LEDs -- two independent readings agreeing. Three more are named outright in `tools/blender/usb_b_receptacle.py`, which calls its own materials `shell`, `cavity` and `pin`. This is the technique to reuse: ask the composer which package contributed a colour instead of looking at the colour.

THE BIGGEST GROUP IS THE ONE THAT MUST NOT BE TOUCHED. #808080 is UNSTYLED -- 48,301 triangles, more than every named colour on the Uno put together, and the most tempting thing in the corpus to 'improve'. It is a face the vendor did not style, so its material is unknown, and a test keeps it on the default. The four XIAO models therefore gain much less than the Uno, which is the honest outcome and not a gap to close.

MY OWN TEST DELETED FOUR ENTRIES, and that is the result I would keep if I could keep one. `test_every_finish_says_what_the_evidence_was` refuses a citation too short to be a sentence. Made to write the evidence out for #10178b, #000ca4, #ebebe5 and #ffffff, there was none -- three of them are 16, 4 and 2 triangles, far too small to be the board faces I had called them. A test that asks for the reason is how a plausible table stops being a confident one.

TWO OF MY TESTS PASSED FOR THE WRONG REASON and mutation found both. `NEUTRAL_LIGHT`'s use count stayed at 2 because a new COMMENT mentioned the constant while the ambient light it was counting was deleted -- a tripwire a sentence can reset is not a tripwire. And a `background` check used `in` on a string that appears twice, so changing one of the two assignments passed. Both count properly now.

A CONSOLE WARNING THAT IS NOT OURS: X4122, a float-precision note from the D3D backend compiling three.js's own PMREM shader. Confirmed by disabling the environment and reloading -- 0 warnings without it, 1 with. No shader is written in this repository, so this is the vendored library's and the '0 warnings' bar now has one known exception.

NEXT, IN THE ORDER I WOULD DO THEM: shadows or baked vertex ambient occlusion, which is what would make fifteen components look ATTACHED to the board rather than floating on it -- the stale 'this scene has one object' comment is finally gone but the shadows it was refusing are still absent. Then the tessellation angular tolerance, ANGULAR = 0.5 rad, which is about 29 degrees between facets and is why the barrel jack and the electrolytics are visibly polygonal; that is a one-line experiment. Then the PCB artwork as a planar-projected texture, which needs the licence question about PICSimLab's `board.svg` answered first -- the XIAO artwork is vendored but the Uno's is read out of a GPL install at runtime. Bloom last, and only it needs a new dependency.
