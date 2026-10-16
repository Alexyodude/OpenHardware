# OpenHardware - Build and run in the static build's page, compiled in the tab.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""`build/site/` served as plain files and driven in Chromium, per OH-244.

`test_compile_wasm.py` holds the bundle's images to the server's under node.
This holds what only the page shows: that Build and run, pressed in a tab with
nothing behind it, compiles the sketch there and runs it on the board -- PB5's
period follows Blink's delay -- that a sketch that does not compile is
reported on its own line and leaves the board as it was, that the compiler is
fetched only when Build is pressed and read from the cache after, and that no
request leaves the site.

The server here is `http.server`'s file handler: it has no `/api/` route and
no compiler, so a build answered at all was answered inside the tab.

**One session, many assertions.** The first build fetches the whole compiler,
which is the slow part, so the module drives the page through every step once
in `session` and each test reads one thing it saw.

It skips -- by name -- without Playwright, without its Chromium, or without the
site: `python tools/build_site.py`, which builds the compiler into it.
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import json
import pathlib
import threading
import time

import pytest

sync_api = pytest.importorskip("playwright.sync_api",
                               reason="Playwright drives the browser here")

from webui.boards.atmega328p import F_CPU_HZ  # noqa: E402
from webui.compile import MAX_SOURCE_BYTES  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
SITE = REPO / "build" / "site"

BOARD = "Arduino Uno"
#: A board the server builds and this copy does not: its compiler is SAMD21's.
OTHER_BOARD = "XIAO-SAMD21-DIP"

#: Long, because the first request waits for Pyodide to boot and the cores to
#: compile, as tests/webui/test_site_browser.py's BOOT_MS says.
BOOT_MS = 120_000
#: The first build fetches the compiler, 21 MB, and compiles it.
BUILD_MS = 300_000
#: Long enough for every compiler file the page asked for to have arrived,
#: had nothing stopped it: a whole first fetch takes seconds on loopback.
SETTLE_MS = 30_000

READY = "document.getElementById('inpage-status').textContent.startsWith('Ready')"
BUILT = "document.getElementById('sketch-report').textContent.includes('bytes on')"
FAILED = "document.getElementById('sketch-report').textContent.includes('Did not compile')"
#: A build that ended either way: built, or the compiler in this tab failed --
#: so that a test expecting the first shows the second's words, not a timeout.
ENDED = f"{BUILT} || document.getElementById('sketch-report').textContent.includes('failed')"

#: As many instructions as `/api/board/run` takes at once (MAX_RUN_STEPS).
RUN_STEPS = 200_000

#: The instructions retired at each of PB5's first three changes after a load,
#: read by running RUN_STEPS at a time: so each is late by less than RUN_STEPS.
#: The Uno's label for PB5 is "13".
TOGGLES = f"""async () => {{
  const seen = [];
  let last = null;
  const until = performance.now() + 120000;
  while (seen.length < 3 && performance.now() < until) {{
    await fetch('/api/board/run', {{method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{steps: {RUN_STEPS}}})}});
    const state = await (await fetch('/api/board/state')).json();
    const level = state.pins['13'];
    if (last !== null && level !== last) seen.push(state.retired);
    last = level;
  }}
  return seen;
}}"""

STATE = "async () => (await fetch('/api/board/state')).json()"

#: Line 2's `int x = ;`, which gcc reports at its 23rd column.
SYNTAX_ERROR = "void setup() { pinMode(13, OUTPUT); }\nvoid loop() { int x = ; }\n"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


class _Server(http.server.ThreadingHTTPServer):
    # The page asks for its files many at a time; at socketserver's default of
    # five, a Windows client refused at a full queue retries after seconds.
    request_queue_size = 64


