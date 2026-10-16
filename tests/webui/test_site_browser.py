# OpenHardware - the built site, in a browser, with nothing behind it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""`build/site/` served as plain files and driven in Chromium, per OH-239.

`test_site_pyodide.py` holds the bundle's answers to the native build's under
node. This holds what only a page shows: that `inpage/transport.js` takes the
page's own `fetch` calls to the Worker, that the page's controls drive it --
a sample from the toolbar, a board from an image chosen in the file picker --
and that for a board it has no compiler for, the copy says so before anyone
presses Build. `test_compiler_page.py` holds the boards it does build.

The server here is `http.server`'s file handler and nothing else, so an
`/api/` request answered at all was answered inside the tab: the handler has
no such route and would say 404.

It skips -- by name -- without Playwright, without its Chromium, or without a
build: `python tools/build_site.py`.
"""

from __future__ import annotations

import functools
import http.server
import pathlib
import threading
import tomllib

import pytest

sync_api = pytest.importorskip("playwright.sync_api",
                               reason="Playwright drives the browser here")

REPO = pathlib.Path(__file__).resolve().parents[2]
SITE = REPO / "build" / "site"
TESTS = REPO / "tests"

#: Long, because the first request waits for Pyodide to boot and the cores to
#: compile, which on a slow runner is tens of seconds.
BOOT_MS = 120_000

#: A board the local server builds and this copy has no compiler for: an
#: ESP32's, whose compiler is the last OH-244 brings to the page.
NOT_BUILT_HERE = "XIAO-ESP32-C3-DIP"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@pytest.fixture(scope="module")
def served() -> str:
    """`build/site/` on a loopback port, as files and nothing else, and from
    a folder -- `/site/` -- as GitHub Pages serves it from /OpenHardware/
    (OH-240): a file the page asks for from the root is then a request outside
    the site, which `test_no_request_leaves_the_site` sees."""
    if not (SITE / "index.html").is_file():
        pytest.skip(f"no build at {SITE}: python tools/build_site.py")
    handler = functools.partial(_Quiet, directory=str(SITE.parent))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/{SITE.name}/"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch()
        except sync_api.Error as exc:
            pytest.skip(f"Playwright has no Chromium here: {exc}")
        yield launched
        launched.close()


@pytest.fixture
def tab(browser, served):
    """A fresh page on the site, its runtime started, and every URL it asked
    for: `tab.asked`."""
    context = browser.new_context(viewport={"width": 1400, "height": 1000})
    asked: list[str] = []
    refused: list[str] = []
    context.on("request", lambda request: asked.append(request.url))
    context.on("response", lambda response: response.status >= 400
               and refused.append(f"{response.status} {response.url}"))
    page = context.new_page()
    page.goto(served)
    page.wait_for_function(
        "document.getElementById('inpage-status').textContent.startsWith('Ready')",
        timeout=BOOT_MS)
    page.asked = asked
    page.refused = refused
    yield page
    context.close()


def _load_board(tab, board: str, image: pathlib.Path, base: str) -> None:
    tab.select_option("#board-pick", board)
    tab.set_input_files("#board-file", str(image))
    tab.fill("#board-base", base)
    tab.click("#board-load")
    tab.wait_for_function("!document.getElementById('board-go').disabled")


def test_the_first_sample_sums_one_to_ten_in_the_page(tab):
    tab.select_option("#sample", index=0)
    tab.click("#load")
    tab.wait_for_function(
        "document.getElementById('counter').textContent === '0 steps'")
    tab.click("#run")
    tab.wait_for_function(
        "document.getElementById('status').textContent.includes('halt')",
        timeout=60_000)
    ax = tab.evaluate("""() => [...document.querySelectorAll('#registers .reg')]
        .find((cell) => cell.querySelector('.name').textContent.toLowerCase() === 'ax')
        .querySelector('.value').textContent""")
    assert ax.lower().endswith("0037")


def test_an_uploaded_rp2040_image_prints_on_the_console(tab):
    _load_board(tab, "XIAO-RP2040-DIP",
                TESTS / "cortexm0" / "uart" / "hello.bin", "0x10000100")
    tab.click("#board-go")
    tab.wait_for_function(
        "document.getElementById('board-console').textContent.includes('hello, world')",
        timeout=60_000)


def test_an_uploaded_uno_image_blinks_pin_13(tab):
    """Read through the page's own fetch, so through the transport: PB5 is
    seen both high and low while the page's Run clock drives the board. A
    read before the sketch's pinMode sees it `input`, which is not a blink
    and does not end the wait.

    A read lands between two of the clock's ticks of `TICK_STEPS` (200,000)
    instructions, so PB5 is seen only at those boundaries; replayed through
    `webui/inpage.py` natively, it is high from the first and low from the
    sixth. The wait is long because six ticks took more than a minute on a
    machine busy with other builds, and a slow CI runner is the same case."""
    _load_board(tab, "Arduino Uno", TESTS / "avr" / "blink" / "blink.bin", "0x0")
    tab.click("#board-go")
    seen = tab.evaluate("""async () => {
        const seen = new Set();
        const until = performance.now() + 180000;
        while (!(seen.has('high') && seen.has('low')) && performance.now() < until) {
          const pins = await (await fetch('/api/board/pins')).json();
          seen.add(pins.pads.find((pad) => pad.chip_pin === 'PB5').state);
          await new Promise((settle) => setTimeout(settle, 100));
        }
        return [...seen].sort();
      }""")
    assert {"high", "low"} <= set(seen), seen


def test_a_board_this_copy_cannot_build_has_build_off_and_says_to_use_the_local_server(tab):
    tab.select_option("#board-pick", NOT_BUILT_HERE)
    tab.dispatch_event("#board-pick", "change")
    tab.wait_for_function(
        "document.getElementById('sketch-report').textContent.includes('local server')",
        timeout=BOOT_MS)
    assert tab.is_disabled("#sketch-build")


def test_no_request_leaves_the_site(tab, served):
    tab.select_option("#sample", index=0)
    tab.click("#load")
    tab.wait_for_function(
        "document.getElementById('counter').textContent === '0 steps'")
    assert tab.asked
    assert [url for url in tab.asked if not url.startswith(served)] == []


def test_every_file_the_page_asks_the_site_for_is_there(tab):
    """models/index.json included, which OH-241 writes even when no model
    ships: the page's request for it was a 404 until then."""
    tab.select_option("#sample", index=0)
    tab.click("#load")
    tab.wait_for_function(
        "document.getElementById('counter').textContent === '0 steps'")
    assert any(url.endswith("/models/index.json") for url in tab.asked)
    assert tab.refused == []


def test_the_notice_names_the_release_pyproject_toml_states(tab):
    stated = tomllib.loads((REPO / "pyproject.toml").read_text(
        encoding="utf-8"))["project"]["version"]
    assert (f"This is OpenHardware {stated}, built from "
            in tab.text_content("#inpage-release"))


def test_the_notice_links_the_licences_the_site_is_under(tab):
    with tab.expect_navigation():
        tab.click(".inpage a[href='NOTICE.txt']")
    assert "Mozilla Public License" in tab.text_content("body")
