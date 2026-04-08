import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

import thetagang.db as db_module
from thetagang.db import (
    DataStore,
    HistoricalBar,
    OrderIntent,
    OrderRecord,
    run_migrations,
    sqlite_db_path,
)


def test_data_store_records_executions(tmp_path) -> None:
    from sqlalchemy import select
    from thetagang.db import ExecutionRecord

    db_path = tmp_path / "state.db"
    data_store = DataStore(
        f"sqlite:///{db_path}",
        str(tmp_path / "thetagang.toml"),
        dry_run=False,
        config_text="test",
    )

    fills = [
        SimpleNamespace(
            execution=SimpleNamespace(
                execId="1",
                orderRef="tg:grid-spread:SPY:bull_put:480.00:20241220",
                time=datetime(2024, 1, 5, 12, 0, 0),
            ),
            contract=SimpleNamespace(symbol="SPY"),
            time=datetime(2024, 1, 5, 12, 0, 0),
        ),
    ]

    data_store.record_executions(fills)

    with data_store.session_scope() as session:
        rows = session.execute(select(ExecutionRecord)).scalars().all()
        assert len(rows) == 1
        assert rows[0].order_ref == "tg:grid-spread:SPY:bull_put:480.00:20241220"


def test_sqlite_db_path_parses(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    assert sqlite_db_path(f"sqlite:///{db_path}") == db_path
    assert sqlite_db_path("sqlite:///:memory:") is None
    assert sqlite_db_path("postgresql://localhost/db") is None


def test_run_migrations_restores_existing_db(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "state.db"
    sqlite3.connect(db_path).execute("create table t (id integer);").close()
    before = db_path.read_bytes()

    def _boom(*_args, **_kwargs) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(db_module, "_run_alembic_upgrade", _boom)

    try:
        run_migrations(f"sqlite:///{db_path}")
    except RuntimeError:
        pass

    after = db_path.read_bytes()
    assert before == after


def test_run_migrations_cleans_temp_on_failure(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "state.db"
    temp_path = Path(str(db_path) + ".tmp")

    def _boom(*_args, **_kwargs) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(db_module, "_run_alembic_upgrade", _boom)

    try:
        run_migrations(f"sqlite:///{db_path}")
    except RuntimeError:
        pass

    assert not db_path.exists()
    assert not temp_path.exists()


def test_record_historical_bars_upserts_and_parses_dates(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    data_store = DataStore(
        f"sqlite:///{db_path}",
        str(tmp_path / "thetagang.toml"),
        dry_run=False,
        config_text="test",
    )

    bars = [
        SimpleNamespace(
            date="20240105",
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            volume=10,
            barCount=1,
            average=1.2,
        )
    ]
    data_store.record_historical_bars("AAA", "1 day", bars)

    updated_bars = [
        SimpleNamespace(
            date="20240105",
            open=2.0,
            high=3.0,
            low=1.0,
            close=2.5,
            volume=20,
            barCount=2,
            average=2.2,
        )
    ]
    data_store.record_historical_bars("AAA", "1 day", updated_bars)

    with data_store.session_scope() as session:
        close, volume = session.execute(
            select(HistoricalBar.close, HistoricalBar.volume).where(
                HistoricalBar.symbol == "AAA"
            )
        ).one()

    assert close == 2.5
    assert volume == 20


def test_record_executions_parses_string_times(tmp_path) -> None:
    from sqlalchemy import select
    from thetagang.db import ExecutionRecord

    db_path = tmp_path / "state.db"
    data_store = DataStore(
        f"sqlite:///{db_path}",
        str(tmp_path / "thetagang.toml"),
        dry_run=False,
        config_text="test",
    )

    fills = [
        SimpleNamespace(
            execution=SimpleNamespace(
                execId="1",
                orderRef="tg:grid-spread:SPY:bull_put:480.00:20241220",
                time="20240105 12:00:00",
            ),
            contract=SimpleNamespace(symbol="SPY"),
            time=None,
        )
    ]

    data_store.record_executions(fills)

    with data_store.session_scope() as session:
        row = session.execute(select(ExecutionRecord)).scalar_one()
        assert row.execution_time == datetime(2024, 1, 5, 12, 0, 0)


def test_record_order_intent_links_orders(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    data_store = DataStore(
        f"sqlite:///{db_path}",
        str(tmp_path / "thetagang.toml"),
        dry_run=True,
        config_text="test",
    )

    contract = SimpleNamespace(
        symbol="AAA",
        secType="STK",
        conId=101,
        exchange="SMART",
        currency="USD",
    )
    order = SimpleNamespace(
        action="BUY",
        totalQuantity=10,
        lmtPrice=123.45,
        orderType="LMT",
        orderRef="tg:test",
        tif="DAY",
    )

    intent_id = data_store.record_order_intent(contract, order)
    assert intent_id is not None
    data_store.record_order(contract, order, intent_id=intent_id)

    with data_store.session_scope() as session:
        intent_row = session.execute(
            select(OrderIntent.id, OrderIntent.dry_run).limit(1)
        ).one()
        record_intent_id = session.execute(
            select(OrderRecord.intent_id).limit(1)
        ).scalar_one()

    assert intent_row.id == intent_id
    assert intent_row.dry_run is True
    assert record_intent_id == intent_id


def test_get_last_event_payload_ignores_dry_run(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    config_path = str(tmp_path / "thetagang.toml")

    dry_run_store = DataStore(
        f"sqlite:///{db_path}",
        config_path,
        dry_run=True,
        config_text="test",
    )
    live_store = DataStore(
        f"sqlite:///{db_path}",
        config_path,
        dry_run=False,
        config_text="test",
    )

    dry_run_store.record_event("grid_spread_run", {"symbol": "SPY", "levels": 5})
    live_store.record_event("grid_spread_run", {"symbol": "SPY", "levels": 8})

    payload = live_store.get_last_event_payload("grid_spread_run")

    assert payload == {"symbol": "SPY", "levels": 8}
