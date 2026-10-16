# OpenHardware - tools/build_site.py, the parts that need no compiler.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""What `tools/build_site.py` writes, checked without building a site.

Building one takes Emscripten and a download; `test_site_pyodide.py` checks
what a build produced. These check the decisions inside it: where the
transport goes in the page, which sources each core is compiled from, what
the bundle carries, and that two builds cannot run into one folder.
"""

from __future__ import annotations

import io
import json
import pathlib
import re
import tarfile
import zipfile

import pytest

from tools import build_core, build_site

EMULATOR_HTML = (build_site.STATIC / "emulator.html").read_text(encoding="utf-8")


def test_the_transport_is_loaded_immediately_before_emulator_js():
    built = build_site.page(EMULATOR_HTML)
    assert (f"{build_site.TRANSPORT_SCRIPT}\n{build_site.EMULATOR_SCRIPT_HERE}"
            in built)
    assert built.count(build_site.TRANSPORT_SCRIPT) == 1


def test_the_built_page_loads_nothing_from_the_servers_root():
    """Pages serves the site from a folder, whose root is another site."""
    built = build_site.page(EMULATOR_HTML)
    assert re.findall(r'(?:src|href)="/[^/"][^"]*"|from "/[^"]*"', built) == []


def test_every_module_a_page_script_imports_from_the_root_is_in_the_import_map():
    """board3d-panel.js imports "/board3d.js" and is not adapted: only the
    import map moves it into the folder. A new import like it needs a row."""
    scripts = "".join((build_site.STATIC / name).read_text(encoding="utf-8")
                      for name in build_site.PAGE_FILES if name.endswith(".js"))
    named = set(re.findall(r'import\(\s*"(/[^"]+)"\s*\)|from\s+"(/[^"]+)"', scripts))
    specifiers = {first or second for first, second in named}
    built = build_site.page(EMULATOR_HTML)
    mapped = json.loads(re.search(r'<script type="importmap">(.*?)</script>',
                                  built, re.S).group(1))["imports"]
    assert specifiers
    assert {name: mapped.get(name) for name in specifiers} == {
        name: f".{name}" for name in specifiers}


def test_the_page_is_otherwise_emulator_html_unchanged():
    built = build_site.page(EMULATOR_HTML)
    for anchor, replacement in reversed(build_site.ADAPTATIONS):
        built = built.replace(replacement, anchor, 1)
    assert built == EMULATOR_HTML


def test_the_build_button_is_disabled_by_the_page_itself():
    """Not by a script: emulator.js greys it only after /api/board/pins
    answers, which it refuses at first load with no board loaded."""
    built = build_site.page(EMULATOR_HTML)
    button = re.search(r'<button id="sketch-build"[^>]*>', built).group(0)
    assert " disabled " in button


def test_the_notice_comes_before_the_toolbar_and_names_the_server():
    built = build_site.page(EMULATOR_HTML)
    assert built.index(build_site.NOTICE) < built.index(build_site.TOOLBAR)
    assert "python webui/emulator_server.py" in build_site.NOTICE


def test_the_notice_has_the_element_the_transport_reports_progress_into():
    transport = (build_site.STATIC / "inpage" / "transport.js").read_text(
        encoding="utf-8")
    written = re.search(r'getElementById\("([^"]+)"\)', transport).group(1)
    assert f'id="{written}"' in build_site.page(EMULATOR_HTML)


def test_every_file_the_adaptations_load_is_shipped():
    """A relative href, src, import or import-map target page() writes is a
    file the site must carry."""
    written = "".join(new for _, new in build_site.ADAPTATIONS)
    added = (re.findall(r'(?:href|src)="([^"/][^"]*)"', written)
             + re.findall(r'"\./([^"]+)"', written))
    assert {"inpage/inpage.css", "inpage/transport.js", "board3d.js",
            "vendor/three.module.js", "clock.js"} <= set(added)
    assert sorted(set(added) - set(build_site.PAGE_FILES)) == []


def test_a_page_missing_any_anchor_is_refused_by_name():
    for anchor, _ in build_site.ADAPTATIONS:
        html = EMULATOR_HTML.replace(anchor, "")
        with pytest.raises(build_site.SiteError, match=re.escape(f"{anchor!r} 0 times")):
            build_site.page(html)


def test_a_page_without_emulator_js_is_refused_by_name():
    html = EMULATOR_HTML.replace(build_site.EMULATOR_SCRIPT, "")
    with pytest.raises(build_site.SiteError, match="emulator.js.*0 times"):
        build_site.page(html)


def test_a_page_loading_emulator_js_twice_is_refused():
    html = EMULATOR_HTML + build_site.EMULATOR_SCRIPT
    with pytest.raises(build_site.SiteError, match="2 times"):
        build_site.page(html)


def test_each_core_is_compiled_from_every_cc_file_beside_its_cmakelists():
    """The browser's core is the native one, file for file: every `.cc` in
    the core's directory is named by its CMakeLists.txt, and nothing else."""
    for core in build_core.cores():
        named = {path.name for path in build_site.core_sources(core)}
        present = {path.name for path in (build_core.CORE_DIR / core).glob("*.cc")}
        assert named == present, core


