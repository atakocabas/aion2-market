"""Price alerts for watched items: decide when to notify, and deliver notifications.

An item alerts when its observed unit price is at or below its target, and
again only if the price drops further. Once the price is back above target the
cycle resets, so the next dip alerts again. A favorite without a target uses
FAVORITE_DEAL_DISCOUNT under its own 7-day average as the target.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.request
from dataclasses import dataclass

from .store import Store

FAVORITE_DEAL_DISCOUNT = 0.20     # favorites without a target alert at 20 % under their 7-day average


@dataclass(frozen=True)
class Alert:
    item_key: str
    name: str | None
    price: float
    target_price: float
    ts: float
    typical: float | None = None      # set for favorite-deal alerts (no target of the user's own)

    @property
    def label(self) -> str:
        return self.name or self.item_key

    def text(self) -> str:
        from .market import fmt_price
        if self.typical:
            below = (self.typical - self.price) / self.typical * 100
            return (f"{self.label}: birim fiyat {fmt_price(self.price)}, 7 gün ortalamasının %{below:.0f} altında "
                    f"(7 gün ort. {fmt_price(self.typical)})")
        return (f"{self.label}: birim fiyat {fmt_price(self.price)} "
                f"(hedef {fmt_price(self.target_price)})")


def favorite_threshold(store: Store, key: str, ts: float) -> tuple[float, float] | None:
    """(alert price, 7-day average) for a favorite without a target, or None without enough history."""
    from .dashboard import typical_price
    history = store.snapshot_history(key, ts - 30 * 86400, store.home_server())
    avg = typical_price([(t, p) for t, p, _ in history], ts)
    return (avg * (1 - FAVORITE_DEAL_DISCOUNT), avg) if avg else None


def check(store: Store, prices: dict[str, float], ts: float) -> list[Alert]:
    """Compare freshly observed unit prices with the watchlist; record and return new alerts."""
    alerts = []
    for key, price in prices.items():
        state = store.watch_state(key)
        if state is None:
            continue
        target, last = state
        typical = None
        if target is None:
            threshold = favorite_threshold(store, key, ts)
            if threshold is None:
                continue
            target, typical = threshold
        if price > target:
            if last is not None:
                store.set_last_alert(key, None)
            continue
        if last is not None and price >= last:
            continue
        store.set_last_alert(key, price)
        store.add_alert(ts, key, price, target)
        alerts.append(Alert(key, store.name(key), price, target, ts, typical))
    return alerts


class PopupHost:
    """Keeps one ``aion2market.popup`` process alive and streams card messages to it."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()          # packet loop and sync thread both send cards

    def show(self, msg: dict) -> None:
        with self.lock:
            self._show(msg)

    def _show(self, msg: dict) -> None:
        line = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        for _ in range(2):                                  # restart once if the window process died
            if self.proc is None or self.proc.poll() is not None:
                # In the released exe sys.executable is the app itself (see app.py).
                cmd = [sys.executable, "--popup"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "aion2market.popup"]
                self.proc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            assert self.proc.stdin is not None          # started with stdin=PIPE
            try:
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
                return
            except OSError:
                self.proc = None
        raise OSError("bildirim penceresi başlatılamadı")

    def close(self, wait: float = 0) -> int | None:
        """Let the window finish its cards and exit; returns its exit code when waited for."""
        if self.proc is None:
            return None
        assert self.proc.stdin is not None              # started with stdin=PIPE
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        return self.proc.wait(wait) if wait else None


def discord_webhook(url: str, text: str) -> None:
    req = urllib.request.Request(url, data=json.dumps({"content": text}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "aion2market"})
    urllib.request.urlopen(req, timeout=10).close()


class Notifier:
    """Sends each alert to every configured channel; a failing channel never stops the service."""

    def __init__(self, popup: bool = True, discord_url: str | None = None):
        self.popup = PopupHost() if popup else None
        self.discord_url = discord_url

    @property
    def channels(self) -> list[str]:
        return (["Ekran"] if self.popup else []) + (["Discord"] if self.discord_url else [])

    def _send(self, card: dict, title: str, body: str) -> list[str]:
        errors = []
        if self.popup:
            try:
                self.popup.show(card)
            except OSError as e:
                errors.append(f"Ekran bildirimi: {e}")
        if self.discord_url:
            try:
                discord_webhook(self.discord_url, f"**{title}**\n{body}")
            except Exception as e:  # network errors of every kind
                errors.append(f"Discord: {e}")
        return errors

    def info(self, title: str, body: str) -> list[str]:
        return self._send({"kind": "info", "title": title, "body": body}, title, body)

    def __call__(self, alert: Alert) -> list[str]:
        card = {"kind": "alert", "item": alert.label, "item_key": alert.item_key,
                "price": alert.price, "target": alert.target_price, "ts": alert.ts}
        if alert.typical:
            card["typical"] = alert.typical
        title = "Aion 2 market: favori fırsatı" if alert.typical else "Aion 2 market: hedef fiyat"
        return self._send(card, title, alert.text())

    def close(self, wait: float = 0) -> list[str]:
        """Release the popup window; when waiting, report if it crashed."""
        if not self.popup:
            return []
        try:
            code = self.popup.close(wait)
        except subprocess.TimeoutExpired:
            return []
        return [f"Ekran bildirimi: pencere süreci {code} koduyla kapandı"] if code else []
