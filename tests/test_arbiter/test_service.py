from arbiter import service


def setup_function():
    service.app.config.update(TESTING=True)
    service._reset_for_testing()


def test_register_and_activate_module():
    client = service.app.test_client()

    response = client.post("/modules/adsb", json={"description": "ADS-B ingest"})
    assert response.status_code == 201
    payload = response.get_json()
    assert payload["name"] == "adsb"
    assert payload["description"] == "ADS-B ingest"
    assert payload["active"] is False

    activate = client.post("/modules/adsb/activate")
    assert activate.status_code == 200
    data = activate.get_json()
    assert data["active_module"] == "adsb"
    assert data["status"]["active"] is True

    status = client.get("/status").get_json()
    assert status["active"] == "adsb"
    assert "adsb" in status["registered"]


def test_reject_duplicate_registration():
    client = service.app.test_client()

    first = client.post("/modules/fm")
    assert first.status_code == 201

    second = client.post("/modules/fm")
    assert second.status_code == 409


def test_delete_module_and_stop():
    client = service.app.test_client()
    client.post("/modules/am")
    client.post("/modules/am/activate")
    stop = client.post("/modules/stop-active")
    assert stop.status_code == 202
    assert stop.get_json()["stopped"] == "am"

    delete = client.delete("/modules/am")
    assert delete.status_code == 204

    status = client.get("/status").get_json()
    assert status["active"] is None
    assert "am" not in status["registered"]
