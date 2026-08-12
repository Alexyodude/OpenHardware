// OpenHardware — 3D board view with drag-to-wire.
//
// This program is free software; you can redistribute it and/or modify it under
// the terms of the GNU General Public License as published by the Free Software
// Foundation; either version 2, or (at your option) any later version.
//
// Components are procedural geometry from `models3d.js`; the board is a PCB
// slab textured with the `board.svg` PICSimLab already ships, carrying a real
// 0.1in header whose gold pins are the drop targets.
//
// **This file positions things; it does not decide them.** Which pins exist,
// where they sit in image space, what they are wired to and whether a region
// is live all arrive from `webui/render_model.py` and `webui/pinmap.py`, which
// are testable. A wire drawn here is only ever a picture of a connection the
// simulator has confirmed.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import { buildHeader, buildPart, hasModel, setGlow } from "/models3d.js";

//: World units per image pixel. A 402px board becomes ~40 units wide, which
//: keeps the default framing sane for every board from 376px to 702px.
const SCALE = 0.1;
const BOARD_THICKNESS = 1.6;
const PART_PCB = 1.2;
const PART_HEIGHT = 16;   // how far peripherals float above the board
const PART_GAP = 16;      // between peripherals, front to back

//: Anchors sit ON TOP of the peripheral's own PCB. An earlier version put them
//: at `PART_HEIGHT - 0.8`, which is *below* a slab whose underside is at
//: `PART_HEIGHT - 0.6` -- the dots were buried inside the board and could
//: never be picked, which is why dragging did nothing.
const ANCHOR_R = 0.85;
const ANCHOR_Y = PART_PCB / 2 + ANCHOR_R;

const COLOUR = {
  wire: 0x4da3ff,
  ghost: 0xe5c07b,
  anchor: 0x9aa4b4,
  anchorWired: 0x4da3ff,
  anchorHot: 0x46d17e,
};

export class Scene3D {
  constructor(canvas, { onConnect, onDisconnect, onNote }) {
    this.canvas = canvas;
    this.onConnect = onConnect;
    this.onDisconnect = onDisconnect || (async () => {});
    this.onNote = onNote || (() => {});

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.5, 800);
    this.camera.position.set(6, 62, 74);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.target.set(0, 6, -12);

