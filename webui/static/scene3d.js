// OpenHardware — 3D board view with drag-to-wire.
//
// This program is free software; you can redistribute it and/or modify it under
// the terms of the GNU General Public License as published by the Free Software
// Foundation; either version 2, or (at your option) any later version.
//
// The board and every peripheral are drawn as slabs textured with the SVG art
// PICSimLab already ships, so nothing here needs a 3D model: `board.svg` and
// `part.svg` become the top faces, and the pads and pins are procedural.
//
// **This file positions things; it does not decide them.** Which pins exist,
// where they sit in image space, what they are wired to and whether a region
// is live all arrive from `webui/render_model.py` and `webui/pinmap.py`, which
// are testable. A wire drawn here is only ever a picture of a connection the
// simulator has confirmed.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

//: World units per image pixel. The board ends up ~40 units wide, which keeps
//: the default camera framing sane for every board from 376px to 702px wide.
const SCALE = 0.1;
const BOARD_THICKNESS = 1.6 * SCALE * 10; // 1.6 mm PCB, exaggerated to read
const PART_HEIGHT = 7;                    // how far peripherals float above
const PAD_RADIUS = 0.55;

const COLOUR = {
  wire: 0x4da3ff,
  wireHot: 0x46d17e,
  pad: 0xb08d3a,
  padHot: 0x4da3ff,
  anchor: 0x9aa4b4,
  anchorHot: 0x4da3ff,
  ghost: 0xe5c07b,
};

/** Turn an SVG URL into a texture. */
function texture(url) {
  const tex = new THREE.TextureLoader().load(url);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

/** A slab whose top face carries `url`, sized from the art's own pixels. */
function slab(widthPx, heightPx, url, thickness) {
  const w = widthPx * SCALE;
  const h = heightPx * SCALE;
  const art = new THREE.MeshBasicMaterial({ map: texture(url) });
  const edge = new THREE.MeshStandardMaterial({ color: 0x1b2230, roughness: 0.9 });
  // BoxGeometry face order is +X, -X, +Y, -Y, +Z, -Z; only +Y is the art.
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(w, thickness, h),
    [edge, edge, art, edge, edge, edge],
  );
  mesh.userData.pixelSize = { w: widthPx, h: heightPx };
  return mesh;
}

/**
 * Image pixel -> local slab coordinate.
 *
 * Image space has its origin top-left with y increasing downwards; the slab is
 * centred on its own origin with +Z pointing "down" the image.
 */
function toLocal(x, y, widthPx, heightPx) {
  return new THREE.Vector3(
    (x - widthPx / 2) * SCALE,
    0,
    (y - heightPx / 2) * SCALE,
  );
}

export class Scene3D {
  constructor(canvas, { onConnect, onNote }) {
    this.canvas = canvas;
    this.onConnect = onConnect;
    this.onNote = onNote || (() => {});

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.5, 500);
    this.camera.position.set(0, 46, 44);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.target.set(0, 0, 0);

    this.scene.add(new THREE.AmbientLight(0xffffff, 1.5));
    const key = new THREE.DirectionalLight(0xffffff, 1.8);
    key.position.set(20, 40, 20);
    this.scene.add(key);

    //: Everything rebuilt when the topology changes. Kept in one group so a
    //: rebuild is a single removal rather than bookkeeping per mesh.
    this.world = new THREE.Group();
    this.scene.add(this.world);

    this.pads = [];      // {pin, label, mesh, world}
    this.anchors = [];   // {partIndex, partName, label, mesh, world, wiredTo}
    this.wires = new THREE.Group();
    this.world.add(this.wires);

    this.pinmap = null;
    this.topology = "";
    this.drag = null;

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();