def test_a_cmakelists_naming_a_missing_source_is_refused(tmp_path, monkeypatch):
    (tmp_path / "toy").mkdir()
    (tmp_path / "toy" / "CMakeLists.txt").write_text(
        "add_library(toy SHARED\n  here.cc\n  gone.cc\n)\n", encoding="utf-8")
    (tmp_path / "toy" / "here.cc").write_text("", encoding="utf-8")
    monkeypatch.setattr(build_core, "CORE_DIR", tmp_path)
    with pytest.raises(build_site.SiteError, match="gone.cc"):
        build_site.core_sources("toy")


def test_every_bundle_pattern_matches_something():
    """A pattern matching nothing is a module that moved and was left behind."""
    for pattern in build_site.BUNDLE:
        assert any(build_site.REPO.glob(pattern)), pattern


def test_the_bundle_carries_no_compiled_python_and_no_page_files():
    names = {path.relative_to(build_site.REPO).as_posix()
             for path in build_site.bundle_files()}
    assert not [name for name in names
                if "__pycache__" in name or name.startswith("webui/static/")]
    assert "webui/inpage.py" in names


def test_the_cores_go_where_build_core_looks_for_them(tmp_path):
    core = tmp_path / "libtoy.so"
    core.write_bytes(b"\0asm")
    zipped = build_site.bundle([core], tmp_path)
    with zipfile.ZipFile(zipped) as archive:
        assert archive.read("build/lib/libtoy.so") == b"\0asm"
    assert build_core.LIB_NAME_PATTERNS["Emscripten"].format("toy") == "libtoy.so"


def test_the_bundle_records_no_build_time(tmp_path):
    """So one tree always zips to one sha256: a timestamp is the only thing
    in a zip that would differ between two builds of the same checkout."""
    core = tmp_path / "libtoy.so"
    core.write_bytes(b"wasm")
    with zipfile.ZipFile(build_site.bundle([core], tmp_path)) as archive:
        stamps = {info.date_time for info in archive.infolist()}
    assert stamps == {build_site.ZIP_EPOCH}


def test_a_second_build_is_refused_while_one_holds_the_lock(tmp_path):
    lock = tmp_path / "site.lock"
    lock.write_text("pid 1234 since then\n", encoding="utf-8")
    with pytest.raises(build_site.SiteError, match="pid 1234.*one build at a time"):
        build_site.build(site=tmp_path / "site", lock=lock)
    assert not (tmp_path / "site").exists()
    assert not (tmp_path / "site.partial").exists()


def test_the_lock_is_released_when_a_build_fails(tmp_path, monkeypatch):
    def fail(site: pathlib.Path) -> dict[str, int]:
        raise build_site.SiteError("deliberately")

    monkeypatch.setattr(build_site, "_write_site", fail)
    lock = tmp_path / "site.lock"
    with pytest.raises(build_site.SiteError, match="deliberately"):
        build_site.build(site=tmp_path / "site", lock=lock)
    assert not lock.exists()


def _release(tmp_path: pathlib.Path, platform: str) -> pathlib.Path:
    """A stand-in Pyodide release: each runtime file, and a lock naming
    `platform` as the one its main module was linked for."""
    tarball = tmp_path / "pyodide-core.tar.bz2"
    with tarfile.open(tarball, "w:bz2") as archive:
        for name in build_site.PYODIDE_RUNTIME:
            data = (json.dumps({"info": {"platform": platform}}).encode()
                    if name == "pyodide-lock.json" else name.encode())
            info = tarfile.TarInfo(f"pyodide/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return tarball


def test_the_runtime_is_shipped_under_names_any_server_types_as_javascript(
        tmp_path, monkeypatch):
    wanted = "emscripten_" + build_site.EMSCRIPTEN_VERSION.replace(".", "_")
    monkeypatch.setattr(build_site, "fetch_pinned",
                        lambda pin: _release(tmp_path, wanted))
    written = build_site.pyodide_runtime(tmp_path / "pyodide")
    assert sorted(path.name for path in written) == sorted(
        ["pyodide.mjs.js", "pyodide.asm.mjs.js", "pyodide.asm.wasm",
         "python_stdlib.zip", "pyodide-lock.json"])
    assert (tmp_path / "pyodide" / "pyodide.mjs.js").read_bytes() == b"pyodide.mjs"


def test_a_pyodide_built_by_another_emscripten_is_refused(tmp_path, monkeypatch):
    """Its main module would not link the cores this builds."""
    monkeypatch.setattr(build_site, "fetch_pinned",
                        lambda pin: _release(tmp_path, "emscripten_4_0_9"))
    with pytest.raises(build_site.SiteError, match="emscripten_4_0_9"):
        build_site.pyodide_runtime(tmp_path / "pyodide")
