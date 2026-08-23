# OpenHardware - tests for the ticket system.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Tests for tools/tickets.py and tools/ticket_guard.py, per rules/ticket-claims.md.

The claim machinery decides whether one session may overwrite another's work,
so the cases that matter most are the refusals. A permissive bug here is
silent: everything keeps working until two sessions land in one file.
"""

import pathlib

import pytest

from tools import tickets as T
from tools.check_ticket_claims import unmatched_claims
from tools.ticket_guard import decide

REPO = pathlib.Path(__file__).resolve().parents[2]

TICKET = """---
id: {id}
title: {title}
status: {status}
priority: {priority}
touches:
{touches}
---

body
"""


def _write(directory, ticket_id, title="A ticket", status="open", priority="P1", touches=()):
    # Quoted, because a leading `*` is a YAML alias marker and a bare
    # `- **/cpu.cc` will not parse at all. `yaml.safe_dump` quotes these when
    # the CLI writes a ticket, so the fixture must too;
    # test_a_leading_star_claim_round_trips pins that the writer really does.
    body = "\n".join(f"  - {t!r}" for t in touches) or "  []"
    path = directory / f"{ticket_id}-{T.slug(title)}.md"
    path.write_text(
        TICKET.format(
            id=ticket_id, title=title, status=status, priority=priority, touches=body
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def board(tmp_path, monkeypatch):
    """A ticket directory and lock directory redirected away from the real repo."""
    tickets = tmp_path / "docs" / "tickets"
    locks = tmp_path / ".omc" / "ticket-locks"
    tickets.mkdir(parents=True)
    locks.mkdir(parents=True)
    monkeypatch.setattr(T, "REPO", tmp_path)
    monkeypatch.setattr(T, "TICKET_DIR", tickets)
    monkeypatch.setattr(T, "LOCK_DIR", locks)
    return tickets


# --- glob semantics -------------------------------------------------------------


def test_a_star_does_not_cross_a_separator():
    """fnmatch's `*` would claim tools/a/b.py from tools/*.py, which is wrong."""
    assert T.matches_claim("tools/*.py", "tools/tickets.py")
    assert not T.matches_claim("tools/*.py", "tools/sub/nested.py")


def test_double_star_does_cross():
    assert T.matches_claim("core/**", "core/i8086/cpu.cc")
    assert T.matches_claim("**/cpu.cc", "core/i8086/cpu.cc")


def test_a_bare_directory_claims_everything_under_it():
    """Requiring the /** is a footgun that reads as a claim matching nothing."""
    assert T.matches_claim("core/i8086", "core/i8086/cpu.cc")


def test_a_claim_does_not_leak_into_a_sibling():
    assert not T.matches_claim("core/**", "tools/x.py")


def test_windows_separators_normalise():
    assert T.matches_claim("core/**", "core\\i8086\\cpu.cc")


# --- parsing ----------------------------------------------------------------------


def test_a_ticket_round_trips(board):
    _write(board, "OH-1", touches=["core/**"])
    (ticket,) = T.load_tickets(board)
    assert (ticket.id, ticket.status, ticket.touches) == ("OH-1", "open", ("core/**",))


def test_a_bad_status_is_rejected(board):
    _write(board, "OH-1", status="nearly-done")
    with pytest.raises(T.TicketError, match="status"):
        T.load_tickets(board)


def test_a_duplicate_id_is_rejected(board):
    _write(board, "OH-1", title="First")
    _write(board, "OH-1", title="Second")
    with pytest.raises(T.TicketError, match="declared twice"):
        T.load_tickets(board)


def test_missing_frontmatter_is_rejected(board):
    (board / "OH-9-bare.md").write_text("just prose\n", encoding="utf-8")
    with pytest.raises(T.TicketError, match="frontmatter"):
        T.load_tickets(board)


def test_a_missing_directory_is_empty_not_an_error(tmp_path):
    assert T.load_tickets(tmp_path / "nope") == []


