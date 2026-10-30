"""Find the game process and its open TCP connections."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import psutil

DEFAULT_PROCESS_PATTERN = r"aion"


@dataclass(frozen=True)
class ConnKey:
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int

    def label(self) -> str:
        rip = self.remote_ip.replace(":", "_")
        return f"{self.local_port}-{rip}_{self.remote_port}"


def find_game_pids(pattern: str = DEFAULT_PROCESS_PATTERN) -> dict[int, str]:
    """Return {pid: process name} for processes whose name matches pattern."""
    rx = re.compile(pattern, re.IGNORECASE)
    me = os.getpid()
    found = {}
    for p in psutil.process_iter(["pid", "name"]):
        name = p.info.get("name") or ""
        if p.info["pid"] != me and rx.search(name):
            found[p.info["pid"]] = name
    return found


def _is_loopback(ip: str) -> bool:
    return ip.startswith("127.") or ip == "::1"


def game_connections(pids: set[int], exclude_ports: set[int] = frozenset()) -> set[ConnKey]:
    """Established TCP connections owned by the given pids.

    Loopback connections are kept because tunnelling tools (ExitLag, etc.)
    run a local proxy and the game talks to it over 127.0.0.1; only sockets
    between the game's own threads/processes are dropped.
    """
    items = []
    for pid in pids:
        try:
            items += psutil.Process(pid).net_connections(kind="tcp")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    own_ports = {c.laddr.port for c in items if c.laddr}
    conns = set()
    for c in items:
        if c.status != psutil.CONN_ESTABLISHED or not c.raddr:
            continue
        if c.raddr.port in exclude_ports:
            continue
        if _is_loopback(c.raddr.ip) and c.raddr.port in own_ports:
            continue
        conns.add(ConnKey(c.laddr.ip, c.laddr.port, c.raddr.ip, c.raddr.port))
    return conns
