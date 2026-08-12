// OpenHardware — paint draw lists onto board and peripheral art.
//
// This program is free software; you can redistribute it and/or modify it under
// the terms of the GNU General Public License as published by the Free Software
// Foundation; either version 2, or (at your option) any later version.
//
// This file holds no decisions. Which regions exist, whether one is active, how
// bright it is and whether it can be clicked are all computed by
// `webui/render_model.py`, because there is no browser test runner here and
// logic that cannot be tested cannot back a ledger cell that claims to work.
//
// If you find yourself about to write a threshold, a lookup or a fallback in
// this file, it belongs in render_model.py instead.

const SVG = "http://www.w3.org/2000/svg";

function element(name, attrs) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, value);
  }
  return node;
}

function hitShape(region) {
  if (region.shape === "circle") {
    return element("circle", {
      cx: (region.left + region.right) / 2,
      cy: (region.top + region.bottom) / 2,
      r: region.radius,
      class: "hit",
    });
  }
  return element("rect", {
    x: region.left,
    y: region.top,
    width: region.right - region.left,
    height: region.bottom - region.top,
    rx: 1.5,
    class: "hit",
  });
}

function glowShape(region) {
  const width = region.right - region.left;
  const height = region.bottom - region.top;
  if (region.shape === "circle") {
    return element("circle", {
      cx: (region.left + region.right) / 2,
      cy: (region.top + region.bottom) / 2,
      r: region.radius,
      class: "glow",
    });
  }
  return element("rect", {
    x: region.left,
    y: region.top,
    width,
    height,
    rx: Math.min(width, height) / 3,
    class: "glow",
  });
}

/** Fill one <svg> overlay with a list of drawables. */
function paintRegions(overlay, regions, width, height, onClick) {
  overlay.setAttribute("viewBox", `0 0 ${width} ${height}`);
  overlay.replaceChildren();

  for (const region of regions) {
    const group = element("g", {
      class: [
        "region",
        region.clickable ? "clickable" : "",
        region.value === null ? "unbound" : "",
      ]
        .filter(Boolean)
        .join(" "),
    });
    group.setAttribute("data-id", region.id);

    if (region.active) {
      const glow = glowShape(region);
      glow.setAttribute("opacity", String(0.25 + 0.75 * region.intensity));
      group.append(glow);
    }
    group.append(hitShape(region));

    const label = document.createElementNS(SVG, "title");
    label.textContent =
      region.value === null
        ? `${region.id} — not reported`
        : `${region.id} = ${region.value}`;
    group.append(label);

    if (region.clickable && onClick) {
      group.addEventListener("click", () => onClick(region));
    }
    overlay.append(group);
  }
}

/** Render the board image and its live overlay. */
export function paint(model, onRegionClick) {
  const img = document.getElementById("board-img");
  const source = `/board.svg?name=${encodeURIComponent(model.board)}`;
  if (img.getAttribute("src") !== source) {
    img.setAttribute("src", source);
    img.setAttribute("alt", `${model.board} board`);
  }
  paintRegions(
    document.getElementById("overlay"),
    model.regions,
    model.width,
    model.height,
    onRegionClick,
  );
}

// --- the workbench ----------------------------------------------------------
//
// Placed peripherals are rendered from the same art pipeline as the board:
// `share/parts/<cat>/<name>/part.{svg,map}`, region ids bound by name to the
// values `info` reports for that part.
//
// The DOM is rebuilt only when the set of placed parts changes. Rebuilding
// every frame would destroy the node under the pointer mid-click and make
// buttons unpressable at a 120 ms poll.

let workbenchKey = "";

