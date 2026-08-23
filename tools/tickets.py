#!/usr/bin/env python3
# OpenHardware - what each parallel session is working on, and what it must not touch.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Tickets: one file per unit of work, each claiming the paths it may edit.

## Why this exists

The i8086 ledger is 43 cells across seven slices, and several are independent
of each other. That is work for more than one session at a time, and two
sessions editing this tree with nothing but a handoff document between them is
how you get a lost edit that nobody notices until CI.

A ticket is the answer to "may I write this file?", asked before the write
rather than discovered after it.

## One file per ticket, and why not a list

Every ticket is its own file in `docs/tickets/`. The obvious alternative -- one
`TICKETS.md` with a table -- fails at exactly the job it is for: two sessions
appending rows conflict on the list itself. A directory of files is the one
shape where two sessions adding work do not collide.

This is the same reasoning `.claude/rules` was already built on, and the same
frontmatter machinery reads both (`tools/rules_meta.py`).

## The files are the truth, GitHub is a mirror

`tools/ticket_guard.py` runs on every edit. It cannot ask a network service who
owns a path -- that would put a round trip in front of every write and fail
offline. So the claim lives in the file, and `tickets sync` pushes one way to
GitHub issues for the history that files are bad at keeping.

## Three layers, and only one of them prevents

| Layer | Catches | Skippable |
|---|---|---|
| `tools/ticket_guard.py` (PreToolUse) | a write into another ticket's path, before it lands | only by disabling hooks |
| `tools/check_ticket_claims.py` (CI) | everything, whoever produced the diff | no |
| `CLAUDE.md` | nothing -- it is what makes a session cooperate at all | always |

Reporting after the fact is not enough on its own: by then the edit exists and
someone has to work out whose it was.

## One ticket at a time

`tickets start` takes a ticket through an exclusive lock file created with
`O_EXCL`, so two sessions cannot both hold one. There is deliberately **no
expiry**: a lock cannot tell a crashed session from a thinking one, and a lock
that quietly lapses is worse than one you must take deliberately. A dead claim
is taken with `--steal`, which prints its age first so the decision is informed.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import os
import pathlib
import re
import sys

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - PyYAML is a declared dependency
    print("tickets: PyYAML is required (pip install PyYAML)", file=sys.stderr)
    raise

REPO = pathlib.Path(__file__).resolve().parents[1]
TICKET_DIR = REPO / "docs" / "tickets"
LOCK_DIR = REPO / ".omc" / "ticket-locks"

PREFIX = "OH"
PRIORITIES = ("P0", "P1", "P2", "P3")
STATUSES = ("open", "in-progress", "in-review", "blocked", "done", "duplicate")

#: A ticket holds its claim until it is finished. `blocked` is deliberately in
#: here: a ticket waiting on something still owns its files, and releasing them
#: because it stalled is how two sessions end up in the same file.
OPEN_STATUSES = frozenset({"open", "in-progress", "in-review", "blocked"})

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.S)
_ID = re.compile(rf"\A{PREFIX}-(\d+)\Z")


class TicketError(Exception):
    """A ticket file is missing, malformed, or contradicts another."""


@dataclasses.dataclass(frozen=True)
class Ticket:
    id: str
    title: str
    status: str
    priority: str
    owner: str
    created: str
    path: pathlib.Path
    touches: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    github: int | None = None
    duplicate_of: str | None = None
    parent: str | None = None
    body: str = ""

    @property
    def number(self) -> int:
        match = _ID.match(self.id)
        if not match:
            raise TicketError(f"{self.path}: id {self.id!r} is not {PREFIX}-<number>")
        return int(match.group(1))

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES


# --- paths and globs -----------------------------------------------------------


