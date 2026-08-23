#!/usr/bin/env python3
# OpenHardware — start the simulator and the web UI, detached.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Bring the whole local stack up, and leave it up.

    python webui/run_local.py            start both, print the URL
    python webui/run_local.py --stop     stop both
    python webui/run_local.py --status   report what is running

**Why this exists, and why it is Python rather than a shell script.**

The bridge must outlive whatever started it. Started from an agent session, an
SSH session, or a console that later closes, it dies with its parent -- and the
page then shows nothing while every server-side check still passes, because the
check and the server were the same short-lived thing. That failure cost most of
an afternoon and was invisible from the server side.

The first version of this was a `.cmd`, and it lost three separate fights with
shell quoting: `timeout` refuses to run with stdin redirected, `start /b` shares
the console it was told to escape, and the launch command -- itself a shell
command full of nested quotes -- was mangled by every shell it passed through.
Python spawns with an argv list, so none of those exist here.

Paths assume PICSimLab is built in WSL at /root/oh, which is what
`docs/HANDOFF_2026-08-12_openhardware.md` describes. Override with the flags.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "distro": "Ubuntu-22.04",
    "sim_dir": "/root/oh/src",
    "share": "/root/oh/share",
    "workspace": "/root/oh/tests/blink/blink.pzw",
    "ws_port": 8787,
    "rcontrol_port": 5000,
}


def detached(argv: list[str], env: dict | None = None) -> subprocess.Popen:
    """Spawn a process that survives this one.

    On Windows that needs both DETACHED_PROCESS (no shared console, so closing
    ours does not signal it) and CREATE_NEW_PROCESS_GROUP (no shared Ctrl-C).
    Neither flag exists elsewhere, hence the guard rather than a platform test.
    """
    options: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "cwd": REPO,
    }
    if env is not None:
        options["env"] = env
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        flags |= getattr(subprocess, name, 0)
    if flags:
        options["creationflags"] = flags
    else:  # POSIX: leave the process group so a closing terminal cannot reach it
        options["start_new_session"] = True
    return subprocess.Popen(argv, **options)


def wsl(distro: str, script: str) -> list[str]:
    """A `bash -lc` argv for WSL. The script stays one argument."""
    return ["wsl", "-d", distro, "--", "bash", "-lc", script]


def simulator_running(distro: str) -> bool:
    # `-x`, not `-f`: with `-f` the probe's own command line contains the word
    # and it matches itself.
    return (
        subprocess.run(
            ["wsl", "-d", distro, "--", "pgrep", "-x", "picsimlab"],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )


def listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def start_simulator(opts) -> bool:
    if simulator_running(opts.distro):
        print("  simulator already running")
        return True
    # `exec`, and no trailing `&`. Backgrounding inside WSL returns 0 and leaves
    # no process: when the foreground command of a WSL session returns, the
    # session is torn down and its background children go with it. Holding the
    # process from out here is what keeps it alive.
    detached(
        wsl(
            opts.distro,
            f"cd {opts.sim_dir} && DISPLAY=:0 exec ./picsimlab '{opts.workspace}'",
        )
    )
    for _ in range(20):
        time.sleep(1.0)
        if simulator_running(opts.distro):
            print("  simulator up")
            return True
    print("  FAILED: no picsimlab process.", file=sys.stderr)
    print(
        "  Check /root/.picsimlab/picsimlab_log0.txt -- several demo workspaces "
        "segfault this build (docs/known-issues.md 4a-ter).",
        file=sys.stderr,
    )
    return False


def start_bridge(opts) -> bool:
    if listening(opts.ws_port):
        print(f"  bridge already listening on {opts.ws_port}")
        return True

    # The launch command goes through the environment rather than argv: it is a
    # shell command full of nested quotes, and it only has to survive being
    # read, not parsed by anything in between.
    env = dict(os.environ)
    env["OPENHARDWARE_SIM_COMMAND"] = (
        f"wsl -d {opts.distro} -- bash -lc \"pkill -x picsimlab; sleep 2; "
        f"cd {opts.sim_dir} && DISPLAY=:0 exec ./picsimlab "
        f"'{opts.share}/boards/{{board}}/demo.pzw'\""
    )

    detached(
        [
            sys.executable,
            os.path.join("webui", "bridge.py"),
            "--rcontrol-port",
            str(opts.rcontrol_port),
            "--ws-port",
            str(opts.ws_port),
        ],
        env=env,
    )
    for _ in range(15):
        time.sleep(1.0)
        if listening(opts.ws_port):
            print(f"  bridge up on {opts.ws_port}")
            return True
    print(f"  FAILED: nothing listening on {opts.ws_port}", file=sys.stderr)
    return False


def verify(opts) -> bool:
    """Fetch the page the way a browser would, not the way a script does."""
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{opts.ws_port}/",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read()
        print(f"  page: {response.status}, {len(body)} bytes")
        return response.status == 200 and b"OpenHardware" in body
    except OSError as exc:
        print(f"  page: FAILED {exc}", file=sys.stderr)
        return False


def stop(opts) -> int:
    if listening(opts.ws_port):
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-NetTCPConnection -LocalPort {opts.ws_port} -State Listen "
                f"-EA SilentlyContinue | ForEach-Object "
                f"{{ Stop-Process -Id $_.OwningProcess -Force -EA SilentlyContinue }}",
            ],
            capture_output=True,
        )
        print("  bridge stopped")
    else:
        print("  bridge was not running")
    subprocess.run(
        ["wsl", "-d", opts.distro, "--", "pkill", "-x", "picsimlab"],
        capture_output=True,
    )
    print("  simulator stopped")
    return 0


def status(opts) -> int:
    print(f"  simulator : {'running' if simulator_running(opts.distro) else 'down'}")
    print(f"  bridge    : {'listening' if listening(opts.ws_port) else 'down'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--distro", default=DEFAULTS["distro"])
    parser.add_argument("--sim-dir", default=DEFAULTS["sim_dir"])
    parser.add_argument("--share", default=DEFAULTS["share"])
    parser.add_argument("--workspace", default=DEFAULTS["workspace"])
    parser.add_argument("--ws-port", type=int, default=DEFAULTS["ws_port"])
    parser.add_argument(
        "--rcontrol-port", type=int, default=DEFAULTS["rcontrol_port"]
    )
    opts = parser.parse_args(argv)

    if opts.stop:
        return stop(opts)
    if opts.status:
        return status(opts)

    print("Starting the simulator...")
    if not start_simulator(opts):
        return 1
    print("Starting the bridge...")
    if not start_bridge(opts):
        return 1
    print("Verifying...")
    if not verify(opts):
        return 1

    url = f"http://127.0.0.1:{opts.ws_port}"
    print(f"\n  {url}/                the UI")
    print(f"  {url}/selftest.html   browser-side self test\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