    this._bindPointer();
    this._resize();
    addEventListener("resize", () => this._resize());
    this._tick();
  }

  setPinMap(pinmap) {
    this.pinmap = pinmap;
    this.topology = ""; // force a rebuild; pads come from this
  }

  // --- construction ---------------------------------------------------------

  /**
   * Rebuild only when the set of objects changes.
   *
   * The render loop runs at ~8 fps; rebuilding meshes each frame would destroy
   * whatever the pointer is over and make dragging impossible.
   */
  update(model) {
    const key = [
      model.board,
      this.pinmap ? this.pinmap.pads.length : 0,
      ...model.parts.map((p) => `${p.index}:${p.name}:${p.anchors.length}`),
    ].join("|");

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

    // --- the board ---------------------------------------------------------
    const board = slab(
      model.width,
      model.height,
      `/board.svg?name=${encodeURIComponent(model.board)}`,
      BOARD_THICKNESS,
    );
    board.position.set(0, 0, 0);
    this.world.add(board);
    this.board = board;

    // --- its header pads ---------------------------------------------------
    if (this.pinmap) {
      const geo = new THREE.CylinderGeometry(PAD_RADIUS, PAD_RADIUS, 0.9, 12);
      for (const pad of this.pinmap.pads) {
        const mesh = new THREE.Mesh(
          geo,
          new THREE.MeshStandardMaterial({
            color: pad.pin ? COLOUR.pad : 0x3a4150,
            metalness: pad.pin ? 0.8 : 0.1,
            roughness: 0.35,
          }),
        );
        const local = toLocal(pad.x, pad.y, this.pinmap.width, this.pinmap.height);
        mesh.position.set(local.x, BOARD_THICKNESS / 2 + 0.35, local.z);
        // A pad with no MCU pin behind it is drawn and cannot be a drop target.
        mesh.userData = { kind: "pad", pin: pad.pin, label: pad.label };
        this.world.add(mesh);
        this.pads.push({
          pin: pad.pin,
          label: pad.label,
          mesh,
          world: mesh.position.clone(),
        });
      }
    }

    // --- the peripherals ---------------------------------------------------
    // Laid out in a row behind the board. Position carries no meaning: the
    // simulator has no notion of where a part physically sits.
    const spacing = 14;
    model.parts.forEach((part, i) => {
      if (!part.drawable) return;
      const mesh = slab(
        part.width,
        part.height,
        `/part.svg?name=${encodeURIComponent(part.name)}`,
        1.2,
      );
      const z = -(model.height * SCALE) / 2 - 10 - i * spacing;
      mesh.position.set(0, PART_HEIGHT, z);
      this.world.add(mesh);

      const geo = new THREE.SphereGeometry(0.7, 14, 10);
      for (const anchor of part.anchors) {
        const dot = new THREE.Mesh(
          geo,
          new THREE.MeshStandardMaterial({ color: COLOUR.anchor, roughness: 0.5 }),
        );
        const local = toLocal(anchor.x, anchor.y, part.width, part.height);
        dot.position.set(local.x, PART_HEIGHT - 0.8, z + local.z);
        dot.userData = {
          kind: "anchor",
          partIndex: part.index,
          partName: part.name,
          label: anchor.label,
        };
        this.world.add(dot);
        this.anchors.push({
          partIndex: part.index,
          partName: part.name,
          label: anchor.label,
          mesh: dot,
          world: dot.position.clone(),
          wiredTo: anchor.wired_to,
        });
      }
    });
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
    }
    if (changed || this.wires.children.length === 0) this._drawWires();

    // Lit board regions glow their pad, so a running LED reads in 3D too.
    const live = new Set(
      model.regions.filter((r) => r.active && r.index !== null).map((r) => r.index),
    );
    for (const pad of this.pads) {
      if (!pad.pin) continue;
      pad.mesh.material.color.setHex(live.has(pad.pin) ? COLOUR.padHot : COLOUR.pad);
    }
  }

  _drawWires() {
    this.wires.clear();
    for (const anchor of this.anchors) {
      if (!anchor.wiredTo) continue;
      const pad = this.pads.find((p) => p.pin === anchor.wiredTo);
      if (!pad) continue; // wired to a pin this board does not expose on a header
      this.wires.add(this._wire(anchor.world, pad.world, COLOUR.wire));
    }
  }

  /** A wire as a tube sagging between two points, the way a jumper hangs. */
  _wire(from, to, colour) {
    const mid = from.clone().lerp(to, 0.5);
    mid.y += Math.max(3, from.distanceTo(to) * 0.28);
    const curve = new THREE.QuadraticBezierCurve3(from, mid, to);
    return new THREE.Mesh(
      new THREE.TubeGeometry(curve, 24, 0.22, 8, false),
      new THREE.MeshStandardMaterial({ color: colour, roughness: 0.4 }),
    );
  }

  // --- dragging -------------------------------------------------------------

  _bindPointer() {
    const pick = (event) => {
      const rect = this.canvas.getBoundingClientRect();
      this.pointer.set(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      this.raycaster.setFromCamera(this.pointer, this.camera);
    };

    this.canvas.addEventListener("pointerdown", (event) => {
      pick(event);
      const hit = this.raycaster.intersectObjects(
        this.anchors.map((a) => a.mesh),
        false,
      )[0];
      if (!hit) return;
      const anchor = this.anchors.find((a) => a.mesh === hit.object);
      this.drag = { anchor, point: anchor.world.clone() };
      this.controls.enabled = false; // orbit must not fight the wire
      this.onNote(`dragging ${anchor.partName}.${anchor.label} — drop on a header pin`);
    });

    this.canvas.addEventListener("pointermove", (event) => {
      if (!this.drag) return;
      pick(event);
      const overPad = this.raycaster.intersectObjects(
        this.pads.filter((p) => p.pin).map((p) => p.mesh),
        false,
      )[0];
      if (overPad) {
        this.drag.point.copy(overPad.object.position);
        this.drag.over = overPad.object.userData;
      } else {
        // Follow the pointer across the board's own plane.
        const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
        const at = new THREE.Vector3();
        if (this.raycaster.ray.intersectPlane(plane, at)) this.drag.point.copy(at);
        this.drag.over = null;
      }
      this._drawWires();
      this.wires.add(this._wire(this.drag.anchor.world, this.drag.point, COLOUR.ghost));
    });

    const finish = async () => {
      if (!this.drag) return;
      const { anchor, over } = this.drag;
      this.drag = null;
      this.controls.enabled = true;
      this._drawWires();
      if (!over || !over.pin) {
        this.onNote("dropped on nothing — wire discarded");
        return;
      }
      await this.onConnect(anchor, over);
    };

    this.canvas.addEventListener("pointerup", finish);
    this.canvas.addEventListener("pointerleave", finish);
  }

  // --- housekeeping ---------------------------------------------------------

  _resize() {
    const parent = this.canvas.parentElement;
    if (!parent) return;
    const w = parent.clientWidth;
    const h = Math.max(360, Math.round(w * 0.62));
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