def normalise(path: str | pathlib.Path) -> str:
    """A repo-relative POSIX path, whatever shape it arrives in."""
    text = str(path).replace("\\", "/").strip()
    if text.startswith("./"):
        text = text[2:]
    root = str(REPO).replace("\\", "/")
    if text.lower().startswith(root.lower() + "/"):
        text = text[len(root) + 1 :]
    return text.lstrip("/")


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a claim pattern to a regex.

    `fnmatch` is not usable here: its `*` crosses `/`, so `tools/*` would claim
    `tools/a/b/c.py` and a session would be refused a file nobody meant to
    claim. Here `*` stops at a separator and `**` does not.

    A pattern with no wildcard and no file extension is read as a directory,
    so `core/i8086` claims everything beneath it. That is what people mean
    when they write it, and requiring the `/**` is a footgun that shows up as
    a claim silently matching nothing.
    """
    glob = normalise(pattern)
    looks_like_dir = not re.search(r"[*?]", glob) and not re.search(r"\.[A-Za-z0-9]+$", glob)
    if looks_like_dir:
        glob = glob.rstrip("/") + "/**"

    out: list[str] = []
    i = 0
    while i < len(glob):
        char = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif char == "*":
            out.append("[^/]*")
            i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(char))
            i += 1
    return re.compile("\\A" + "".join(out) + "\\Z")


def matches_claim(pattern: str, path: str) -> bool:
    return bool(glob_to_regex(pattern).match(normalise(path)))


# --- reading and writing -------------------------------------------------------


def slug(title: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return text[:52].rstrip("-") or "ticket"


def _as_list(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def parse_ticket(path: pathlib.Path) -> Ticket:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if not match:
        raise TicketError(f"{path}: no YAML frontmatter")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise TicketError(f"{path}: frontmatter does not parse: {exc}") from exc
    if not isinstance(meta, dict):
        raise TicketError(f"{path}: frontmatter is not a mapping")

    for key in ("id", "title", "status", "priority"):
        if not meta.get(key):
            raise TicketError(f"{path}: frontmatter has no {key!r}")
    if meta["status"] not in STATUSES:
        raise TicketError(f"{path}: status {meta['status']!r} not in {list(STATUSES)}")
    if meta["priority"] not in PRIORITIES:
        raise TicketError(f"{path}: priority {meta['priority']!r} not in {list(PRIORITIES)}")

    return Ticket(
        id=str(meta["id"]),
        title=str(meta["title"]),
        status=str(meta["status"]),
        priority=str(meta["priority"]),
        owner=str(meta.get("owner", "") or ""),
        created=str(meta.get("created", "") or ""),
        path=path,
        touches=_as_list(meta.get("touches")),
        avoid=_as_list(meta.get("avoid")),
        github=int(meta["github"]) if meta.get("github") is not None else None,
        duplicate_of=meta.get("duplicate-of") or meta.get("duplicate_of"),
        parent=meta.get("parent"),
        body=match.group(2),
    )


def load_tickets(directory: pathlib.Path | None = None) -> list[Ticket]:
    """Every ticket, lowest id first. A missing directory is empty, not an error.

    `directory` defaults to None rather than to TICKET_DIR: a default argument
    is bound once, at definition time, so `TICKET_DIR` as a default would
    freeze the module-level value and ignore any later reassignment. The
    guard's self-test relies on redirecting it, and so would any caller
    pointing this at another tree.
    """
    directory = TICKET_DIR if directory is None else directory
    if not directory.is_dir():
        return []
    tickets = [parse_ticket(p) for p in sorted(directory.glob(f"{PREFIX}-*.md"))]
    seen: dict[str, pathlib.Path] = {}
    for ticket in tickets:
        if ticket.id in seen:
            raise TicketError(f"{ticket.id} is declared twice: {seen[ticket.id]} and {ticket.path}")
        seen[ticket.id] = ticket.path
    return sorted(tickets, key=lambda t: t.number)


def write_ticket(ticket: Ticket) -> pathlib.Path:
    meta: dict = {
        "id": ticket.id,
        "title": ticket.title,
        "status": ticket.status,
        "priority": ticket.priority,
    }
    if ticket.owner:
        meta["owner"] = ticket.owner
    if ticket.created:
        meta["created"] = ticket.created
    if ticket.github is not None:
        meta["github"] = ticket.github
    if ticket.touches:
        meta["touches"] = list(ticket.touches)
    if ticket.avoid:
        meta["avoid"] = list(ticket.avoid)
    if ticket.duplicate_of:
        meta["duplicate-of"] = ticket.duplicate_of
    if ticket.parent:
        meta["parent"] = ticket.parent

    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip("\n")
    body = ticket.body.strip("\n")
    ticket.path.parent.mkdir(parents=True, exist_ok=True)
    ticket.path.write_text(f"---\n{front}\n---\n\n{body}\n", encoding="utf-8")
    return ticket.path


def next_id(tickets: list[Ticket]) -> str:
    highest = max((t.number for t in tickets), default=0)
    return f"{PREFIX}-{highest + 1}"


# --- collisions ------------------------------------------------------------------


def owners_of(path: str, tickets: list[Ticket]) -> list[Ticket]:
    """Every open ticket whose claims cover this path."""
    return [
        t
        for t in tickets
        if t.is_open and any(matches_claim(pattern, path) for pattern in t.touches)
    ]


def collisions(tickets: list[Ticket]) -> list[tuple[Ticket, Ticket, str]]:
    """Pairs of open tickets claiming a path that actually exists.

    Compared against real files rather than by intersecting the patterns:
    `tools/*.py` and `**/tickets.py` overlap in theory on every repository and
    in practice only where a file sits in both. Reporting theoretical overlap
    produces warnings nobody can act on.
    """
    files = [normalise(p.relative_to(REPO)) for p in REPO.rglob("*") if p.is_file()]
    files = [f for f in files if not f.startswith((".git/", ".omc/", "third_party/"))]

    out: list[tuple[Ticket, Ticket, str]] = []
    openers = [t for t in tickets if t.is_open]
    for i, a in enumerate(openers):
        for b in openers[i + 1 :]:
            for path in files:
                if any(matches_claim(p, path) for p in a.touches) and any(
                    matches_claim(p, path) for p in b.touches
                ):
                    out.append((a, b, path))
                    break
    return out


# --- similarity -------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+")
#: Words that carry no signal in this repository's titles; without them a
#: shared "the simulator" scores two unrelated tickets as neighbours.
_STOP = frozenset(
    "a an and are as at be by for from has in is it its of on or that the to with "
    "when which while into not no".split()
)


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of the significant words in two titles."""
    first, second = _terms(a), _terms(b)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


