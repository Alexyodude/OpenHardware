# OpenHardware - the built site's Python, run where the browser runs it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The bundle in `build/site/`, booted alone under node's Pyodide, answers as
CPython with the native cores does.

`test_inpage.py` holds `InPage` to the loopback server on this machine's
CPython and native cores. This holds the other half of the claim: the files
`tools/build_site.py` ships -- Pyodide's runtime, `openhardware.zip`, the
cores compiled to wasm -- give the same answers to the same requests. So it
proves three things a page would otherwise find out first:

* `BUNDLE` carries every module and data file the routes need (the
  interpreter sees nothing else: no checkout is mounted);
* each core's side module loads through its unchanged `core/*/abi.py`, ABI
  version and struct sizes included;
* the wasm build of each core computes what the native one does.

## Why node, and why it skips

Pyodide runs under node with the same runtime files a browser loads, which is
what lets this be a test rather than a screenshot. It skips -- by name, never
quietly -- without node or without a build: `python tools/build_site.py`.
"""

from __future__ import annotations

import base64
import json
import pathlib
import shutil
import subprocess

import pytest

from core.i8086 import abi
from webui import emulator, inpage

REPO = pathlib.Path(__file__).resolve().parents[2]
SITE = REPO / "build" / "site"
TESTS = REPO / "tests"

#: Every sample, then the two boards the page is checked on: a Cortex-M0+
#: printing over its UART, and the Uno running blink on the AVR core.
REQUESTS = [
    request
    for sample in emulator.SAMPLES
    for request in (
        ("POST", "/api/load", json.dumps({"hex": sample.hex})),
        ("POST", "/api/run", json.dumps({"steps": 100_000})),
        ("GET", "/api/state?at=0x100&len=64", ""),
    )
] + [
    ("GET", "/api/samples", ""),
    ("POST", "/api/board/load", json.dumps({
        "board": "XIAO-RP2040-DIP", "base": "0x10000100",
        "image": base64.b64encode(
            (TESTS / "cortexm0" / "uart" / "hello.bin").read_bytes()).decode()})),
    ("POST", "/api/board/run", json.dumps({"steps": 20_000})),
    ("GET", "/api/board/state?at=0x20000000&len=32", ""),
    ("POST", "/api/board/load", json.dumps({
        "board": "Arduino Uno", "base": "0x0",
        "image": base64.b64encode(
            (TESTS / "avr" / "blink" / "blink.bin").read_bytes()).decode()})),
    ("POST", "/api/board/run", json.dumps({"steps": 200_000})),
    ("GET", "/api/board/state", ""),
    ("GET", "/api/board/pins", ""),
]

#: Boots the built site's runtime and bundle, answers REQUESTS (read from the
#: file named by argv[2]) and prints [[status, body], ...] as JSON.
NODE_SCRIPT = """
import fs from "node:fs";
import { pathToFileURL } from "node:url";
const site = process.argv[2];
const requests = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const { loadPyodide } = await import(pathToFileURL(`${site}/pyodide/pyodide.mjs.js`).href);
const { default: createPyodideModule } =
  await import(pathToFileURL(`${site}/pyodide/pyodide.asm.mjs.js`).href);
const pyodide = await loadPyodide({ indexURL: `${site}/pyodide/`, createPyodideModule });
const home = "/home/pyodide/openhardware";
// A Uint8Array, as a browser's fetch hands the worker: Pyodide refuses a Buffer.
const zipped = new Uint8Array(fs.readFileSync(`${site}/openhardware.zip`));
pyodide.unpackArchive(zipped, "zip", { extractDir: home });
pyodide.runPython(`import sys; sys.path.insert(0, "${home}")`);
const page = pyodide.pyimport("webui.inpage").InPage();
const answers = requests.map(([verb, target, body]) => {
  const answered = page.answer(verb, target, body);
  const pair = answered.toJs();
  answered.destroy();
  return pair;
});
process.stdout.write(JSON.stringify(answers));
"""


@pytest.fixture(scope="module")
def under_pyodide(tmp_path_factory) -> list[tuple[int, object]]:
    """REQUESTS answered by the built site under node, decoded."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; the built site's runtime needs one")
    if not (SITE / "openhardware.zip").is_file():
        pytest.skip(f"no build at {SITE}: python tools/build_site.py")
    scratch = tmp_path_factory.mktemp("site_pyodide")
    script = scratch / "boot.mjs"
    script.write_text(NODE_SCRIPT, encoding="utf-8")
    asked = scratch / "requests.json"
    asked.write_text(json.dumps(REQUESTS), encoding="utf-8")
    done = subprocess.run([node, str(script), SITE.as_posix(), str(asked)],
                          capture_output=True, text=True, timeout=300,
                          check=False)
    if done.returncode != 0:
        raise AssertionError(f"node exited {done.returncode}\n{done.stderr[-4000:]}")
    return [(status, json.loads(body)) for status, body in json.loads(done.stdout)]


@pytest.fixture(scope="module")
def natively() -> list[tuple[int, object]]:
    """REQUESTS answered by this checkout's CPython and native cores."""
    try:
        abi.load()
    except abi.AbiError as exc:
        pytest.skip(f"i8086 core unavailable: {exc}")
    page = inpage.InPage()
    return [(status, json.loads(body))
            for status, body in (page.answer(*request) for request in REQUESTS)]


def test_the_built_site_answers_every_request_as_the_native_build_does(
        under_pyodide, natively):
    for request, got, expected in zip(REQUESTS, under_pyodide, natively):
        assert got == expected, f"{request[0]} {request[1]}"
    assert len(under_pyodide) == len(REQUESTS)


def test_the_first_sample_sums_one_to_ten_in_the_built_site(under_pyodide):
    """A guard on the test above: two builds that agreed on a failure would
    pass it, so one answer is checked against the program's own arithmetic."""
    status, state = under_pyodide[2]
    assert (status, state["registers"]["ax"]) == (200, 55)


def test_the_rp2040_prints_over_its_uart_in_the_built_site(under_pyodide):
    index = REQUESTS.index(("GET", "/api/board/state?at=0x20000000&len=32", ""))
    status, state = under_pyodide[index]
    assert (status, state["uart"]["text"]) == (200, "hello, world\n")
