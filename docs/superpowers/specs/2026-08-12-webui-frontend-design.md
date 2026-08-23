# The browser front-end

**Date:** 2026-08-12
**Status:** design approved, not implemented
**Supersedes:** the "conduction ceiling" in `2026-08-10-peripherals-design.md` §8,
and `docs/known-issues.md` 4a.4 and 4a.5. See §9.

## 1. What this is

`webui/` today is a websocket server with no client. `bridge.py` speaks to
nobody: there is not one `.html`, `.js` or `.css` file in this repository. The
fourteen `webui.ui.*` cells in `docs/features/webui.md` are all `planned`.

This specifies the front-end that fills them, over the transport already built
and verified against a live simulator.

**Not the WASM build.** Upstream's `src/Makefile.JS` compiles the existing
C++ GUI — LXRAD on SDL2 — onto a canvas. It puts the 2005 desktop widget layout
in a browser, which is a different product from a web UI, and it needs six
hardcoded sibling checkouts plus a `template.html` and an `assets/` directory
that are not in this tree. The transport seam in `webui/api.py` still allows it
later; nothing here forecloses it.

## 2. Three measurements that shaped this

All three were taken on 2026-08-12 against the live PICSimLab 0.9.3 running in
WSL, not read from source.

### 2.1 `info` is a whole-state dump

One command returns the board's outputs and every placed part with its inputs
named:

```
Board:     Arduino Uno
Processor: atmega328p
Frequency:   16000000 Hz
Use Spare: 1
    board.out[01] LD_L=   0
  part[00]: Push Buttons
    part[00].in[00] PB_1= 0
    ...
```

The front-end therefore polls **one** command per frame rather than one per
element. This matters more than it looks: `bridge.py` serialises every request
behind an `asyncio.Lock`, because rcontrol has no request IDs and concurrent
requests would interleave. A per-element render loop would queue behind that
lock and scale with the circuit. A single dump does not.

### 2.2 The board art is already a web format

`share/` ships 108 SVGs and 86 `.map` files. The maps are **HTML image maps**
emitted by GIMP:

```html
<area shape="rect" coords="158,53,169,63" href="O_LD_L" />
<area shape="rect" coords="32,10,65,43"   href="B_PB_RST" />
```

The `href` is a region id whose prefix gives its role — `O_` output, `B_`
button, `I_` input — and whose remainder matches the names the simulator reports
(`O_LD_L` ↔ `board.out[01] LD_L`). So the browser needs no new artwork and no
geometry: it renders the shipped SVG and overlays the shipped rectangles.

### 2.3 Every indexed accessor is fixed-width two-digit

`src/lib/rcontrol.cc:748` parses an index by character position, not by
`atoi`:

```c
int out = (ptr[11] - '0') * 10 + (ptr[12] - '0');
```

For `board.out[1]` that reads `']'` as the second digit and computes 55, which
fails the range test and returns ERROR. `board.out[01]` returns `LD_L= 97`.

This single fact has produced three separate wrong conclusions in this project's
documentation, each recorded as an upstream defect that does not exist. It is
not a quirk to remember; it is an invariant that belongs in exactly one place in
the code.

**Consequence worth stating:** two digits is also a ceiling. Indices above 99
are unaddressable through this protocol, which bounds parts at 100 for any
operation that indexes one.

## 3. Architecture

```
browser
  webui/static/*.{html,js,css}      vanilla ES modules, no build step
        |  websocket JSON, existing allowlist
  webui/bridge.py                   + static and asset routes
        |
  webui/render_model.py             NEW: state + map -> draw list
  webui/assets.py                   NEW: locate share/ art, parse .map
  webui/api.py                      + state, board I/O, part I/O, osc
        |
  rcontrol TCP  ->  picsimlab (native)
```

Everything above the transport line is additive. `webui/rcontrol.py` is
untouched.

## 4. The stack, and why it has no build step

Plain ES modules served by `bridge.py`. No npm, no bundler, no `node_modules`.

Three reasons, in order of weight:

1. `webui.pkg.offline-guarantee` is a ledger cell whose oracle is the browser's
   own network log. A page with no external origins satisfies it by
   construction; a bundled page has to be audited to prove it.
2. `rules/gpl-hygiene.md` §3 restricts dependency licences and is
   *already* knowingly weaker than its own standard at three Python
   dependencies (known-issues 3.4). Adding a transitive npm tree before the
   dependency checker exists would make an acknowledged gap much worse.
3. `python webui/bridge.py` stays the entire install, which is what
   `webui.pkg.one-command-local` says.

The board art is SVG and the interaction model is rectangles over an image.
That is native DOM work. A framework would earn its cost on a large stateful
form UI; this is not one.

## 5. Components

| unit | responsibility | depends on |
|---|---|---|
| `webui/assets.py` | Resolve the `share/` root, load `board.svg`, parse `board.map` into typed regions | nothing |
| `webui/render_model.py` | Pure function: parsed state + regions → draw list | `assets` |
| `webui/api.py` | New ops. **Sole construction site for indexed accessors** | `rcontrol` |
| `webui/bridge.py` | Serve `static/`, serve art, extend the operation allowlist | `api`, `assets` |
| `webui/static/board.js` | Paint the draw list, dispatch region clicks | — |
| `webui/static/parts.js` | Palette, placement, config forms generated from schemas | — |
| `webui/static/scope.js` | Oscilloscope view | — |
| `webui/static/terminal.js` | `IO Virtual Term` view | — |
| `webui/static/app.js` | Websocket client, poll loop, view wiring | — |

`webui/parts/` — the schema layer built on 2026-08-10 — currently has **no
consumer at all**. `parts.js` becomes its first one, which is also the first
real test of whether that abstraction was the right shape.

## 6. Where the logic lives, and why

You cannot test a DOM without a browser runner, and there is no npm here to
install one. Fourteen cells whose oracle is `sim-state` would then have no
reachable fixture, and `rules/conformance-fixtures.md` §3 forbids
marking those `done`.

So the model is Python and the browser is a renderer.

`render_model.py` takes a parsed state dump and a parsed map and returns a draw
list — which region, at which coordinates, in which visual state, clickable or
not. It performs no I/O and imports no transport. It is therefore testable
under the existing pytest suite, including against a live simulator, and the
cells it backs get real fixtures.

`board.js` paints that list and posts events back. It holds no derived state.
The rule is: **if a browser file contains a decision, it is in the wrong file.**

This is a deliberate trade. It puts a round trip between a click and its
repaint, which is invisible at human interaction rates and is what the existing
serialised transport does anyway.

## 7. Data flow

**Render.** `app.js` polls `state` on an interval → `bridge` calls
`api.state()` → `info` → parsed to a typed structure → `render_model` combines
it with the cached region map → draw list → websocket → `board.js` paints.

**Interact.** A click on region `B_PB_RST` → `app.js` posts
`{op: "board_input", id: "B_PB_RST", value: 1}` → `bridge` validates against the
allowlist → `api.set_board_input` formats `set board.in[00] = 1` **with the
index zero-padded in `api.py`, nowhere else** → the next poll shows the effect.

The UI never renders an optimistic result. A click that the simulator did not
accept must not look like it worked — that is the miswiring-reported-as-success
failure this project has already hit twice.

## 8. Cell coverage and honest status

All fourteen `webui.ui.*` cells are in scope. Three cannot honestly reach
`done` on this design alone, and are listed so that is a stated outcome rather
than a discovery:

| cell | status it can reach | why |
|---|---|---|
| `ui.button-press` | `in-progress` | Writes to `part[00].in[00]` are accepted, but `0` and `1` both read back `16`. Until that encoding is pinned down, a fixture cannot assert a press. |
| `ui.scope-view` | `in-progress` | `oscrdcfg` returns real configuration, but `oscmeasures` returns ERROR live. The read path is proven, the measurement path is not. |
| `ui.serial-terminal` | `in-progress` | Needs an `IO Virtual Term` part placed, and part placement can segfault the simulator (4a.1). |

The other eleven can reach `done` with a live fixture. The UI ships for all
fourteen either way; what differs is what the ledger is permitted to claim.

## 9. What this corrects

Two recorded upstream defects do not exist, and one spec section rests on the
false one. All three were the same parsing mistake in §2.3.

- **`docs/known-issues.md` 4a.4** — "`get board.in[]` and `get board.out[]`
  return ERROR on Arduino Uno, which has no on-board controls". The Uno has an
  on-board L LED, `info` advertises it as `board.out[01]`, and
  `get board.out[01]` returns `LD_L= 97`.
- **`docs/known-issues.md` 4a.5** — "`get part[0].in[N]` returns ERROR for
  every N, so `Part->GetInputCount()` is 0". `get part[00].in[00]` returns
  `PB_1= 0`. Input enumeration works.
- **`2026-08-10-peripherals-design.md` §8** — its conduction ceiling is
  justified by 4a.5 and inherits the error. The ceiling is *narrower* than
  stated: reads of a part's inputs work; what remains unproven is the meaning
  of a written value.

Both entries were measured honestly and recorded honestly. They were measured
with an unpadded index, and the server answers a differently-shaped question
than the one the measurement intended to ask. The correction is not that the
earlier work was careless; it is that ERROR is a single undifferentiated reply,
so "malformed request" and "unsupported feature" are indistinguishable without
reading the parser. That is the lesson worth keeping.

## 10. Error handling

The existing posture is unchanged and extended:

- Every failure raises. No operation returns a sentinel that a caller can
  ignore, matching `webui/rcontrol.py`.
- A dropped connection surfaces in the UI as a disconnected state, never as a
  frozen last-known-good render. 4a.1 and 4a.7 mean the simulator can die
  mid-session, and a UI that keeps showing the last frame is claiming a
  simulator that is not there.
- `assets.py` raises on an empty or unparseable map, per the house rule that a
  checker returning an empty result is indistinguishable from one that verified
  nothing.
- Region ids in a `.map` that the simulator does not report are dropped with a
  count, not silently. A board whose art and firmware disagree is a real
  condition worth seeing.

## 11. Testing

| layer | how |
|---|---|
| `assets.py` | pytest against the real shipped `.map` and `.svg` files, not fixtures invented here |
| `render_model.py` | pytest, pure function, table-driven |
| `api.py` additions | stub for shape, `test_live_oracle.py` for truth |
| zero-padding | a dedicated test asserting every indexed command `api.py` emits is two-digit — this is the invariant that has already cost three wrong conclusions |
| `static/*.js` | no automated coverage; kept thin enough that this is acceptable, and said out loud rather than implied |

`OPENHARDWARE_LIVE=1` continues to make an unreachable simulator a failure
rather than a skip.

## 12. Non-goals

- Not the WASM build (§1).
- Not a 3D view — that is still its own sub-project.
- No upstream C++ changes. An `atoi`-based index parser is the right eventual
  contribution and would retire §2.3 entirely, but it needs a build pipeline
  that can verify it, which known-issues 4a.6 shows does not yet exist here.
- No npm, no bundler, no framework (§4).
- Not authentication or multi-user. The bridge is loopback-only by design.
