import asyncio

import pytest

import main as main_module


def test_main_starts_subscriber(monkeypatch):
    events = {}

    class DummySubscriber:
        def __init__(self, uri):
            events["uri"] = uri

        def setup_db(self):
            events["setup"] = True

        async def save_to_db(self):
            events["saves"] = events.get("saves", 0) + 1

        async def connect_and_listen(self):
            events["connected"] = True

    async def fake_sleep(_):
        raise asyncio.CancelledError

    monkeypatch.setattr(main_module, "ADSBSubscriber", DummySubscriber)
    monkeypatch.setattr(main_module.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_module.main())

    assert events["uri"] == "ws://127.0.0.1:8443"
    assert events["setup"]
    assert events["saves"] == 1
    assert events["connected"]
