from backend.services.run_timeline import RunTimeline, sanitize_url


def test_timeline_sanitizes_urls_and_secrets() -> None:
    assert sanitize_url("https://example.test/entry?token=secret#fragment") == "https://example.test/entry"
    timeline = RunTimeline(run_id="run-1")
    event = timeline.emit("run", "RUN_CREATED", "success", url="https://example.test/a?password=secret")
    assert event["url"] == "https://example.test/a"


def test_external_entry_bootstrap_main_order() -> None:
    events: list[str] = []
    timeline = RunTimeline(run_id="run-2")
    timeline.emit = lambda stage, event, status, **details: (events.append(event) or {})  # type: ignore[method-assign]
    timeline.emit("run", "RUN_CREATED", "success")
    timeline.emit("external_entry", "EXTERNAL_ENTRY_STARTED", "started")
    timeline.emit("external_entry", "EXTERNAL_ENTRY_COMPLETED", "success")
    timeline.emit("access_bootstrap", "BOOTSTRAP_STARTED", "started")
    timeline.emit("access_bootstrap", "BOOTSTRAP_COMPLETED", "success")
    timeline.emit("main_graph", "MAIN_GRAPH_STARTED", "started")
    assert events.index("BOOTSTRAP_COMPLETED") < events.index("MAIN_GRAPH_STARTED")


def test_waiting_events_are_coalesced() -> None:
    events: list[str] = []
    timeline = RunTimeline(run_id="run-3", heartbeat_seconds=60)
    timeline.emit = lambda stage, event, status, **details: (events.append(event) or {})  # type: ignore[method-assign]
    timeline.waiting("selector")
    timeline.waiting("selector")
    assert events == ["WAITING_EXTERNAL_SYSTEM"]
