#!/usr/bin/env python3
"""Process-level singleton lock for fleet Discord bots.

Two systemd units historically launched the same bot script (e.g.
architect-bot.service AND schubert-architect.service). Discord then
delivered every message to both gateway sessions, so the operator saw
duplicate replies.

Acquire this lock at process start. A second copy exits 0 so systemd
Restart=always does not crash-loop against a healthy primary.
"""

from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path
from typing import IO, Optional

LOCK_DIRS = (
    Path("/run/schubert-fleet"),
    Path("/tmp/schubert-fleet"),
)


def _open_lockfile(name: str) -> IO[str]:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name)
    last_err: Optional[Exception] = None
    for directory in LOCK_DIRS:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{safe}.lock"
            fh = open(path, "w", encoding="utf-8")
            return fh
        except OSError as exc:
            last_err = exc
            continue
    raise RuntimeError(f"Could not create singleton lock for {name}: {last_err}")


def acquire_singleton(name: str) -> IO[str]:
    """Take an exclusive flock for this bot. Exit 0 if another copy holds it."""
    fh = _open_lockfile(name)
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        held_by = fh.read().strip() or "unknown"
        print(
            f"Another {name} instance already running (pid {held_by}, lock {fh.name}). Exiting.",
            file=sys.stderr,
            flush=True,
        )
        try:
            fh.close()
        except OSError:
            pass
        sys.exit(0)
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh