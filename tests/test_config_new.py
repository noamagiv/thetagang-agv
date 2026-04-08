import pytest

from thetagang.config import Config, stage_enabled_map, stage_enabled_map_from_run, RunConfig


def _base_config(run=None):
    return {
        "meta": {"schema_version": 2},
        "run": run or {"strategies": ["grid"]},
        "runtime": {
            "account": {"number": "DUX", "margin_usage": 0.5},
            "option_chains": {"expirations": 4, "strikes": 10},
        },
        "strategies": {
            "grid": {
                "symbols": {
                    "SPY": {
                        "lower_bound": 400.0,
                        "upper_bound": 600.0,
                        "grid_spacing": 5.0,
                        "spread_width": 5.0,
                        "max_loss_per_symbol": 5000.0,
                        "max_exposure_per_symbol": 10000.0,
                    }
                }
            }
        },
    }


class TestRunConfig:
    def test_strategies_required(self):
        with pytest.raises(Exception, match="run must define"):
            RunConfig()

    def test_unknown_strategy_raises(self):
        with pytest.raises(Exception, match="unknown strategy"):
            RunConfig(strategies=["wheel"])

    def test_grid_strategy_valid(self):
        rc = RunConfig(strategies=["grid"])
        stages = rc.resolved_stages()
        assert len(stages) == 1
        assert stages[0].id == "equity_grid_spread"

    def test_stage_enabled_map(self):
        rc = RunConfig(strategies=["grid"])
        m = stage_enabled_map_from_run(rc)
        assert m["equity_grid_spread"] is True

    def test_stages_and_strategies_mutual_exclusion(self):
        with pytest.raises(Exception, match="exactly one"):
            RunConfig(
                strategies=["grid"],
                stages=[{"id": "equity_grid_spread", "kind": "equity.grid_spread"}],
            )

    def test_unknown_stage_id_raises(self):
        with pytest.raises(Exception, match="unknown stage id"):
            RunConfig(stages=[{"id": "options_write_puts", "kind": "options.write_puts"}])


class TestConfig:
    def test_valid_config(self):
        cfg = Config(**_base_config())
        assert cfg.runtime.account.number == "DUX"
        assert "SPY" in cfg.strategies.grid.symbols

    def test_stage_map_via_config(self):
        cfg = Config(**_base_config())
        m = stage_enabled_map(cfg)
        assert m["equity_grid_spread"] is True

    def test_grid_symbol_spacing_validation(self):
        doc = _base_config()
        doc["strategies"]["grid"]["symbols"]["SPY"]["grid_spacing_pct"] = 0.01
        with pytest.raises(Exception, match="only one of"):
            Config(**doc)

    def test_grid_symbol_no_spacing_raises(self):
        doc = _base_config()
        del doc["strategies"]["grid"]["symbols"]["SPY"]["grid_spacing"]
        with pytest.raises(Exception, match="set grid_spacing"):
            Config(**doc)

    def test_grid_symbol_bounds_validation(self):
        doc = _base_config()
        doc["strategies"]["grid"]["symbols"]["SPY"]["upper_bound"] = 399.0
        with pytest.raises(Exception, match="upper_bound must exceed lower_bound"):
            Config(**doc)

    def test_grid_spread_width_validation(self):
        doc = _base_config()
        doc["strategies"]["grid"]["symbols"]["SPY"]["spread_width"] = 500.0
        with pytest.raises(Exception, match="spread_width must be smaller"):
            Config(**doc)

    def test_bias_defaults_to_neutral(self):
        cfg = Config(**_base_config())
        from thetagang.config_models import GridBiasMode
        assert cfg.strategies.grid.symbols["SPY"].bias.mode == GridBiasMode.NEUTRAL
        assert cfg.strategies.grid.symbols["SPY"].bias.buy_levels == 5
        assert cfg.strategies.grid.symbols["SPY"].bias.sell_levels == 5

    def test_meta_schema_version_enforced(self):
        doc = _base_config()
        doc["meta"]["schema_version"] = 1
        with pytest.raises(Exception, match="schema_version must be 2"):
            Config(**doc)

    def test_grid_symbols_required(self):
        doc = _base_config()
        doc["strategies"]["grid"]["symbols"] = {}
        with pytest.raises(Exception):
            Config(**doc)