#: Warn, never fail. No threshold cleanly separates "duplicate" from
#: "adjacent", and a fuzzy gate that blocks builds gets switched off -- taking
#: the exact claim check next to it along with it.
SIMILAR_THRESHOLD = 0.30


def similar_to(title: str, tickets: list[Ticket], threshold: float = SIMILAR_THRESHOLD):
    scored = [(similarity(title, t.title), t) for t in tickets]
    return sorted(
        ((s, t) for s, t in scored if s >= threshold), key=lambda pair: -pair[0]
    )


# --- session locks ------------------------------------------------------------------


def session_id() -> str:
    """Who is asking. Explicit variable first, then the process tree."""
    for var in ("OH_SESSION_ID", "CLAUDE_SESSION_ID"):
        value = os.environ.get(var)
        if value:
            return value
    return f"pid-{os.getppid()}"


def _lock_path(ticket_id: str) -> pathlib.Path:
    return LOCK_DIR / f"{ticket_id}.lock"


def holder_of(ticket_id: str) -> tuple[str, str] | None:
    """(session, iso timestamp) holding this ticket, or None."""
    path = _lock_path(ticket_id)
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8").strip().split("\n")
    return (raw[0] if raw else "", raw[1] if len(raw) > 1 else "")


def held_by(session: str) -> list[str]:
    if not LOCK_DIR.is_dir():
        return []
    out = []
    for path in sorted(LOCK_DIR.glob(f"{PREFIX}-*.lock")):
        held = holder_of(path.stem)
        if held and held[0] == session:
            out.append(path.stem)
    return out


