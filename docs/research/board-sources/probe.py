#!/usr/bin/env python3
# OpenHardware - re-check the board-source survey against the sources themselves.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Re-derive the machine-checkable cells of sources.json and print what moved.

A survey is a dated claim about somebody else's server, so the useful question
is not "is this file correct" but "is it still correct". Two of the sixteen
rows are already known to be fragile in different ways: st.com could not be
reached at all when the survey was written, and one SparkFun repository's
README points at a LICENSE.md that is not in the repository. Both are the kind
of thing that changes without anyone here noticing.

So this re-fetches only what a machine can settle -- repository size, the
licence GitHub recognises, whether a URL still answers -- and prints the
recorded value beside the observed one. It never edits sources.json. Which
cells to believe, and how to reword a row when they disagree, is a judgement,
and the point of the evidence classes is that a judgement is visible as one.

    python docs/research/board-sources/probe.py

Unauthenticated GitHub allows 60 requests an hour and this makes two per
GitHub-hosted row, so it fits -- but if `gh` is logged in or $GITHUB_TOKEN is
set, the token is used and the limit stops mattering.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).parent

GITHUB_REPO = re.compile(r"^https://github\.com/([^/]+)/([^/#?]+)")
FIRST_NUMBER = re.compile(r"([\d,]{3,})")

TIMEOUT = 45


def token() -> str | None:
    """A GitHub token from the environment, or from `gh` if it is logged in."""
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def fetch(url: str, auth: str | None, accept: str = "application/json") -> dict:
    """GET a JSON API response, or raise with the URL that failed."""
    request = urllib.request.Request(url, headers={"Accept": accept})
    request.add_header("User-Agent", "OpenHardware-board-source-probe")
    if auth:
        request.add_header("Authorization", f"Bearer {auth}")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def reachable(url: str) -> str:
    """The HTTP status a URL answers with, or why it did not answer.

    Tries HEAD first and falls back to a one-byte ranged GET, because several
    of these hosts serve the file happily and refuse the HEAD -- nordicsemi.com
    answers 403 to HEAD and 200 to GET. Reporting the HEAD alone would print a
    failure for a download that works.
    """
    for method, headers in (("HEAD", {}), ("GET", {"Range": "bytes=0-0"})):
        request = urllib.request.Request(url, method=method, headers=headers)
        request.add_header("User-Agent", "Mozilla/5.0 OpenHardware-board-source-probe")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                suffix = "" if method == "HEAD" else " (HEAD refused, GET worked)"
                return f"HTTP {response.status}{suffix}"
        except urllib.error.HTTPError as error:
            last = f"HTTP {error.code}"
        except Exception as error:  # noqa: BLE001 - the reason is the result here
            last = f"unreachable: {type(error).__name__}: {error}"
    return last


def recorded_number(text: str) -> int | None:
    """The first number in a recorded size string, or None if there is none."""
    found = FIRST_NUMBER.search(text)
    return int(found.group(1).replace(",", "")) if found else None


def probe_github(owner: str, repo: str, auth: str | None) -> tuple[str, list[str]]:
    """Size, recognised licence and hardware-file tally for one repository."""
    meta = fetch(f"https://api.github.com/repos/{owner}/{repo}", auth)
    branch = meta["default_branch"]
    tree = fetch(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}"
        "?recursive=1",
        auth,
    )
    licence = (meta.get("license") or {}).get("spdx_id") or "none"
    blobs = [item for item in tree.get("tree", []) if item["type"] == "blob"]

    #: The extensions that decide the artefact columns, grouped as they print.
    classes = {
        "schematic source": (".sch", ".kicad_sch", ".schdoc", ".dsn"),
        "schematic pdf": (".pdf",),
        "pcb layout": (".kicad_pcb", ".brd", ".pcbdoc"),
        "footprint/symbol": (".kicad_mod", ".kicad_sym", ".lbr", ".lib", ".schlib", ".pcblib"),
        "3d": (".step", ".stp", ".wrl"),
    }
    tally = []
    for label, suffixes in classes.items():
        count = sum(1 for b in blobs if b["path"].lower().endswith(suffixes))
        if count:
            tally.append(f"{label}={count}")
    if tree.get("truncated"):
        tally.append("TREE TRUNCATED - counts are a lower bound")

    summary = f"size={meta['size']} KiB licence={licence} blobs={len(blobs)}"
    return summary, tally


def main() -> int:
    data = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    auth = token()
    print(f"surveyed {data['surveyed']}; probing {len(data['sources'])} sources"
          f" ({'authenticated' if auth else 'unauthenticated, 60 requests/hour'})")
    print()

    drifted = 0
    for source in data["sources"]:
        url = source["url"]
        print(f"{source['vendor']} - {source['source']}")
        match = GITHUB_REPO.match(url)
        if match:
            owner, repo = match.group(1), match.group(2)
            try:
                summary, tally = probe_github(owner, repo, auth)
            except Exception as error:  # noqa: BLE001 - reported, not swallowed
                print(f"  FAILED {owner}/{repo}: {type(error).__name__}: {error}")
                drifted += 1
                continue
            print(f"  observed {summary}")
            if tally:
                print(f"  artefacts {', '.join(tally)}")
            print(f"  recorded size={source['size']['value']}"
                  f" licence={source['licence']['value']}")
            was = recorded_number(source["size"]["value"])
            now = int(summary.split("size=")[1].split()[0])
            if was is not None and was != now:
                print(f"  DRIFT size recorded {was} KiB, now {now} KiB")
                drifted += 1
        else:
            status = reachable(url)
            print(f"  {status}  <- {url}")
            if source["licence"]["evidence"] == "unreachable" and "HTTP" in status:
                print("  DRIFT recorded unreachable, now answers -"
                      " this row can be filled in")
                drifted += 1
        print()

    print(f"{drifted} cell(s) need a person. sources.json was not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
