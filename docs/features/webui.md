# Feature ledger — web UI (`bridge` + browser front-end)

Derived by the `feature-strategy` skill on 2026-08-10. Parsed by
`tools/ledger.py`; see `docs/features/README.md` for column meanings.

Strategy, Phase 0 evidence, and the transport decision live in
`docs/superpowers/plans/2026-08-10-webui.md`. Read it before working a cell —
the two-transport design and the reason the UI needs no new C++ are recorded
there and nowhere else.

Oracle shorthand:

- **rcontrol** — the command surface in `src/lib/rcontrol.cc`. For API cells the
  oracle is **differential**: the same command issued through the bridge must
  return what a direct TCP session returns.
- **sim-state** — the simulator itself. A UI action is correct when its effect
  is readable back through the API: pressing a button in the browser is right
  only if `get part[N].in[M]` then reports the new value. The UI is never its
  own oracle, and "it looked right" is never evidence.
- **pzw** — a `.pzw` workspace, which is a zip storing board and processor by
  name. Round-tripping one is checkable byte-for-byte on the parts it owns.
- **network-log** — the browser's own request log, for the offline guarantee.

`F1`-`F3` do not apply to any cell here. Those tiers describe timing and
electrical fidelity, which a user interface does not have; everything is `F0`,
and that is a statement about the tier scale rather than about ambition.

Only one table may appear in this file: `tools/ledger.py` parses every
pipe-delimited row it finds.

| id | tier | oracle | tolerance | status | fixture |
|---|---|---|---|---|---|
| webui.dec0.transport-order | F0 | rcontrol | exact | planned | - |
| webui.bridge.process | F0 | rcontrol | exact | done | tests/webui/test_live_oracle.py |
| webui.bridge.framing | F0 | rcontrol | exact | done | tests/webui/test_live_oracle.py |
| webui.bridge.queueing | F0 | rcontrol | exact | in-progress | - |
| webui.bridge.disconnect-fails-loudly | F0 | rcontrol | exact | in-progress | - |
| webui.bridge.localhost-only | F0 | network-log | exact | in-progress | - |
| webui.api.session-control | F0 | rcontrol | exact | done | tests/webui/test_live_oracle.py |
| webui.api.pins-read | F0 | rcontrol | exact | done | tests/webui/test_live_oracle.py |
| webui.api.pins-write | F0 | rcontrol | exact | in-progress | - |
| webui.api.board-io | F0 | rcontrol | exact | in-progress | - |
| webui.api.parts-list | F0 | rcontrol | exact | done | tests/webui/test_live_oracle.py |
| webui.api.parts-io | F0 | rcontrol | exact | in-progress | - |
| webui.api.parts-add-remove | F0 | rcontrol | exact | in-progress | - |
| webui.api.parts-config | F0 | rcontrol | exact | in-progress | - |
| webui.api.firmware-load | F0 | rcontrol | exact | in-progress | - |
| webui.api.scope | F0 | rcontrol | exact | in-progress | - |
| webui.api.board-info | F0 | rcontrol | exact | done | tests/webui/test_live_oracle.py |
| webui.ui.board-canvas | F0 | sim-state | exact | done | tests/webui/test_live_oracle.py |
| webui.ui.run-controls | F0 | sim-state | exact | done | tests/webui/test_live_oracle.py |
| webui.ui.firmware-picker | F0 | sim-state | exact | planned | - |
| webui.ui.part-palette | F0 | sim-state | exact | planned | - |
| webui.ui.part-place | F0 | sim-state | exact | planned | - |
| webui.ui.part-remove | F0 | sim-state | exact | planned | - |
| webui.ui.part-config | F0 | sim-state | exact | planned | - |
| webui.ui.button-press | F0 | sim-state | exact | planned | - |
| webui.ui.pot-drag | F0 | sim-state | exact | planned | - |
| webui.ui.led-render | F0 | sim-state | exact | done | tests/webui/test_live_oracle.py |
| webui.ui.display-render | F0 | sim-state | exact | planned | - |
| webui.ui.pin-inspector | F0 | sim-state | exact | in-progress | - |
| webui.ui.scope-view | F0 | sim-state | exact | planned | - |
| webui.ui.serial-terminal | F0 | sim-state | exact | planned | - |
| webui.ws.load-pzw | F0 | pzw | exact | planned | - |
| webui.ws.save-pzw | F0 | pzw | exact | planned | - |
| webui.ws.round-trip | F0 | pzw | exact | planned | - |
| webui.pkg.one-command-local | F0 | network-log | exact | planned | - |
| webui.pkg.offline-guarantee | F0 | network-log | exact | planned | - |
| webui.wasm.template-shell | F0 | rcontrol | exact | planned | - |
| webui.wasm.assets-dir | F0 | rcontrol | exact | planned | - |
| webui.wasm.build-script | F0 | rcontrol | exact | planned | - |
| webui.wasm.ci-job | F0 | rcontrol | exact | planned | - |
| webui.wasm.export-api | F0 | rcontrol | exact | planned | - |
| webui.wasm.transport-swap | F0 | rcontrol | exact | planned | - |
| webui.wasm.single-file | F0 | network-log | exact | planned | - |