    this.scene.add(new THREE.AmbientLight(0xffffff, 1.25));
    const key = new THREE.DirectionalLight(0xffffff, 2.0);
    key.position.set(28, 60, 34);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0x88aaff, 0.7);
    fill.position.set(-30, 25, -30);
    this.scene.add(fill);

    this.world = new THREE.Group();
    this.scene.add(this.world);
    this.wires = new THREE.Group();
    this.world.add(this.wires);

    this.pads = [];     // {pin, label, mesh, world}
    this.anchors = [];  // {partIndex, partName, label, mesh, world, wiredTo}
    this.glowing = [];  // {index, meshes}
    this.pinmap = null;
    this.topology = "";
    this.drag = null;

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();

    this._bindPointer();
    this._resize();
    this._observer = new ResizeObserver(() => this._resize());
    this._observer.observe(canvas.parentElement);
    this._tick();
  }

  setPinMap(pinmap) {
    this.pinmap = pinmap;
    this.topology = ""; // pads come from this, so force a rebuild
  }

  // --- construction ---------------------------------------------------------

  update(model) {
    const key = [
      model.board,
      this.pinmap ? this.pinmap.pads.length : 0,
      ...model.parts.map((p) => `${p.index}:${p.name}:${p.anchors.length}`),
    ].join("|");

    // Rebuilding every frame would destroy whatever the pointer is holding.
    if (key !== this.topology) {
      this.topology = key;
      this._build(model);
    }
    this._refresh(model);
  }

  _build(model) {
    for (const child of [...this.world.children]) {
      if (child !== this.wires) this.world.remove(child);
    }
    this.pads = [];
    this.anchors = [];
    this.glowing = [];

    const toBoardLocal = (x, y) =>
      new THREE.Vector3(
        (x - model.width / 2) * SCALE,
        0,
        (y - model.height / 2) * SCALE,
      );

    // --- the board ---------------------------------------------------------
    const art = new THREE.MeshBasicMaterial({
      map: this._texture(`/board.svg?name=${encodeURIComponent(model.board)}`),
    });
    const edge = new THREE.MeshStandardMaterial({ color: 0x123a28, roughness: 0.75 });
    const board = new THREE.Mesh(
      new THREE.BoxGeometry(model.width * SCALE, BOARD_THICKNESS, model.height * SCALE),
      [edge, edge, art, edge, edge, edge],
    );
    this.world.add(board);

    // --- its header --------------------------------------------------------
    if (this.pinmap) {
      const header = buildHeader(this.pinmap.pads, toBoardLocal, BOARD_THICKNESS / 2);
      this.world.add(header);
      for (const entry of header.userData.pins) {
        this.pads.push({
          pin: entry.pad.pin,
          label: entry.pad.label,
          mesh: entry.mesh,
          world: entry.world,
        });
      }
    }

    // --- the peripherals ---------------------------------------------------
    // Laid out in a row behind the board. Position carries no meaning: the
    // simulator has no notion of where a part physically sits.
    let modelled = 0;
    model.parts.forEach((part, i) => {
      if (!part.drawable) return;
      const built = buildPart(
        part.name,
        part.width,
        part.height,
        `/part.svg?name=${encodeURIComponent(part.name)}`,
        SCALE,
      );
      if (built.kind === "model") modelled += 1;

      const z = -(model.height * SCALE) / 2 - 14 - i * PART_GAP;
      built.group.position.set(0, PART_HEIGHT, z);
      this.world.add(built.group);

      // LED-style parts glow with the value the simulator reports.
      const items = built.parts?.userData?.items ?? [];
      if (items.length) {
        this.glowing.push({ partIndex: part.index, items });
      }

      const geo = new THREE.SphereGeometry(ANCHOR_R, 16, 12);
      for (const anchor of part.anchors) {
        const dot = new THREE.Mesh(
          geo,
          new THREE.MeshStandardMaterial({ color: COLOUR.anchor, roughness: 0.45 }),
        );
        dot.position.set(
          (anchor.x - part.width / 2) * SCALE,
          ANCHOR_Y,
          (anchor.y - part.height / 2) * SCALE,
        );
        dot.userData = {
          kind: "anchor",
          partIndex: part.index,
          partName: part.name,
          label: anchor.label,
        };
        built.group.add(dot);

        const world = new THREE.Vector3();
        dot.getWorldPosition(world);
        this.anchors.push({
          partIndex: part.index,
          partName: part.name,
          label: anchor.label,
          mesh: dot,
          world,
          wiredTo: anchor.wired_to,
        });
      }
    });

    const total = model.parts.filter((p) => p.drawable).length;
    if (total) {
      const flat = total - modelled;
      this.onNote(
        flat === 0
          ? `${modelled} peripheral${modelled === 1 ? "" : "s"} modelled`
          : `${modelled} modelled, ${flat} shown as textured board${flat === 1 ? "" : "s"} (no model yet)`,
      );
    }
  }

  // --- per-frame values -----------------------------------------------------

  _refresh(model) {
    const wiring = new Map();
    for (const part of model.parts) {
      for (const anchor of part.anchors) {
        wiring.set(`${part.index}/${anchor.label}`, anchor.wired_to);
      }
    }

    let changed = false;
    for (const anchor of this.anchors) {
      const now = wiring.get(`${anchor.partIndex}/${anchor.label}`) ?? null;
      if (now !== anchor.wiredTo) {
        anchor.wiredTo = now;
        changed = true;
      }
      if (!this.drag || this.drag.anchor !== anchor) {
        anchor.mesh.material.color.setHex(
          anchor.wiredTo ? COLOUR.anchorWired : COLOUR.anchor,
        );
      }
    }
    if (changed && !this.drag) this._drawWires();

    // Component glow, driven by the part's own reported input values.
    for (const entry of this.glowing) {
      const part = model.parts.find((p) => p.index === entry.partIndex);
      if (!part) continue;
      entry.items.forEach((item, i) => {
        const value = part.inputs[i]?.value ?? 0;
        const intensity = Math.min(1, Math.abs(value) / 255);
        for (const mesh of item.userData.glow ?? []) {
          mesh.userData.glowColour = item.userData.glowColour;
          setGlow(mesh, intensity);
        }
        // Tactile caps depress when pressed.
        if (item.userData.press) item.userData.press.position.y = value ? 1.9 : 2.2;
      });
    }
  }

  _drawWires(ghost) {
    this.wires.clear();
    for (const anchor of this.anchors) {
      if (!anchor.wiredTo) continue;
      const pad = this.pads.find((p) => p.pin === anchor.wiredTo);
      if (!pad) continue; // wired to a pin this board exposes on no header
      this.wires.add(this._wire(anchor.world, pad.world, COLOUR.wire));
    }
    if (ghost) this.wires.add(this._wire(ghost.from, ghost.to, COLOUR.ghost));
  }

  /** A wire as a tube sagging between two points, the way a jumper hangs. */
  _wire(from, to, colour) {
    const mid = from.clone().lerp(to, 0.5);
    mid.y += Math.max(4, from.distanceTo(to) * 0.3);
    const curve = new THREE.QuadraticBezierCurve3(from, mid, to);
    return new THREE.Mesh(
      new THREE.TubeGeometry(curve, 28, 0.26, 8, false),
      new THREE.MeshStandardMaterial({ color: colour, roughness: 0.45 }),
    );
  }

  // --- picking --------------------------------------------------------------

  _at(event) {
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(this.pointer, this.camera);
  }

  _hitAnchor() {
    const hit = this.raycaster.intersectObjects(
      this.anchors.map((a) => a.mesh),
      false,
    )[0];
    return hit ? this.anchors.find((a) => a.mesh === hit.object) : null;
  }

  _hitPad() {
    const hit = this.raycaster.intersectObjects(
      this.pads.filter((p) => p.pin).map((p) => p.mesh),
      false,
    )[0];
    return hit ? this.pads.find((p) => p.mesh === hit.object) : null;
  }

  _bindPointer() {
    // **Capture phase.** OrbitControls binds its own pointerdown to this same
    // canvas; disabling it afterwards leaves an orbit already in progress, so
    // the camera fights the wire. Running first and stopping propagation is
    // what keeps a drag from also spinning the board.
    this.canvas.addEventListener(
      "pointerdown",
      (event) => {
        this._at(event);
        const anchor = this._hitAnchor();
        if (!anchor) return;

        event.stopPropagation();
        event.preventDefault();
        this.canvas.setPointerCapture(event.pointerId);
        this.controls.enabled = false;
        this.drag = { anchor, to: anchor.world.clone(), pad: null };
        anchor.mesh.material.color.setHex(COLOUR.anchorHot);
        this.onNote(
          `${anchor.partName}.${anchor.label} — drop on a gold header pin, ` +
            `or anywhere else to cancel`,
        );
      },
      true,
    );

    this.canvas.addEventListener("pointermove", (event) => {
      if (!this.drag) return;
      this._at(event);

      const pad = this._hitPad();
      if (pad) {
        this.drag.to.copy(pad.world);
        this.drag.pad = pad;
      } else {
        // Follow the pointer across the board's top plane.
        const plane = new THREE.Plane(
          new THREE.Vector3(0, 1, 0),
          -BOARD_THICKNESS / 2,
        );
        const at = new THREE.Vector3();
        if (this.raycaster.ray.intersectPlane(plane, at)) this.drag.to.copy(at);
        this.drag.pad = null;
      }
      this._drawWires({ from: this.drag.anchor.world, to: this.drag.to });
    });

    const finish = async (event) => {
      if (!this.drag) return;
      const { anchor, pad } = this.drag;
      this.drag = null;
      this.controls.enabled = true;
      if (event?.pointerId !== undefined && this.canvas.hasPointerCapture(event.pointerId)) {
        this.canvas.releasePointerCapture(event.pointerId);
      }
      anchor.mesh.material.color.setHex(
        anchor.wiredTo ? COLOUR.anchorWired : COLOUR.anchor,
      );
      this._drawWires();

      if (!pad) {
        this.onNote("cancelled — nothing was changed");
        return;
      }
      await this.onConnect(anchor, { pin: pad.pin, label: pad.label });
    };

    this.canvas.addEventListener("pointerup", finish);
    this.canvas.addEventListener("pointercancel", finish);

    // Double-click a wired pin to unwire it.
    this.canvas.addEventListener("dblclick", async (event) => {
      this._at(event);
      const anchor = this._hitAnchor();
      if (!anchor || !anchor.wiredTo) return;
      event.stopPropagation();
      await this.onDisconnect(anchor);
    });
  }

  // --- housekeeping ---------------------------------------------------------

  _texture(url) {
    const tex = new THREE.TextureLoader().load(url);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = 8;
    return tex;
  }

  _resize() {
    const parent = this.canvas.parentElement;
    if (!parent || !parent.clientWidth) return;
    const w = parent.clientWidth;
    const h = Math.max(420, Math.round(w * 0.66));
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _tick() {
    requestAnimationFrame(() => this._tick());
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}

export { hasModel };
