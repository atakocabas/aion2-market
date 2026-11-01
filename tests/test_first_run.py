"""What a fresh install on another computer runs into: no key file, failed capture, unreachable sources."""
import http.client

from aion2market import app, dashboard, iteminfo, service, sync
from aion2market.store import Store


def test_failed_live_capture_falls_back_to_background_sources(tmp_path, monkeypatch):
    db, stop = tmp_path / "market.db", tmp_path / "app.stop"
    background = []

    def broken(argv):
        raise RuntimeError("Npcap admin-only mode")
    monkeypatch.setattr(service, "main", broken)
    monkeypatch.setattr(service, "run_background", lambda d, s: background.append(d))
    app.run_service(db, stop, tmp_path / "keys.log")
    assert background == [db]
    s = Store(db)
    assert "admin-only" in dashboard.npcap_status(s)["error"]


def test_declined_key_file_still_runs_background_sources(tmp_path, monkeypatch):
    db, background = tmp_path / "market.db", []
    monkeypatch.setattr(service, "main", lambda argv: (_ for _ in ()).throw(AssertionError("no live capture")))
    monkeypatch.setattr(service, "run_background", lambda d, s: background.append(d))
    app.run_service(db, tmp_path / "app.stop", None)
    assert background == [db] and Store(db).get_meta("capture.error")


def test_capture_status_is_cleared_when_working():
    s = Store(":memory:")
    service.set_capture_status(s, service.KEYLOG_MISSING)
    assert dashboard.npcap_status(s)["error"] == service.KEYLOG_MISSING
    service.set_capture_status(s, None)
    assert dashboard.npcap_status(s)["error"] is None


def test_background_loop_survives_unexpected_errors(tmp_path, capsys):
    calls = []

    def body(store):
        calls.append(1)
        raise KeyError("surprise")
    service._once("Deneme", tmp_path / "m.db", body)
    service._once("Deneme", tmp_path / "m.db", body)
    assert len(calls) == 2 and "beklenmeyen hata" in capsys.readouterr().out


def test_unreachable_name_source_is_shown_and_cleared():
    s = Store(":memory:")
    s.add_snapshots(1000.0, 1, [(str(k), 1.0, 1) for k in range(100000001, 100000008)])

    def down(key):
        raise http.client.IncompleteRead(b"")             # not an OSError: used to end the name thread
    assert iteminfo.fill_missing(s, delay=0, fetcher=down) == (0, 0, 5)
    assert "IncompleteRead" in dashboard.npcap_status(s)["names_error"]
    iteminfo.fill_missing(s, delay=0, fetcher=lambda key: None)
    assert dashboard.npcap_status(s)["names_error"] is None


def test_share_client_turns_protocol_errors_into_share_errors(monkeypatch):
    def cut(*a, **k):
        raise http.client.RemoteDisconnected("closed")
    monkeypatch.setattr(sync.urllib.request, "urlopen", cut)
    try:
        sync.ShareClient("https://x", "k").request("GET", "/v1/servers")
    except sync.ShareError as e:
        assert "closed" in str(e)
    else:
        raise AssertionError("no ShareError")


def test_market_interfaces_adds_the_route_to_the_market(monkeypatch):
    import socket

    from aion2market import capture
    monkeypatch.setattr(socket, "gethostbyname", lambda h: "1.2.3.4")
    monkeypatch.setattr(capture, "_route_iface", lambda ip: "VPN")
    assert service.market_interfaces("Ethernet") == ["Ethernet", "VPN"]
    monkeypatch.setattr(capture, "_route_iface", lambda ip: "Ethernet")
    assert service.market_interfaces("Ethernet") == ["Ethernet"]