export function paintWorkbench(model, handlers) {
  const host = document.getElementById("workbench");
  const note = document.getElementById("workbench-note");
  const key = model.parts.map((p) => `${p.index}:${p.name}`).join("|");

  if (key !== workbenchKey) {
    workbenchKey = key;
    host.replaceChildren();

    for (const part of model.parts) {
      const card = document.createElement("div");
      card.className = "part-card";
      card.dataset.index = String(part.index);

      const head = document.createElement("div");
      head.className = "part-head";
      const title = document.createElement("h3");
      title.textContent = `part[${String(part.index).padStart(2, "0")}] ${part.name}`;
      head.append(title);

      const wire = document.createElement("button");
      wire.className = "link";
      wire.type = "button";
      wire.textContent = "wiring";
      wire.addEventListener("click", () => handlers.onWiring(part));
      head.append(wire);

      const drop = document.createElement("button");
      drop.className = "link danger";
      drop.type = "button";
      drop.textContent = "remove";
      drop.addEventListener("click", () => handlers.onRemove(part));
      head.append(drop);
      card.append(head);

      if (part.drawable) {
        const stage = document.createElement("div");
        stage.className = "part-stage";
        const img = document.createElement("img");
        img.src = `/part.svg?name=${encodeURIComponent(part.name)}`;
        img.alt = part.name;
        const overlay = document.createElementNS(SVG, "svg");
        overlay.setAttribute("xmlns", SVG);
        overlay.classList.add("part-overlay");
        stage.append(img, overlay);
        card.append(stage);
      } else {
        const missing = document.createElement("p");
        missing.className = "note";
        missing.textContent = "this peripheral ships no image map, so it cannot be drawn";
        card.append(missing);
      }

      const wiring = document.createElement("div");
      wiring.className = "wiring";
      wiring.hidden = true;
      card.append(wiring);

      host.append(card);
    }
  }

  // Repaint values every frame; the DOM above is stable.
  for (const part of model.parts) {
    const card = host.querySelector(`.part-card[data-index="${part.index}"]`);
    if (!card) continue;
    const overlay = card.querySelector(".part-overlay");
    if (overlay && part.drawable) {
      paintRegions(overlay, part.regions, part.width, part.height, (region) =>
        handlers.onRegionClick(part, region),
      );
    }
  }

  note.textContent =
    model.parts.length === 0
      ? "no peripherals placed"
      : `${model.parts.length} placed`;
}

/** Render a part's schema-driven wiring form into its card. */
export function paintWiring(partIndex, schema, wiring, onConnect) {
  const card = document.querySelector(`.part-card[data-index="${partIndex}"]`);
  if (!card) return;
  const host = card.querySelector(".wiring");
  host.hidden = false;
  host.replaceChildren();

  if (schema === null) {
    const none = document.createElement("p");
    none.className = "note";
    none.textContent =
      "no schema for this peripheral — its config layout has not been read " +
      "from source, and a guessed one would miswire the circuit silently.";
    host.append(none);
    return;
  }

  const cite = document.createElement("p");
  cite.className = "note";
  cite.textContent = schema.verified
    ? `verified: ${schema.verified}`
    : `layout from ${schema.source} — not confirmed by a live round-trip`;
  host.append(cite);

  for (const field of schema.fields) {
    if (field.role !== "pin") continue;
    const row = document.createElement("label");
    row.className = "wire-row";

    const name = document.createElement("span");
    name.textContent = `${field.label} (${field.dir})`;
    row.append(name);

    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.max = "255";
    input.value = String(wiring[field.label] ?? 0);
    input.addEventListener("change", () =>
      onConnect(field.label, Number(input.value)),
    );
    row.append(input);
    host.append(row);
  }

  const settings = schema.fields.filter((f) => f.role !== "pin");
  if (settings.length) {
    const line = document.createElement("p");
    line.className = "note";
    line.textContent =
      "settings (read-only here): " +
      settings.map((f) => `${f.label}=${wiring[f.label]}`).join(", ");
    host.append(line);
  }
}

// --- palette and board list -------------------------------------------------

export function paintPalette(catalogue, filter, onPlace) {
  const host = document.getElementById("palette");
  host.replaceChildren();
  const needle = filter.trim().toLowerCase();

  const shown = catalogue.parts.filter(
    (p) => !needle || p.name.toLowerCase().includes(needle),
  );

  for (const part of shown) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `catalogue-row${part.drawable ? "" : " no-art"}`;
    row.title = part.drawable
      ? `${part.category} — click to place`
      : `${part.category} — placeable, but ships no image map`;
    row.innerHTML =
      `<span class="cat-name">${part.name}</span>` +
      `<span class="cat-tag">${part.category}</span>`;
    row.addEventListener("click", () => onPlace(part.name));
    host.append(row);
  }

  if (!shown.length) {
    const empty = document.createElement("p");
    empty.className = "note";
    empty.textContent = "nothing matches";
    host.append(empty);
  }
}

export function paintBoardList(boards, onSwitch) {
  const host = document.getElementById("board-list");
  host.replaceChildren();
  for (const board of boards.boards) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `board-row${board.active ? " active" : ""}`;
    const art = board.art ?? board.name;
    row.title = board.active
      ? "this board is running"
      : `restart the simulator on ${art}`;
    row.innerHTML =
      `<span class="b-name">${art}</span>` +
      `<span class="b-tag">${board.active ? "running" : "switch"}</span>`;
    if (!board.active && onSwitch) {
      row.addEventListener("click", () => onSwitch(board));
    }
    host.append(row);
  }
}

export function paintPins(pins) {
  const body = document.querySelector("#pins tbody");
  body.replaceChildren();
  for (const pin of pins) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="dim">${String(pin.index).padStart(2, "0")}</td>
      <td>${pin.name}</td>
      <td class="dim">${pin.direction}${pin.type}</td>
      <td class="${pin.value ? "on" : "dim"}">${pin.value}</td>`;
    body.append(row);
  }
}
