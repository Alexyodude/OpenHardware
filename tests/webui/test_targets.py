# OpenHardware — tests for which targets are runnable.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# The point of `webui/targets.py` is that nothing about it is written down —
# a target exists because a directory does, and it is ready because a file is.
# So these tests build the directories and the files, rather than asserting
# against a list that would have to be kept in step with `core/`.
#
# `monkeypatch` here replaces `build_core.CORE_DIR` and `LIB_DIR`, which are
# the two facts `targets` reads. That is mocking what we do not own — the
# filesystem — and not the thing under test.

import pathlib

import pytest

from tools import build_core
from webui import targets


@pytest.fixture
def fake_tree(tmp_path, monkeypatch):
    """A `core/` and a `build/lib/` under tmp_path, wired into build_core."""
    core = tmp_path / "core"
    lib = tmp_path / "build" / "lib"
    core.mkdir()
    lib.mkdir(parents=True)
    monkeypatch.setattr(build_core, "CORE_DIR", core)
    monkeypatch.setattr(build_core, "LIB_DIR", lib)
    # REPO too, so reported paths are relative to this fake tree rather than
    # to the real checkout -- otherwise every path here falls out absolute and
    # the relative-path rule is never actually exercised.
    monkeypatch.setattr(build_core, "REPO", tmp_path)
    return core, lib


def add_core(core_dir: pathlib.Path, name: str) -> pathlib.Path:
    """A core is a directory with a CMakeLists.txt — build_core's own test."""
    path = core_dir / name
    path.mkdir()
    (path / "CMakeLists.txt").write_text("# stub\n", encoding="utf-8")
    return path


def add_library(name: str) -> pathlib.Path:
    """Whatever `library_path` says this platform calls the built artefact."""
    path = build_core.library_path(name)
    path.write_bytes(b"\x00")
    return path


# --- the real repository ---------------------------------------------------


def test_the_repository_has_exactly_one_core_today():
    """A guard on the claim the UI makes. If a second core lands, this fails
    and whoever added it updates the copy that says only one is runnable."""
    assert build_core.cores() == ["i8086"]


def test_the_catalogue_covers_every_core_that_exists():
    assert [t.name for t in targets.catalogue()] == build_core.cores()


# --- status is computed ----------------------------------------------------


def test_a_core_with_a_built_library_is_ready(fake_tree):
    core, _ = fake_tree
    add_core(core, "i8086")
    add_library("i8086")
    target, = targets.catalogue()
    assert target.status == targets.READY
    assert target.selectable is True


def test_a_core_without_a_library_is_unbuilt(fake_tree):
    core, _ = fake_tree
    add_core(core, "i8086")
    target, = targets.catalogue()
    assert target.status == targets.UNBUILT
    assert target.selectable is False


def test_an_unbuilt_target_carries_the_command_that_fixes_it(fake_tree):
    core, _ = fake_tree
    add_core(core, "i8086")
    target, = targets.catalogue()
    assert "tools/build_core.py" in target.detail


def test_a_library_under_the_repo_is_named_relatively(fake_tree):
    """The absolute Windows path is 78 characters and overflowed the table
    cell, pushing the fix-it command off the right-hand edge."""
    core, _ = fake_tree
    add_core(core, "i8086")
    add_library("i8086")
    assert targets.catalogue()[0].library == "build/lib/" +         build_core.library_path("i8086").name


def test_a_library_outside_the_repo_keeps_its_absolute_path(fake_tree, monkeypatch, tmp_path):
    """Falling back beats raising: a build directory outside the repository is
    unusual, not wrong, and a crash there would take the whole UI with it."""
    core, _ = fake_tree
    add_core(core, "i8086")
    add_library("i8086")
    monkeypatch.setattr(build_core, "REPO", tmp_path / "somewhere-else")
    assert pathlib.Path(targets.catalogue()[0].library).is_absolute()


