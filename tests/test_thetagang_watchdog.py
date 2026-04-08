import asyncio


_GRID_CONFIG = """
[meta]
schema_version = 2

[run]
strategies = ["grid"]

[runtime.account]
number = "DU99999"
margin_usage = 0.5

[runtime.option_chains]
expirations = 4
strikes = 10

[runtime.database]
enabled = false

[strategies.grid.symbols.SPY]
lower_bound = 400.0
upper_bound = 600.0
grid_spacing = 5.0
spread_width = 5.0
max_loss_per_symbol = 5000.0
max_exposure_per_symbol = 10000.0
"""


def test_watchdog_runs_inside_task(monkeypatch, tmp_path):
    import thetagang.thetagang as tg

    config_path = tmp_path / "thetagang.toml"
    config_path.write_text(_GRID_CONFIG, encoding="utf8")

    loop = asyncio.new_event_loop()
    monkeypatch.setattr(tg.util, "getLoop", lambda: loop)
    monkeypatch.setattr(tg, "need_to_exit", lambda *_: False)

    captured = {}

    class DummyEvent:
        def __init__(self):
            self._handlers = []

        def __iadd__(self, handler):
            self._handlers.append(handler)
            return self

        def __isub__(self, handler):
            self._handlers.remove(handler)
            return self

    class FakeContract:
        def __init__(self, **_kwargs):
            pass

    class FakeIBC:
        def __init__(self, tws_version, **_kwargs):
            self.twsVersion = tws_version
            self.terminated = False
            captured["ibc"] = self

        async def terminateAsync(self):
            self.terminated = True

    class FakeWatchdog:
        def __init__(self, *_args, **_kwargs):
            self.started = False
            self.stopped = False
            captured["watchdog"] = self

        def start(self):
            assert asyncio.get_running_loop() is loop
            self.started = True

        def stop(self):
            self.stopped = True

    class FakeIB:
        def __init__(self):
            self.connectedEvent = DummyEvent()
            self.RaiseRequestErrors = False

        def run(self, awaitable):
            assert asyncio.iscoroutine(awaitable)
            loop.run_until_complete(awaitable)
            loop.stop()
            loop.close()

    class FakePortfolioManager:
        def __init__(
            self,
            _config,
            _ib,
            completion_future,
            _dry_run,
            data_store=None,
            run_stage_flags=None,
            run_stage_order=None,
        ):
            if not completion_future.done():
                completion_future.set_result(True)

    monkeypatch.setattr(tg, "IBC", FakeIBC)
    monkeypatch.setattr(tg, "Watchdog", FakeWatchdog)
    monkeypatch.setattr(tg, "IB", FakeIB)
    monkeypatch.setattr(tg, "PortfolioManager", FakePortfolioManager)
    monkeypatch.setattr(tg, "Contract", FakeContract)

    tg.start(str(config_path), without_ibc=False, dry_run=True)

    assert captured["watchdog"].started is True
    assert captured["watchdog"].stopped is True
    assert captured["ibc"].terminated is True
