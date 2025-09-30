import main as main_module


def test_main_starts_all_services(monkeypatch):
    calls = []

    def fake_runner(config, ready, stop_event):
        calls.append(config)
        ready.set()
        stop_event.wait(timeout=0.01)

    monkeypatch.setattr(
        main_module,
        "SERVICE_DEFINITIONS",
        [
            main_module.ServiceDefinition(
                name="Fake Service",
                description="stub",
                runner=fake_runner,
            ),
        ],
    )

    runtime = main_module.main(run_forever=False)

    assert len(calls) == 1
    runtime.stop_all()


def test_load_config_respects_environment(monkeypatch):
    monkeypatch.setenv("DUMP1090_HOST", "dump1090.local")
    monkeypatch.setenv("DUMP1090_RAW_PORT", "1234")
    monkeypatch.setenv("ADSB_WS_HOST", "0.0.0.0")
    monkeypatch.setenv("ADSB_WS_PORT", "9999")
    monkeypatch.setenv("ADSB_WS_URI", "ws://publisher.test:9999")
    monkeypatch.setenv("ADSB_DB_PATH", "/tmp/adsb.db")
    monkeypatch.setenv("ADSB_SAVE_INTERVAL", "2.5")
    monkeypatch.setenv("WAVETAP_API_HOST", "127.0.0.1")
    monkeypatch.setenv("WAVETAP_API_PORT", "5050")
    monkeypatch.setenv("WAVETAP_API_DEBUG", "true")
    monkeypatch.setenv("WAVETAP_API_THREADED", "false")

    config = main_module.load_config()

    assert config.publisher.dump1090_host == "dump1090.local"
    assert config.publisher.dump1090_port == 1234
    assert config.publisher.websocket_port == 9999
    assert config.subscriber.websocket_uri == "ws://publisher.test:9999"
    assert config.subscriber.db_path == "/tmp/adsb.db"
    assert config.subscriber.save_interval == 2.5
    assert config.api.host == "127.0.0.1"
    assert config.api.port == 5050
    assert config.api.debug is True
    assert config.api.threaded is False


def test_runtime_describe_services_includes_definitions(monkeypatch):
    fake_definition = main_module.ServiceDefinition(
        name="Demo Service",
        description="Demonstrates orchestration",
        runner=lambda *_: None,
    )
    monkeypatch.setattr(main_module, "SERVICE_DEFINITIONS", [fake_definition])

    runtime = main_module.WaveTapRuntime(main_module.load_config())
    summary = runtime.describe_services()

    assert "Demo Service" in summary
    assert "Demonstrates orchestration" in summary

    # Ensure describe_services falls back to actual handles once started
    def fake_runner(config, ready, stop_event):
        ready.set()
        stop_event.wait(timeout=0.01)

    monkeypatch.setattr(
        main_module,
        "SERVICE_DEFINITIONS",
        [main_module.ServiceDefinition("Demo Service", "Demonstrates orchestration", fake_runner)],
    )

    runtime = main_module.WaveTapRuntime(main_module.load_config())
    runtime.start_all()
    summary_after_start = runtime.describe_services()
    runtime.stop_all()

    assert summary_after_start.count("Demo Service") == 1