def test_deleting_the_library_makes_a_ready_target_unbuilt(fake_tree):
    """Status is read from disk every time, never cached. A UI that cached it
    would keep offering Run against a library that is no longer there."""
    core, _ = fake_tree
    add_core(core, "i8086")
    library = add_library("i8086")
    assert targets.catalogue()[0].status == targets.READY
    library.unlink()
    assert targets.catalogue()[0].status == targets.UNBUILT


def test_a_directory_without_a_cmakelists_is_not_a_target(fake_tree):
    """The same test `tools/build_core.cores()` applies, so the two cannot
    disagree about what a core is."""
    core, _ = fake_tree
    (core / "notes").mkdir()
    (core / "notes" / "README.md").write_text("scratch\n", encoding="utf-8")
    assert targets.catalogue() == []


def test_no_cores_is_an_answer_rather_than_an_error(fake_tree):
    """Unlike the inventory collectors, which raise on empty. A checkout that
    has not built anything is a real state the UI has to render."""
    assert targets.catalogue() == []
    assert targets.default_name() is None


# --- ordering and defaults -------------------------------------------------


def test_the_catalogue_is_ordered_the_same_way_twice(fake_tree):
    core, _ = fake_tree
    for name in ("zilog", "i8086", "cortexm0"):
        add_core(core, name)
    assert [t.name for t in targets.catalogue()] == ["cortexm0", "i8086", "zilog"]


def test_the_default_target_is_the_first_runnable_one_not_the_first_one(fake_tree):
    """Opening on a target that cannot run, while a runnable one sits beside
    it, makes the tool look broken on a machine where it works."""
    core, _ = fake_tree
    add_core(core, "aardvark")   # sorts first, never built
    add_core(core, "i8086")
    add_library("i8086")
    assert targets.default_name() == "i8086"


# --- selection -------------------------------------------------------------


def test_a_ready_target_can_be_selected(fake_tree):
    core, _ = fake_tree
    add_core(core, "i8086")
    add_library("i8086")
    assert targets.require_selectable("i8086").name == "i8086"


def test_selecting_an_unbuilt_target_is_refused_with_the_reason(fake_tree):
    core, _ = fake_tree
    add_core(core, "i8086")
    with pytest.raises(targets.TargetError) as caught:
        targets.require_selectable("i8086")
    assert "not runnable" in str(caught.value)
    assert "build_core.py" in str(caught.value)


def test_selecting_an_unknown_target_lists_what_does_exist(fake_tree):
    core, _ = fake_tree
    add_core(core, "i8086")
    with pytest.raises(targets.TargetError) as caught:
        targets.require_selectable("rp2040")
    assert "no such target" in str(caught.value)
    assert "i8086" in str(caught.value)


def test_the_refusal_says_none_rather_than_nothing_when_core_is_empty(fake_tree):
    """An empty list in an error message reads as a bug in the message."""
    with pytest.raises(targets.TargetError) as caught:
        targets.require_selectable("rp2040")
    assert "none" in str(caught.value)


def test_find_returns_none_rather_than_guessing_what_was_meant(fake_tree):
    core, _ = fake_tree
    add_core(core, "i8086")
    assert targets.find("i8085") is None


# --- the JSON the UI receives ----------------------------------------------


def test_the_json_carries_selectable_so_the_ui_never_recomputes_it(fake_tree):
    """The disabled state of an <option> must come from the server. A UI that
    re-derived it from `status` would be a second place for the rule to live."""
    core, _ = fake_tree
    add_core(core, "i8086")
    add_library("i8086")
    payload = targets.catalogue()[0].as_json()
    assert payload["selectable"] is True
    assert set(payload) == {"name", "status", "selectable", "library", "detail"}


def test_an_unbuilt_target_reports_no_library_path(fake_tree):
    core, _ = fake_tree
    add_core(core, "i8086")
    assert targets.catalogue()[0].as_json()["library"] is None
