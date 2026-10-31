import pytest

from aion2market import updates


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(updates, "_state", {"next_check": 0.0, "checking": False, "latest": None, "url": None})
    monkeypatch.setattr(updates, "__version__", "0.3.4")


@pytest.mark.parametrize("latest, current, newer", [
    ("v0.3.5", "0.3.4", True), ("v0.4.0", "0.3.10", True), ("v0.3.10", "0.3.9", True),
    ("v0.3.4", "0.3.4", False), ("v0.3.3", "0.3.4", False),
    ("v0.3.5", "dev", False), ("nightly", "0.3.4", False), (None, "0.3.4", False),
])
def test_is_newer(latest, current, newer):
    assert updates.is_newer(latest, current) is newer


def test_status_reports_a_newer_release_and_caches_it(monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "fetch", lambda: calls.append(1) or ("v0.3.5", "https://example.test/r"))
    s = updates.status(background=False)
    assert s == {"current": "0.3.4", "latest": "v0.3.5", "url": "https://example.test/r", "available": True}
    updates.status(background=False)
    assert len(calls) == 1                      # not asked again until CHECK_EVERY has passed


def test_status_survives_a_failed_check(monkeypatch):
    def boom():
        raise OSError("offline")
    monkeypatch.setattr(updates, "fetch", boom)
    assert updates.status(background=False)["available"] is False
    assert updates._state["checking"] is False
