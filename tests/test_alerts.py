import json
import sqlite3

from aion2market import alerts
from aion2market.store import Store


def _store():
    s = Store(":memory:")
    s.set_name("1", "Pure Odyle")
    s.watch("1", 60000, 0)
    return s


def test_alert_cycle():
    s = _store()
    seq = [70000, 59000, 59000, 60000, 58000, 61000, 59500]
    fired = [[a.price for a in alerts.check(s, {"1": p}, i)] for i, p in enumerate(seq)]
    # first dip, no repeat at same/higher price, again on a further drop,
    # reset above target, alert again on the next dip
    assert fired == [[], [59000], [], [], [58000], [], [59500]]
    assert [r[2] for r in s.recent_alerts(10)] == [59500, 58000, 59000]


def test_unwatched_and_no_target_items_never_alert():
    s = _store()
    s.watch("2", None, 0)
    assert alerts.check(s, {"2": 1, "3": 1}, 0) == []


def test_favorite_without_target_alerts_well_under_its_usual_price():
    s = Store(":memory:")
    for i in range(10):
        s.add_snapshots(1000.0 + i, 12306, [("7", 100.0, 5)])         # usual price 100, home server 12306
    s.watch("7", None, 0)
    assert alerts.check(s, {"7": 85.0}, 2000.0) == []                  # 15 % under: not yet
    (a,) = alerts.check(s, {"7": 79.0}, 2001.0)                         # 21 % under: alert
    assert a.typical == 100.0 and a.target_price == 80.0 and "7 gün ortalamasının %21 altında" in a.text()
    assert alerts.check(s, {"7": 79.0}, 2002.0) == []                  # same price: no repeat
    s.watch("8", None, 0)
    assert alerts.check(s, {"8": 1.0}, 2003.0) == []                   # no history: no alert


def test_new_target_restarts_cycle():
    s = _store()
    alerts.check(s, {"1": 59000}, 0)
    s.watch("1", 59500, 1)
    assert [a.price for a in alerts.check(s, {"1": 59000}, 2)] == [59000]


def test_old_database_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE watchlist (item_key TEXT PRIMARY KEY, target_price REAL, added_ts REAL NOT NULL)")
    db.execute("INSERT INTO watchlist VALUES ('1', 100, 0)")
    db.commit()
    db.close()
    s = Store(path)
    assert s.watch_state("1") == (100, None)


def test_notifier_sends_alert_card_and_reports_errors(monkeypatch):
    shown = []
    monkeypatch.setattr(alerts.PopupHost, "show", lambda self, msg: shown.append(msg))
    monkeypatch.setattr(alerts, "discord_webhook", lambda url, text: (_ for _ in ()).throw(TimeoutError("slow")))
    n = alerts.Notifier(popup=True, discord_url="https://example.invalid/hook")
    errs = n(alerts.Alert("1", "Pure Odyle", 59000, 60000, 0))
    assert shown == [{"kind": "alert", "item": "Pure Odyle", "item_key": "1", "price": 59000,
                      "target": 60000, "ts": 0}]
    assert len(errs) == 1 and errs[0].startswith("Discord") and n.channels == ["Ekran", "Discord"]


def test_popup_host_streams_json_lines(monkeypatch):
    class FakeProc:
        def __init__(self, *a, **k):
            import io
            self.stdin = io.BytesIO()
            self.stdin.close = lambda: None
        def poll(self):
            return None
    monkeypatch.setattr(alerts.subprocess, "Popen", FakeProc)
    host = alerts.PopupHost()
    host.show({"kind": "info", "title": "Ş", "body": "x"})
    host.show({"kind": "info", "title": "b", "body": "y"})
    lines = host.proc.stdin.getvalue().decode("utf-8").splitlines()
    assert [json.loads(x)["title"] for x in lines] == ["Ş", "b"]
