import json
import urllib.parse

from aion2market import dashboard, sync
from aion2market.store import Store

NOW = 1_800_000_000.0


class FakeCloud:
    """In-memory stand-in for cloud/src/index.js with the same request/response shapes."""

    def __init__(self):
        self.snapshots, self.listings, self.servers = [], [], {}

    def client(self, key):
        cloud = self

        class C(sync.ShareClient):
            def request(self, method, path, body=None):
                return cloud.handle(method, path, json.loads(json.dumps(body)) if body else None)
        return C("https://fake", key)

    def handle(self, method, path, body):
        p, _, q = path.partition("?")
        since = int(urllib.parse.parse_qs(q).get("since", ["0"])[0])
        if p == "/v1/upload":
            for r in body.get("snapshots", []):
                if not any(x[1:4] == [r[0], r[1], r[2]] for x in self.snapshots):
                    self.snapshots.append([len(self.snapshots) + 1, *r])
            for r in body.get("listings", []):
                self.listings.append([len(self.listings) + 1, *r])
            return {}
        if p in ("/v1/snapshots", "/v1/listings"):
            rows = [r for r in getattr(self, p[4:]) if r[0] > since][:2]          # tiny pages
            more = len([r for r in getattr(self, p[4:]) if r[0] > since]) > 2
            return {"rows": rows, "next": rows[-1][0] if rows else since, "more": more}
        if p == "/v1/servers":
            return {"servers": [{"server_id": k, "name": v} for k, v in self.servers.items()]}
        raise AssertionError(path)


def test_two_users_share_prices_without_echoing_back():
    cloud = FakeCloud()
    cloud.servers[12306] = "Ortak ad"
    a, b = Store(":memory:"), Store(":memory:")
    a.add_snapshots(NOW - 60, 12306, [("1", 100.0, 3), ("2", 50.0, 1), ("3", 9.0, 9)])
    a.add_listings(NOW - 60, 12306, [{"sale_id": "AB-1", "game_item_key": "1", "game_item_quantity": "1",
                                      "sale_price": "100", "unit_price": "100.0"}])
    b.add_snapshots(NOW - 30, 22306, [("1", 70.0, 2)])                 # B plays on another server

    sync.sync_once(a, cloud.client("ka"), now=NOW)
    sync.sync_once(b, cloud.client("kb"), now=NOW)
    sync.sync_once(a, cloud.client("ka"), now=NOW)

    assert b.latest_snapshot("1", 12306)[1] == 100 and b.latest_snapshot("1", 22306)[1] == 70
    assert b.latest_listings("1", 12306)[1] == [(1, 100, 100.0)]
    assert a.latest_snapshot("1", 22306)[1] == 70                     # A got B's server too
    assert len(cloud.snapshots) == 4                                   # shared rows are never re-uploaded
    assert b.home_server() == 22306 and a.home_server() == 12306
    assert {s["server_id"]: s["name"] for s in b.servers()}[12306] == "Ortak ad"
    rows = dashboard.item_rows(b, NOW)
    assert rows["server_id"] == 22306 and [r["item_key"] for r in rows["items"]] == ["1"]
    assert len(dashboard.item_rows(b, NOW, 12306)["items"]) == 3


def test_shared_prices_alert_only_for_own_server_and_fresh_data():
    cloud = FakeCloud()
    me, other = Store(":memory:"), Store(":memory:")
    me.add_snapshots(NOW - 3600, 12306, [("1", 100.0, 3)])
    me.watch("1", 90, 0)
    other.add_snapshots(NOW - 10, 12306, [("1", 85.0, 4)])            # fresh, my server, below target
    other.add_snapshots(NOW - 10, 22306, [("1", 10.0, 4)])            # another server: ignored
    other.add_snapshots(NOW - 7200, 12306, [("1", 80.0, 4)])          # stale: ignored
    sync.sync_once(other, cloud.client("o"), now=NOW)
    sent = []
    lines = sync.sync_once(me, cloud.client("m"), notifier=lambda a: sent.append(a) or [], now=NOW)
    assert [a.price for a in sent] == [85.0] and any("ortak veri" in l for l in lines)


def test_errors_are_recorded_not_raised():
    s = Store(":memory:")

    class Down(sync.ShareClient):
        def request(self, *a, **k):
            raise sync.ShareError("HTTP 401 invalid key")
    lines = sync.sync_once(s, Down("https://x", "k"), now=NOW)
    assert "401" in lines[0] and s.get_meta("sync.last_error") == "HTTP 401 invalid key"
    assert dashboard.sync_status(s)["last_error"] == "HTTP 401 invalid key"


def test_first_use_registers_a_key_and_the_switch_stops_syncing(monkeypatch):
    s = Store(":memory:")
    monkeypatch.delenv("AION2_SHARE_URL", raising=False)
    monkeypatch.delenv("AION2_SHARE_KEY", raising=False)
    monkeypatch.setattr(sync, "DEFAULT_URL", "https://store.example")
    calls = []

    def fake_request(self, method, path, body=None):
        calls.append((self.url, self.key, method, path))
        return {"id": 7, "key": "a2m_new"}
    monkeypatch.setattr(sync.ShareClient, "request", fake_request)

    assert sync.client_from(s) is None                                  # no key yet
    client = sync.ensure_client(s, now=NOW)
    assert calls == [("https://store.example", "", "POST", "/v1/register")]
    assert client.key == "a2m_new" and s.get_meta("sync.key") == "a2m_new"
    assert sync.ensure_client(s, now=NOW).key == "a2m_new" and len(calls) == 1   # registers only once

    sync.set_enabled(s, False)
    assert sync.ensure_client(s, now=NOW) is None
    assert dashboard.sync_status(s) | {"last_ok": None} == {
        "configured": True, "enabled": False, "last_ok": None, "last_error": None}
    sync.set_enabled(s, True)
    assert sync.client_from(s).key == "a2m_new"                         # the key survives switching off


def test_failed_registration_waits_before_retrying(monkeypatch):
    s = Store(":memory:")
    monkeypatch.delenv("AION2_SHARE_URL", raising=False)
    monkeypatch.setattr(sync, "DEFAULT_URL", "https://store.example")
    calls = []

    def down(self, *a, **k):
        calls.append(1)
        raise sync.ShareError("HTTP 429 too many registrations today")
    monkeypatch.setattr(sync.ShareClient, "request", down)
    assert sync.ensure_client(s, now=NOW) is None and "429" in s.get_meta("sync.last_error")
    assert sync.ensure_client(s, now=NOW + 60) is None and len(calls) == 1
    sync.ensure_client(s, now=NOW + sync.REGISTER_RETRY + 1)
    assert len(calls) == 2


def test_no_built_in_store_means_nothing_happens(monkeypatch):
    s = Store(":memory:")
    monkeypatch.delenv("AION2_SHARE_URL", raising=False)
    monkeypatch.setattr(sync, "DEFAULT_URL", "")
    assert sync.ensure_client(s, now=NOW) is None and not dashboard.sync_status(s)["configured"]