def take(ticket_id: str, session: str, steal: bool = False, now: str | None = None) -> None:
    """Claim a ticket exclusively, or raise.

    O_EXCL rather than exists-then-write: the check and the create must be one
    operation, or two sessions starting together both see it free.
    """
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    path = _lock_path(ticket_id)

    # One at a time: release anything else this session holds first, so claims
    # cannot quietly accumulate across a long session.
    for other in held_by(session):
        if other != ticket_id:
            _lock_path(other).unlink(missing_ok=True)

    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        current = holder_of(ticket_id)
        if current and current[0] == session:
            return
        if not steal:
            who, since = current or ("unknown", "unknown")
            raise TicketError(
                f"{ticket_id} is held by {who} since {since}. "
                f"If that session is gone, take it with --steal."
            )
        path.unlink(missing_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{session}\n{stamp}\n")


def release(session: str) -> list[str]:
    freed = held_by(session)
    for ticket_id in freed:
        _lock_path(ticket_id).unlink(missing_ok=True)
    return freed


def current_ticket() -> str | None:
    """The ticket this session says it is on."""
    value = os.environ.get("OH_TICKET")
    if value:
        return value.strip()
    pointer = REPO / ".omc" / "current-ticket"
    if pointer.is_file():
        # A stray newline or tab here must not become part of the id.
        return pointer.read_text(encoding="utf-8").strip() or None
    return None


# --- CLI ---------------------------------------------------------------------------


def _fmt(ticket: Ticket) -> str:
    held = holder_of(ticket.id)
    mark = f"  [held by {held[0]}]" if held else ""
    owner = f"  @{ticket.owner}" if ticket.owner else ""
    return f"  {ticket.priority}  {ticket.id:<8} {ticket.status:<12} {ticket.title}{owner}{mark}"


def cmd_list(args) -> int:
    tickets = load_tickets()
    shown = tickets if args.all else [t for t in tickets if t.is_open]
    if not shown:
        print("no open tickets" if not args.all else "no tickets")
        return 0
    for priority in PRIORITIES:
        group = [t for t in shown if t.priority == priority]
        if group:
            print(f"{priority}")
            for ticket in group:
                print(_fmt(ticket))
    return 0


def cmd_new(args) -> int:
    tickets = load_tickets()
    close = similar_to(args.title, [t for t in tickets if t.is_open])
    if close and not args.force:
        print("this looks like something that already exists:", file=sys.stderr)
        for score, ticket in close[:5]:
            print(f"  {score:.2f}  {ticket.id}  {ticket.title}", file=sys.stderr)
        print("\nfile it anyway with --force, or work the existing one.", file=sys.stderr)
        return 1

    ticket_id = next_id(tickets)
    ticket = Ticket(
        id=ticket_id,
        title=args.title,
        status="open",
        priority=args.priority,
        owner=args.owner or "",
        created=_dt.date.today().isoformat(),
        path=TICKET_DIR / f"{ticket_id}-{slug(args.title)}.md",
        touches=tuple(args.touches or ()),
        avoid=tuple(args.avoid or ()),
        body=args.body or "_No description yet._",
    )
    path = write_ticket(ticket)
    print(f"{ticket.id}  {path.relative_to(REPO)}")
    return 0


def _find(ticket_id: str) -> Ticket:
    for ticket in load_tickets():
        if ticket.id.lower() == ticket_id.lower():
            return ticket
    raise TicketError(f"no ticket {ticket_id}")


def cmd_set(args) -> int:
    ticket = _find(args.id)
    changes = {}
    if args.status:
        changes["status"] = args.status
    if args.priority:
        changes["priority"] = args.priority
    if args.owner is not None:
        changes["owner"] = args.owner
    touches = list(ticket.touches) + list(args.touch or ())
    avoid = list(ticket.avoid) + list(args.avoid_add or ())
    updated = dataclasses.replace(
        ticket, touches=tuple(dict.fromkeys(touches)), avoid=tuple(dict.fromkeys(avoid)), **changes
    )
    write_ticket(updated)
    print(_fmt(updated).strip())
    return 0


def cmd_note(args) -> int:
    """Append a dated finding without rewriting the body."""
    ticket = _find(args.id)
    stamp = _dt.date.today().isoformat()
    body = ticket.body.rstrip("\n") + f"\n\n**Note {stamp}:** {args.text}\n"
    write_ticket(dataclasses.replace(ticket, body=body))
    print(f"{ticket.id}: note added")
    return 0


def cmd_start(args) -> int:
    ticket = _find(args.id)
    if not ticket.is_open:
        print(f"{ticket.id} is {ticket.status}; nothing to start", file=sys.stderr)
        return 1
    session = session_id()
    if args.steal:
        held = holder_of(ticket.id)
        if held:
            print(f"stealing {ticket.id} from {held[0]}, held since {held[1]}", file=sys.stderr)
    take(ticket.id, session, steal=args.steal)
    (REPO / ".omc").mkdir(parents=True, exist_ok=True)
    (REPO / ".omc" / "current-ticket").write_text(ticket.id, encoding="utf-8")
    print(f"{session} now holds {ticket.id}: {ticket.title}")
    if ticket.touches:
        print("  may edit:")
        for pattern in ticket.touches:
            print(f"    {pattern}")
    return 0


def cmd_stop(args) -> int:
    freed = release(session_id())
    (REPO / ".omc" / "current-ticket").unlink(missing_ok=True)
    print(f"released {', '.join(freed)}" if freed else "held nothing")
    return 0


def cmd_whoami(args) -> int:
    session = session_id()
    mine = held_by(session)
    print(f"session {session}")
    print(f"  holding: {', '.join(mine) if mine else 'nothing'}")
    print(f"  pointer: {current_ticket() or '(unset)'}")
    others = []
    if LOCK_DIR.is_dir():
        for path in sorted(LOCK_DIR.glob(f"{PREFIX}-*.lock")):
            held = holder_of(path.stem)
            if held and held[0] != session:
                others.append(f"    {path.stem}  {held[0]}  since {held[1]}")
    print("  others:" if others else "  others: none")
    for line in others:
        print(line)
    return 0


def cmd_owner(args) -> int:
    found = owners_of(args.path, load_tickets())
    if not found:
        print(f"{normalise(args.path)}: unclaimed")
        return 0
    for ticket in found:
        print(_fmt(ticket).strip())
    return 0


def cmd_similar(args) -> int:
    close = similar_to(args.title, load_tickets(), args.threshold)
    if not close:
        print("nothing resembles that")
        return 0
    for score, ticket in close:
        print(f"  {score:.2f}  {ticket.id}  {ticket.title}")
    return 0


def cmd_dupes(args) -> int:
    """Audit open tickets against each other. Closed ones are history."""
    tickets = [t for t in load_tickets() if t.is_open]
    hits = []
    for i, a in enumerate(tickets):
        for b in tickets[i + 1 :]:
            score = similarity(a.title, b.title)
            if score >= args.threshold:
                hits.append((score, a, b))
    for score, a, b in sorted(hits, key=lambda h: -h[0]):
        print(f"  {score:.2f}  {a.id} {a.title}\n        {b.id} {b.title}")
    print(f"{len(hits)} pair(s) at or above {args.threshold}" if hits else "no likely duplicates")
    return 0


def cmd_merge(args) -> int:
    source, target = _find(args.id), _find(args.into)
    moved = tuple(dict.fromkeys(list(target.touches) + list(source.touches)))
    write_ticket(dataclasses.replace(target, touches=moved))
    write_ticket(
        dataclasses.replace(
            source,
            status="duplicate",
            duplicate_of=target.id,
            touches=(),
            body=source.body.rstrip("\n") + f"\n\nFolded into {target.id}.\n",
        )
    )
    print(f"{source.id} folded into {target.id}; {len(source.touches)} claim(s) moved")
    return 0


def cmd_group(args) -> int:
    child, parent = _find(args.id), _find(args.parent)
    write_ticket(dataclasses.replace(child, parent=parent.id))
    print(f"{child.id} recorded under {parent.id}")
    return 0


def cmd_check(args) -> int:
    from tools.check_ticket_claims import main as check_main

    return check_main([])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tickets", description="what each session is working on, and what it must not touch"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="open tickets, most urgent first")
    p.add_argument("--all", action="store_true", help="include done and duplicate")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("new", help="file a ticket")
    p.add_argument("title")
    p.add_argument("--priority", choices=PRIORITIES, default="P2")
    p.add_argument("--owner", default="")
    p.add_argument("--touches", nargs="*", help="paths or globs this ticket claims")
    p.add_argument("--avoid", nargs="*", help="paths it must not touch")
    p.add_argument("--body", help="the problem, in prose")
    p.add_argument("--force", action="store_true", help="file even if it resembles another")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("set", help="change a field")
    p.add_argument("id")
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--priority", choices=PRIORITIES)
    p.add_argument("--owner")
    p.add_argument("--touch", nargs="*", help="add a claim")
    p.add_argument("--avoid-add", nargs="*", dest="avoid_add")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("note", help="append a dated finding")
    p.add_argument("id")
    p.add_argument("text")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("start", help="take a ticket for this session")
    p.add_argument("id")
    p.add_argument("--steal", action="store_true", help="take one another session holds")
    p.set_defaults(func=cmd_start)

    sub.add_parser("stop", help="give it back").set_defaults(func=cmd_stop)
    sub.add_parser("whoami", help="what this session holds").set_defaults(func=cmd_whoami)

    p = sub.add_parser("owner", help="which ticket claims a path")
    p.add_argument("path")
    p.set_defaults(func=cmd_owner)

    p = sub.add_parser("similar", help="what already looks like this")
    p.add_argument("title")
    p.add_argument("--threshold", type=float, default=SIMILAR_THRESHOLD)
    p.set_defaults(func=cmd_similar)

    p = sub.add_parser("dupes", help="audit every open ticket against every other")
    p.add_argument("--threshold", type=float, default=SIMILAR_THRESHOLD)
    p.set_defaults(func=cmd_dupes)

    p = sub.add_parser("merge", help="same problem filed twice")
    p.add_argument("id")
    p.add_argument("--into", required=True)
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("group", help="related but distinct")
    p.add_argument("id")
    p.add_argument("--parent", required=True)
    p.set_defaults(func=cmd_group)

    sub.add_parser("check", help="collisions and claim violations").set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except TicketError as exc:
        print(f"tickets: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