def test_ids_advance_past_the_highest(board):
    _write(board, "OH-1")
    _write(board, "OH-7")
    assert T.next_id(T.load_tickets(board)) == "OH-8"


# --- who owns what -----------------------------------------------------------------


def test_a_closed_ticket_releases_its_claim(board):
    _write(board, "OH-1", status="done", touches=["core/**"])
    assert T.owners_of("core/cpu.cc", T.load_tickets(board)) == []


def test_a_blocked_ticket_keeps_its_claim(board):
    """Releasing on stall is exactly how two sessions land in one file."""
    _write(board, "OH-1", status="blocked", touches=["core/**"])
    assert [t.id for t in T.owners_of("core/cpu.cc", T.load_tickets(board))] == ["OH-1"]


def test_collisions_are_reported_against_real_files_only(board, tmp_path):
    """Two patterns that overlap only in theory are not a collision."""
    _write(board, "OH-1", title="One", touches=["core/*.cc"])
    _write(board, "OH-2", title="Two", touches=["**/cpu.cc"])
    assert T.collisions(T.load_tickets(board)) == []

    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "cpu.cc").write_text("//\n", encoding="utf-8")
    found = T.collisions(T.load_tickets(board))
    assert [(a.id, b.id) for a, b, _ in found] == [("OH-1", "OH-2")]


# --- locks -------------------------------------------------------------------------


def test_a_second_session_cannot_take_a_held_ticket(board):
    T.take("OH-1", "sess-A")
    with pytest.raises(T.TicketError, match="held by sess-A"):
        T.take("OH-1", "sess-B")


def test_the_holder_may_retake_its_own(board):
    T.take("OH-1", "sess-A")
    T.take("OH-1", "sess-A")
    assert T.held_by("sess-A") == ["OH-1"]


def test_steal_takes_a_dead_claim(board):
    T.take("OH-1", "sess-A")
    T.take("OH-1", "sess-B", steal=True)
    assert T.holder_of("OH-1")[0] == "sess-B"


def test_starting_a_second_ticket_releases_the_first(board):
    """One at a time, or claims quietly accumulate across a long session."""
    T.take("OH-1", "sess-A")
    T.take("OH-2", "sess-A")
    assert T.held_by("sess-A") == ["OH-2"]


def test_release_frees_everything_this_session_holds(board):
    T.take("OH-1", "sess-A")
    assert T.release("sess-A") == ["OH-1"]
    assert T.holder_of("OH-1") is None


# --- the guard ----------------------------------------------------------------------


def _write_call(path):
    return {"tool_name": "Write", "tool_input": {"file_path": path}}


def test_the_guard_ignores_reads(board, monkeypatch):
    _write(board, "OH-1", touches=["core/**"])
    monkeypatch.setattr(T, "current_ticket", lambda: None)
    call = {"tool_name": "Read", "tool_input": {"file_path": "core/cpu.cc"}}
    assert decide(call, "sess-A")[0] is True


def test_the_guard_allows_an_unclaimed_path(board, monkeypatch):
    """Most of the tree is unclaimed; demanding a ticket for all of it is how
    the guard gets switched off, taking the CI check with it."""
    _write(board, "OH-1", touches=["core/**"])
    monkeypatch.setattr(T, "current_ticket", lambda: None)
    assert decide(_write_call("webui/api.py"), "sess-A")[0] is True


def test_the_guard_refuses_a_claimed_path_with_no_ticket(board, monkeypatch):
    _write(board, "OH-1", touches=["core/**"])
    monkeypatch.setattr(T, "current_ticket", lambda: None)
    allowed, reason = decide(_write_call("core/cpu.cc"), "sess-A")
    assert allowed is False and "names no ticket" in reason


def test_the_guard_allows_the_holder(board, monkeypatch):
    _write(board, "OH-1", touches=["core/**"])
    T.take("OH-1", "sess-A")
    monkeypatch.setattr(T, "current_ticket", lambda: "OH-1")
    assert decide(_write_call("core/cpu.cc"), "sess-A")[0] is True