@pytest.fixture(scope="module")
def served() -> str:
    """The site on a loopback port, as files and nothing else, from a folder
    as GitHub Pages serves it (OH-240)."""
    if not (SITE / "compiler" / "manifest.json").is_file():
        pytest.skip(f"no site with a compiler at {SITE}: python tools/build_site.py")
    server = _Server(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(SITE.parent)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/{SITE.name}/"
    server.shutdown()
    server.server_close()


#: Headless Chromium draws WebGL in software unless told it may use the GPU,
#: and the page's 3D view then starves the tab: the first build took 83 s that
#: way and 9 s with this, on the same machine. Where there is no GPU it falls
#: back to software, and BUILD_MS allows for that.
LAUNCH_ARGS = ["--enable-gpu"]


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch(args=LAUNCH_ARGS)
        except sync_api.Error as exc:
            pytest.skip(f"Playwright has no Chromium here: {exc}")
        yield launched
        launched.close()


def _pick(page, board: str) -> None:
    page.select_option("#board-pick", board)
    page.dispatch_event("#board-pick", "change")


def _build(page, source: str, until: str) -> None:
    page.fill("#sketch-source", source)
    page.click("#sketch-build")
    page.wait_for_function(until, timeout=BUILD_MS)


@pytest.fixture(scope="module")
def session(browser, served) -> dict[str, object]:
    """Everything one visit sees, by step: each request the page made, under
    the step that made it, and what the page and the board said after it."""
    context = browser.new_context(viewport={"width": 1400, "height": 1000})
    step = ["boot"]
    # Every step has a list, so a step that asked for nothing reads as [] and
    # not as a missing key.
    asked: dict[str, list[str]] = {name: [] for name in (
        "boot", "first build", "second build", "failed build", "reload", "build after reload")}
    context.on("request", lambda request: asked[step[0]].append(request.url))
    page = context.new_page()
    seen: dict[str, object] = {"asked": asked}

    page.goto(served)
    page.wait_for_function(READY, timeout=BOOT_MS)
    _pick(page, BOARD)
    seen["blink"] = page.input_value("#sketch-source")
    seen["ready_report"] = page.text_content("#sketch-report")

    step[0] = "first build"
    _build(page, seen["blink"], BUILT)  # type: ignore[arg-type]
    seen["built_report"] = page.text_content("#sketch-report")
    seen["toggles_500"] = page.evaluate(TOGGLES)

    step[0] = "second build"
    _build(page, seen["blink"].replace("delay(500)", "delay(250)"), BUILT)  # type: ignore[union-attr]
    seen["toggles_250"] = page.evaluate(TOGGLES)

    seen["state_before_failure"] = page.evaluate(STATE)
    step[0] = "failed build"
    _build(page, SYNTAX_ERROR, FAILED)
    seen["state_after_failure"] = page.evaluate(STATE)
    seen["errors"] = page.text_content("#sketch-errors")
    seen["error_at"] = page.eval_on_selector_all(
        "#sketch-errors .diagnostic-at", "found => found.map(at => at.textContent)")

    _pick(page, OTHER_BOARD)
    seen["other_disabled"] = page.is_disabled("#sketch-build")
    seen["other_title"] = page.get_attribute("#sketch-build", "title")
    seen["other_report"] = page.text_content("#sketch-report")

    step[0] = "reload"
    page.reload()
    page.wait_for_function(READY, timeout=BOOT_MS)
    _pick(page, BOARD)
    step[0] = "build after reload"
    _build(page, seen["blink"], BUILT)  # type: ignore[arg-type]
    context.close()
    return seen


def _half_period(toggles: list[int]) -> int:
    """Instructions between PB5's second and third changes: one delay, and the
    digitalWrite after it."""
    assert len(toggles) == 3, (f"PB5 changed {len(toggles)} times within TOGGLES' two "
                               f"minutes, after {toggles} instructions; three are needed")
    return toggles[2] - toggles[1]


def test_the_uno_says_it_builds_in_this_tab_before_anything_is_fetched(session):
    assert session["ready_report"] == "Builds in this tab. The first build fetches the compiler, once."


def test_nothing_of_the_compiler_but_its_board_list_is_fetched_before_build(session, served):
    assert [url for url in session["asked"]["boot"] if "/compiler/" in url] == [
        f"{served}compiler/boards.json"]


def test_blink_builds_and_loads_on_the_uno_in_the_tab(session):
    assert session["built_report"].endswith("bytes on Arduino Uno, entered at 0x00000000. Press Run.")


def test_blink_toggles_pb5_every_500_ms_of_the_uno_s_clock(session):
    assert abs(_half_period(session["toggles_500"]) - F_CPU_HZ // 2) < RUN_STEPS


def test_editing_blink_s_delay_to_250_halves_pb5_s_period(session):
    assert abs(_half_period(session["toggles_250"]) - F_CPU_HZ // 4) < RUN_STEPS


def test_the_second_build_fetches_nothing_more_of_the_compiler(session):
    assert [url for url in session["asked"]["second build"] if "/compiler/" in url] == []


def test_a_reloaded_page_reads_the_compiler_from_the_cache(session):
    assert [url for url in session["asked"]["build after reload"] if "/compiler/avr/" in url] == []


def test_a_syntax_error_is_reported_on_its_line(session):
    assert session["error_at"] == ["sketch.cpp:2:23:"]


def test_a_syntax_error_quotes_the_line_it_is_on(session):
    assert "    void loop() { int x = ; }\n" in session["errors"]


def test_a_failed_build_leaves_the_board_as_it_was(session):
    assert session["state_after_failure"] == session["state_before_failure"]


def test_a_board_this_copy_cannot_build_has_build_disabled(session):
    assert session["other_disabled"] is True


def test_a_board_this_copy_cannot_build_says_to_build_it_with_the_local_server(session):
    assert "python webui/emulator_server.py" in session["other_title"]


def test_a_board_this_copy_cannot_build_says_so_beside_the_button(session):
    assert session["other_report"] == session["other_title"]


def test_no_request_leaves_the_site(session, served):
    origin = served.split(f"/{SITE.name}/")[0]
    everything = [url for urls in session["asked"].values() for url in urls]
    assert everything
    assert [url for url in everything
            if not url.startswith((served, f"blob:{origin}/"))] == []


# --- what the Worker does when something is wrong -----------------------------
#
# Each in a context of its own, so its Cache Storage starts empty, and with
# its routes in place before the page asks for anything.


@pytest.fixture
def fresh(browser):
    """A new context and a page in it, not yet navigated, every URL it asks
    for, `page.asked`, and every URL whose request has finished or failed,
    `page.settled`."""
    context = browser.new_context(viewport={"width": 1400, "height": 1000})
    asked: list[str] = []
    settled: list[str] = []
    context.on("request", lambda request: asked.append(request.url))
    context.on("requestfinished", lambda request: settled.append(request.url))
    context.on("requestfailed", lambda request: settled.append(request.url))
    page = context.new_page()
    page.asked = asked
    page.settled = settled
    yield page
    context.close()


def _open(page, served: str) -> None:
    page.goto(served)
    page.wait_for_function(READY, timeout=BOOT_MS)
    _pick(page, BOARD)


def _press(page, until: str) -> str:
    page.click("#sketch-build")
    page.wait_for_function(until, timeout=BUILD_MS)
    return page.text_content("#sketch-report")


def _manifest() -> dict:
    return json.loads((SITE / "compiler" / "manifest.json").read_text(encoding="utf-8"))


def _when_the_compiler_fetches_settle(page) -> None:
    """Back once every compiler file the page asked for has arrived or been
    abandoned -- or after SETTLE_MS, for a browser that reports neither for a
    request it dropped -- and a second later, for what arrived to be said."""
    deadline = time.monotonic() + SETTLE_MS / 1000
    while time.monotonic() < deadline and sorted(
            url for url in page.asked if "/compiler/avr/" in url) != sorted(
            url for url in page.settled if "/compiler/avr/" in url):
        page.wait_for_timeout(250)
    page.wait_for_timeout(1000)


def _serve_plan(page, change) -> None:
    """plan.json as `change` leaves it, with manifest.json's record of it
    changed to match, so it passes the check that it is the plan the manifest
    names and reaches build.js."""
    plan = json.loads((SITE / "compiler" / "plan.json").read_text(encoding="utf-8"))
    change(plan)
    body = json.dumps(plan).encode()
    manifest = _manifest()
    manifest["files"]["plan.json"] = [len(body), hashlib.sha256(body).hexdigest()]
    page.context.route("**/compiler/plan.json", lambda route: route.fulfill(
        body=body, content_type="application/json"))
    page.context.route("**/compiler/manifest.json", lambda route: route.fulfill(
        body=json.dumps(manifest), content_type="application/json"))


def test_a_compiler_file_altered_on_the_way_is_refused_naming_both_hashes(fresh, served):
    path = "avr/tools/avr-as.mjs"
    altered = (SITE / "compiler" / path).read_bytes() + b"//"
    fresh.context.route(f"**/compiler/{path}", lambda route: route.fulfill(
        body=altered, content_type="text/javascript"))
    size, digest = _manifest()["files"][path]
    _open(fresh, served)
    assert _press(fresh, "document.getElementById('sketch-report').textContent.includes('sha256')") == (
        f"the compiler in this tab failed: compiler/{path}: expected {size} bytes with sha256 "
        f"{digest}, got {len(altered)} with {hashlib.sha256(altered).hexdigest()}")


def test_a_failed_fetch_s_error_stays_beside_the_button_while_the_other_fetches_end(
        fresh, served):
    path = "avr/tools/avr-as.mjs"
    altered = (SITE / "compiler" / path).read_bytes() + b"//"
    fresh.context.route(f"**/compiler/{path}", lambda route: route.fulfill(
        body=altered, content_type="text/javascript"))
    _open(fresh, served)
    said = _press(fresh, "document.getElementById('sketch-report').textContent.includes('sha256')")
    _when_the_compiler_fetches_settle(fresh)
    assert fresh.text_content("#sketch-report") == said


def test_a_failed_manifest_fetch_is_tried_again_on_the_next_press(fresh, served):
    fresh.context.route("**/compiler/manifest.json",
                        lambda route: route.fulfill(status=503, body="busy"), times=1)
    _open(fresh, served)
    _press(fresh, "document.getElementById('sketch-report').textContent.includes('HTTP 503')")
    assert _press(fresh, BUILT).endswith("bytes on Arduino Uno, entered at 0x00000000. Press Run.")


def test_a_plan_from_another_build_than_the_manifest_is_refused(fresh, served):
    other = (SITE / "compiler" / "plan.json").read_bytes() + b"\n"
    fresh.context.route("**/compiler/plan.json", lambda route: route.fulfill(
        body=other, content_type="application/json"))
    _open(fresh, served)
    assert "compiler/plan.json is not the one manifest.json" in _press(
        fresh, "document.getElementById('sketch-report').textContent.includes('different builds')")


def test_a_plan_of_another_format_is_refused_before_its_shape_is_read(fresh, served):
    # A new format is a new shape: here, one with no `chips` at all.
    _serve_plan(fresh, lambda plan: (plan.update(format=99), plan.pop("chips")))
    _open(fresh, served)
    assert "plan.json is format 99 and this build.js reads format 1" in _press(
        fresh, "document.getElementById('sketch-report').textContent.includes('format 99')")


def test_a_manifest_of_another_format_is_refused_before_its_shape_is_read(fresh, served):
    manifest = {**_manifest(), "format": 99}
    del manifest["files"]
    fresh.context.route("**/compiler/manifest.json", lambda route: route.fulfill(
        body=json.dumps(manifest), content_type="application/json"))
    _open(fresh, served)
    assert "manifest.json is format 99 and this build.js reads format 1" in _press(
        fresh, "document.getElementById('sketch-report').textContent.includes('format 99')")


def test_a_build_past_its_time_budget_fails_in_the_servers_words(fresh, served):
    _serve_plan(fresh, lambda plan: plan.update(budget_seconds=0))
    _open(fresh, served)
    _press(fresh, FAILED)
    assert "the build ran out of its 0 s budget while running cc1plus" in fresh.text_content(
        "#sketch-errors")


def test_after_a_build_runs_out_of_time_the_next_press_builds_in_a_new_compiler(fresh, served):
    # The compiler that ran out holds the plan with no time in it; only a new
    # one, which asks for the plan again, can build.
    _serve_plan(fresh, lambda plan: plan.update(budget_seconds=0))
    _open(fresh, served)
    _press(fresh, FAILED)
    fresh.context.unroute("**/compiler/plan.json")
    fresh.context.unroute("**/compiler/manifest.json")
    assert _press(fresh, BUILT).endswith("bytes on Arduino Uno, entered at 0x00000000. Press Run.")


def test_a_sketch_over_the_size_limit_is_refused_before_the_compiler_is_fetched(fresh, served):
    _open(fresh, served)
    fresh.fill("#sketch-source", "//" + "x" * MAX_SOURCE_BYTES)
    _press(fresh, "document.getElementById('sketch-report').textContent.includes('over the')")
    assert [url for url in fresh.asked if "/compiler/avr/" in url] == []


def test_a_cached_compiler_file_that_was_altered_is_fetched_again(fresh, served):
    path = "avr/tools/avr-as.mjs"
    _open(fresh, served)
    _press(fresh, BUILT)
    fresh.evaluate("""async (url) => {
      const name = (await caches.keys()).find((key) => key.startsWith('openhardware-compiler:'));
      await (await caches.open(name)).put(url, new Response('// not the assembler'));
    }""", f"{served}compiler/{path}")
    _open(fresh, served)
    del fresh.asked[:]
    _press(fresh, BUILT)
    assert [url for url in fresh.asked if "/compiler/avr/" in url] == [f"{served}compiler/{path}"]


def test_a_rebuilt_bundle_deletes_its_own_older_cache_and_no_other_site_s(fresh, served):
    folder = served.split("://", 1)[1].split("/", 1)[1]
    ours = f"openhardware-compiler:/{folder}compiler/@"
    theirs = "openhardware-compiler:/another-site/compiler/@0123456789abcdef"
    _open(fresh, served)
    fresh.evaluate("""async (names) => {
      for (const name of names) await (await caches.open(name)).put('/x', new Response('x'));
    }""", [f"{ours}0123456789abcdef", theirs])
    _press(fresh, BUILT)
    assert sorted(fresh.evaluate("caches.keys()")) == sorted(
        [f"{ours}{_manifest()['version']}", theirs])


def test_a_tab_whose_cache_storage_refuses_to_open_still_builds(fresh, served):
    refuses = ("CacheStorage.prototype.open = () => "
               "Promise.reject(new DOMException('refused by the test', 'SecurityError'));\n")
    worker = refuses + (SITE / "compiler" / "worker.js").read_text(encoding="utf-8")
    fresh.context.route("**/compiler/worker.js", lambda route: route.fulfill(
        body=worker, content_type="text/javascript"))
    _open(fresh, served)
    assert "bytes on" in _press(fresh, ENDED)


def test_a_tab_whose_cache_storage_fails_every_lookup_still_builds(fresh, served):
    fails = ("Cache.prototype.match = () => "
             "Promise.reject(new DOMException('refused by the test', 'UnknownError'));\n")
    worker = fails + (SITE / "compiler" / "worker.js").read_text(encoding="utf-8")
    fresh.context.route("**/compiler/worker.js", lambda route: route.fulfill(
        body=worker, content_type="text/javascript"))
    _open(fresh, served)
    assert "bytes on" in _press(fresh, ENDED)


def test_a_tab_whose_cache_storage_keeps_nothing_still_builds(fresh, served):
    full = ("Cache.prototype.put = () => "
            "Promise.reject(new DOMException('refused by the test', 'QuotaExceededError'));\n")
    worker = full + (SITE / "compiler" / "worker.js").read_text(encoding="utf-8")
    fresh.context.route("**/compiler/worker.js", lambda route: route.fulfill(
        body=worker, content_type="text/javascript"))
    _open(fresh, served)
    assert "bytes on" in _press(fresh, ENDED)


def test_a_page_served_over_plain_http_from_another_host_has_build_off_and_says_why(
        fresh, served):
    # Every request to the made-up host is answered from the loopback server,
    # so the page is the same files at an origin that is not a secure context.
    loopback = served.split(f"/{SITE.name}/")[0]
    elsewhere = "http://openhardware.test"
    fresh.context.route(f"{elsewhere}/**", lambda route: route.fulfill(
        response=route.fetch(url=route.request.url.replace(elsewhere, loopback))))
    _open(fresh, served.replace(loopback, elsewhere))
    reason = ("building in this tab needs the page served over https or from localhost, "
              f"and this one is {elsewhere}")
    assert (fresh.is_disabled("#sketch-build"), fresh.get_attribute("#sketch-build", "title"),
            fresh.text_content("#sketch-report")) == (True, reason, reason)
