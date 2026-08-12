// OpenHardware — paint a draw list onto the board image.
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

/** Draw one region's hit area, matching the shape the .map file declared. */
function hitShape(region) {
  if (region.shape === "circle") {
    const [cx, cy] = [
      (region.left + region.right) / 2,
      (region.top + region.bottom) / 2,
    ];
    return element("circle", { cx, cy, r: region.radius, class: "hit" });
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

/** The lit overlay for an active output, sized to the region. */
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

/**
 * Render `model` into the board panel.
 *
 * `onRegionClick(region)` fires only for regions the model marked clickable.
 */
export function paint(model, onRegionClick) {
  const img = document.getElementById("board-img");
  const overlay = document.getElementById("overlay");

  const source = `/board.svg?name=${encodeURIComponent(model.board)}`;
  if (img.getAttribute("src") !== source) {
    img.setAttribute("src", source);
    img.setAttribute("alt", `${model.board} board`);
  }

  overlay.setAttribute("viewBox", `0 0 ${model.width} ${model.height}`);
  overlay.replaceChildren();

  for (const region of model.regions) {
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
        ? `${region.id} — not reported by this board`
        : `${region.id} = ${region.value}`;
    group.append(label);

    if (region.clickable) {
      group.addEventListener("click", () => onRegionClick(region));
    }
    overlay.append(group);
  }
}

/** Fill the region table beside the board. */
export function paintRegionTable(model) {
  const body = document.querySelector("#regions tbody");
  body.replaceChildren();
  for (const region of model.regions) {
    const row = document.createElement("tr");
    const value =
      region.value === null ? "—" : String(region.value);
    row.innerHTML = `
      <td>${region.id}</td>
      <td class="dim">${region.role}</td>
      <td class="${region.active ? "on" : "dim"}">${value}</td>`;
    body.append(row);
  }
}

/** Fill the spare-parts panel. `onInput(part, input)` fires on a pill click. */
export function paintParts(model, onInput) {
  const host = document.getElementById("parts");
  host.replaceChildren();

  if (model.parts.length === 0) {
    const empty = document.createElement("p");
    empty.className = "note";
    empty.style.padding = "0";
    empty.textContent = "no spare parts placed";
    host.append(empty);
    return;
  }

  for (const part of model.parts) {
    const card = document.createElement("div");
    card.className = "part";

    const heading = document.createElement("h3");
    heading.textContent = `part[${String(part.index).padStart(2, "0")}] ${part.name}`;
    card.append(heading);

    const row = document.createElement("div");
    row.className = "io";
    for (const input of part.inputs) {
      const pill = document.createElement("button");
      pill.className = `pill${input.value ? " on" : ""}`;
      pill.type = "button";
      pill.textContent = `${input.name}=${input.value}`;
      pill.addEventListener("click", () => onInput(part, input));
      row.append(pill);
    }
    card.append(row);
    host.append(card);
  }
}

/** Fill the pin table. */
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