def test_naming_a_ticket_is_not_claiming_it(board, monkeypatch):
    """Self-declared and unverified, two sessions could both export OH-1."""
    _write(board, "OH-1", touches=["core/**"])
    monkeypatch.setattr(T, "current_ticket", lambda: "OH-1")
    allowed, reason = decide(_write_call("core/cpu.cc"), "sess-A")
    assert allowed is False and "has not claimed it" in reason


def test_the_guard_refuses_a_ticket_another_session_holds(board, monkeypatch):
    _write(board, "OH-1", touches=["core/**"])
    T.take("OH-1", "sess-A")
    monkeypatch.setattr(T, "current_ticket", lambda: "OH-1")
    allowed, reason = decide(_write_call("core/cpu.cc"), "sess-B")
    assert allowed is False and "held by sess-A" in reason


def test_the_guard_refuses_another_tickets_file(board, monkeypatch):
    _write(board, "OH-1", title="Core", touches=["core/**"])
    _write(board, "OH-2", title="UI", touches=["webui/**"])
    T.take("OH-2", "sess-A")
    monkeypatch.setattr(T, "current_ticket", lambda: "OH-2")
    allowed, reason = decide(_write_call("core/cpu.cc"), "sess-A")
    assert allowed is False and "OH-1" in reason


# --- similarity and unmatched claims -------------------------------------------------


def test_an_exact_title_scores_one():
    assert T.similarity("Build the core", "Build the core") == 1.0


def test_stopwords_do_not_make_neighbours():
    """Without the stoplist a shared 'of the' pairs unrelated tickets."""
    with_stops = T.similarity(
        "Decode of the instruction stream", "Rendering of the board artwork"
    )
    assert with_stops == 0.0, "only stopwords are shared, so nothing is"


def test_an_unwritten_ticket_is_summarised_not_listed(board, tmp_path, monkeypatch):
    """Listing each claim produced 24 lines of noise on a freshly seeded board."""
    monkeypatch.setattr(T, "REPO", tmp_path)
    _write(board, "OH-1", touches=["core/**", "tests/i8086/**"])
    suspicious, unwritten = unmatched_claims(T.load_tickets(board))
    assert suspicious == [] and unwritten == 1


def test_a_claim_beside_matching_ones_is_flagged(board, tmp_path, monkeypatch):
    monkeypatch.setattr(T, "REPO", tmp_path)
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "cpu.cc").write_text("//\n", encoding="utf-8")
    _write(board, "OH-1", touches=["core/**", "tpyo/**"])
    suspicious, unwritten = unmatched_claims(T.load_tickets(board))
    assert suspicious == [("OH-1", "tpyo/**")] and unwritten == 0


# --- the real board --------------------------------------------------------------------


def test_this_repositorys_tickets_parse_and_do_not_collide():
    tickets = T.load_tickets()
    assert tickets, "the board should not be empty"
    found = T.collisions(tickets)
    assert not found, f"claims overlap: {[(a.id, b.id, p) for a, b, p in found]}"


def test_a_leading_star_claim_round_trips(board):
    """`**/cpu.cc` is a YAML alias unless quoted, and would break the board.

    `yaml.safe_dump` quotes it; this pins that it keeps doing so, because the
    failure is not local -- one unparseable ticket takes down every command
    that loads the directory.
    """
    ticket = T.Ticket(
        id="OH-1",
        title="Star claim",
        status="open",
        priority="P1",
        owner="",
        created="2026-08-23",
        path=board / "OH-1-star.md",
        touches=("**/cpu.cc", "*.py", "core/**"),
        body="body",
    )
    T.write_ticket(ticket)
    (read_back,) = T.load_tickets(board)
    assert read_back.touches == ("**/cpu.cc", "*.py", "core/**")

