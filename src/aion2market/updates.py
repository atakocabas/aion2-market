"""Whether a newer release is out on GitHub; the window shows it next to the version.

The check runs in the background (at most every few hours) so the window never waits on it.
Only the public releases API is asked; nothing is sent about this computer.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Any

from . import __version__

RELEASES_URL = "https://api.github.com/repos/atakocabas/aion2-market/releases/latest"
CHECK_EVERY = 6 * 3600
RETRY_AFTER = 30 * 60      # after a failed check
TIMEOUT = 10

_lock = threading.Lock()
_state: dict[str, Any] = {"next_check": 0.0, "checking": False, "latest": None, "url": None}


def parse(version: str | None) -> tuple[int, ...] | None:
    """'v0.3.4' -> (0, 3, 4); None for anything that isn't a plain dotted version (e.g. 'dev')."""
    parts = (version or "").strip().lstrip("vV").split(".")
    return tuple(int(p) for p in parts) if all(p.isdigit() for p in parts) else None


def is_newer(latest: str | None, current: str | None = None) -> bool:
    a, b = parse(latest), parse(current or __version__)
    return a is not None and b is not None and a > b


def fetch() -> tuple[str, str]:
    """(version, release page) of the latest release."""
    req = urllib.request.Request(RELEASES_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"aion2market/{__version__}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["tag_name"], data["html_url"]


def _check() -> None:
    try:
        latest, url = fetch()
        found, wait = {"latest": latest, "url": url}, CHECK_EVERY
    except Exception:          # offline, rate-limited, no release yet: try again later
        found, wait = {}, RETRY_AFTER
    with _lock:
        _state.update(found, checking=False, next_check=time.time() + wait)


def status(now: float | None = None, background: bool = True) -> dict:
    """{"current", "latest", "url", "available"}; starts a check when the last one is old."""
    now = now or time.time()
    with _lock:
        start = not _state["checking"] and now >= _state["next_check"]
        if start:
            _state["checking"] = True
        latest, url = _state["latest"], _state["url"]
    if start:
        if background:
            threading.Thread(target=_check, daemon=True).start()
        else:
            _check()
            return status(now, background)
    return {"current": __version__, "latest": latest, "url": url, "available": is_newer(latest)}
