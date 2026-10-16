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

import hashlib
import io
import json
import pathlib
import re
import subprocess
import tarfile
import tomllib
import zipfile

import pytest

from tools import build_core, build_site

EMULATOR_HTML = (build_site.STATIC / "emulator.html").read_text(encoding="utf-8")


def test_the_transport_then_the_compiler_are_loaded_immediately_before_emulator_js():
    built = build_site.page(EMULATOR_HTML)
    assert (f"{build_site.TRANSPORT_SCRIPT}\n{build_site.COMPILE_SCRIPT}\n"
            f"{build_site.EMULATOR_SCRIPT_HERE}" in built)
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
    assert {"inpage/inpage.css", "inpage/transport.js", "inpage/compile.js", "board3d.js",
            "vendor/three.module.js", "clock.js", "NOTICE.txt",
            "compiler/NOTICE.txt"} <= set(added)
    # The two NOTICE.txt files are the ones the build writes rather than copies.
    assert sorted(set(added) - {*build_site.PAGE_FILES, "NOTICE.txt",
                                "compiler/NOTICE.txt"}) == []


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


def test_two_pinned_files_with_one_name_are_cached_apart(tmp_path, monkeypatch):
    """Four of the site's licence texts are each called LICENSE."""
    monkeypatch.setattr(build_site, "CACHE", tmp_path)
    first, second = b"MIT License, one\n", b"MIT License, two\n"
    pins = [build_site.Pinned(f"https://example.com/{who}/LICENSE",
                              hashlib.sha256(text).hexdigest(), len(text))
            for who, text in (("a", first), ("b", second))]
    for pin, text in zip(pins, (first, second)):
        (tmp_path / f"{pin.sha256[:12]}-LICENSE").write_bytes(text)
    assert [build_site.fetch_pinned(pin).read_bytes() for pin in pins] == [first, second]


#: A machine's models/ as the composer leaves it: a board that ships, one
#: that is withheld, and a KiCad part.
UNO = {"file": "/models/Arduino-Uno.glb", "source": "Arduino's own EAGLE board file"}
RP2040 = {"file": "/models/RP2040.glb", "source": "https://files.seeedstudio.com/"}
KB2040 = {"file": "/models/Adafruit-KB2040.glb", "source": "Adafruit's own board file"}
LED = {"file": "/models/parts/LED_D3_0mm.glb",
       "source": f"{build_site.site_licences.KICAD_PACKAGES3D}-/raw/master/x.step"}


def _models(root: pathlib.Path, boards: dict[str, dict]) -> pathlib.Path:
    (root / "parts").mkdir(parents=True)
    for entry in [*boards.values(), LED]:
        (root / entry["file"].removeprefix("/models/")).write_bytes(b"glTF")
    (root / "index.json").write_text(json.dumps({
        "units": "mm", "boards": boards,
        "parts": {"source": "KiCad", "libraries": {"LED_THT": [LED]}}}), encoding="utf-8")
    return root


def test_with_no_models_built_the_site_still_answers_for_the_index(tmp_path):
    build_site.models(tmp_path / "out", source=tmp_path / "none")
    assert json.loads((tmp_path / "out" / "index.json").read_text()) == build_site.NO_MODELS
    assert (tmp_path / "out" / "NOTICE.txt").is_file()
    assert list((tmp_path / "out").rglob("*.glb")) == []


def test_a_withheld_model_is_neither_copied_nor_indexed(tmp_path):
    source = _models(tmp_path / "models", {"Arduino Uno": UNO, "XIAO-RP2040-DIP": RP2040})
    build_site.models(tmp_path / "out", source=source)
    copied = sorted(path.relative_to(tmp_path / "out").as_posix()
                    for path in (tmp_path / "out").rglob("*.glb"))
    assert copied == ["Arduino-Uno.glb", "parts/LED_D3_0mm.glb"]
    index = json.loads((tmp_path / "out" / "index.json").read_text())
    assert list(index["boards"]) == ["Arduino Uno"]


def test_a_model_drawing_an_mit_work_ships_with_its_text_whole(tmp_path, monkeypatch):
    source = _models(tmp_path / "models", {"Adafruit KB2040": KB2040})
    mit = "MIT License\n\nCopyright (c) 2016 Adafruit Industries\n"
    fetched = tmp_path / "fetched"
    fetched.write_text(mit, encoding="utf-8")
    monkeypatch.setattr(build_site, "fetch_pinned", lambda pin: fetched)
    build_site.models(tmp_path / "out", source=source)
    assert mit in (tmp_path / "out" / "NOTICE.txt").read_text(encoding="utf-8")


def test_the_runtime_notice_carries_emscriptens_texts_from_its_own_tree(
        tmp_path, monkeypatch):
    tree = tmp_path / "emscripten"
    for title, relative in build_site.site_licences.EMSCRIPTEN_TEXTS.items():
        (tree / relative).parent.mkdir(parents=True, exist_ok=True)
        (tree / relative).write_text(f"the text of {title}\n", encoding="utf-8")
    fetched = tmp_path / "fetched"
    fetched.write_text("a fetched licence\n", encoding="utf-8")
    monkeypatch.setattr(build_site, "emscripten", lambda: tree)
    monkeypatch.setattr(build_site, "fetch_pinned", lambda pin: fetched)
    notice = build_site.runtime_notice(tmp_path).read_text(encoding="utf-8")
    missing = [title for title in build_site.site_licences.EMSCRIPTEN_TEXTS
               if f"the text of {title}" not in notice]
    assert missing == []


def test_a_runtime_licence_missing_from_emscriptens_tree_is_refused_by_name(
        tmp_path, monkeypatch):
    fetched = tmp_path / "fetched"
    fetched.write_text("a fetched licence\n", encoding="utf-8")
    monkeypatch.setattr(build_site, "emscripten", lambda: tmp_path / "empty")
    monkeypatch.setattr(build_site, "fetch_pinned", lambda pin: fetched)
    with pytest.raises(build_site.SiteError, match="Emscripten"):
        build_site.runtime_notice(tmp_path)


# --- the release the page says it is (OH-243) ---------------------------------


def test_the_page_says_the_version_pyproject_toml_states():
    stated = tomllib.loads((build_site.REPO / "pyproject.toml").read_text(
        encoding="utf-8"))["project"]["version"]
    built = build_site.stamp(build_site.page(EMULATOR_HTML), build_site.version(),
                             "0123456789ab")
    assert f"This is OpenHardware {stated}, built from 0123456789ab." in built


def test_a_pyproject_stating_no_version_is_refused_by_name(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.pytest.ini_options]\naddopts = ""\n', encoding="utf-8")
    with pytest.raises(build_site.SiteError, match="states no \\[project\\] version"):
        build_site.version(pyproject)


def test_a_version_that_is_not_a_string_is_refused_with_what_it_is(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nversion = 1\n", encoding="utf-8")
    with pytest.raises(build_site.SiteError, match="it has 1"):
        build_site.version(pyproject)


def test_a_pyproject_that_is_not_toml_is_refused_by_name(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project\n", encoding="utf-8")
    with pytest.raises(build_site.SiteError, match="pyproject.toml could not be read"):
        build_site.version(pyproject)


def test_a_page_without_the_release_slot_is_refused():
    with pytest.raises(build_site.SiteError, match="inpage-release"):
        build_site.stamp(EMULATOR_HTML, "0.1.0", "0123456789ab")


@pytest.fixture
def repo(tmp_path) -> pathlib.Path:
    """A repository with one commit of one file, `page.html`."""
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                       capture_output=True)
    git("init", "-q")
    (tmp_path / "page.html").write_text("<p>one</p>\n", encoding="utf-8")
    git("add", "page.html")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid",
        "commit", "-q", "-m", "one")
    return tmp_path


def test_a_clean_tree_is_named_by_its_commit_alone(repo):
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert build_site.commit(repo) == head[:12]


def test_a_tree_whose_tracked_file_was_edited_says_so(repo):
    (repo / "page.html").write_text("<p>two</p>\n", encoding="utf-8")
    assert build_site.commit(repo).endswith(" with local changes")


def test_an_untracked_file_the_build_does_not_ship_is_not_a_local_change(repo):
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    (repo / "another-sessions-work.md").write_text("draft\n", encoding="utf-8")
    assert build_site.commit(repo, [repo / "page.html"]) == head[:12]


def test_an_untracked_file_the_build_ships_is_a_local_change(repo):
    """BUNDLE is globs, so a new file beside the tracked ones ships too."""
    (repo / "new-board.json").write_text("{}\n", encoding="utf-8")
    assert build_site.commit(repo, [repo / "page.html", repo / "new-board.json"]
                             ).endswith(" with local changes")


def test_a_folder_that_is_no_repository_is_refused_by_name(tmp_path, monkeypatch):
    # So a repository somewhere above the temporary folder is not found instead.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    with pytest.raises(build_site.SiteError, match="built from a clone"):
        build_site.commit(tmp_path)
