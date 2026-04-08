# Repository Guidelines

## Strategy Overview

This fork replaces the original "wheel" strategy with a **grid credit spread** strategy.
On each run the bot places bull put spreads (below current price) and/or bear call spreads
(above current price) at evenly-spaced grid levels, subject to per-symbol exposure and
max-loss caps. Direction bias (bullish / bearish / neutral) controls the ratio of buy-side
to sell-side grid levels.

## Project Structure & Module Organization

- Core trading code lives in `thetagang/`; the CLI entry point is `thetagang/entry.py`,
  with the main orchestration in `portfolio_manager.py` and configuration models in
  `config.py` / `config_models.py`.
- The Click CLI command is defined in `thetagang/main.py` (flags: `--config`, `--dry-run`,
  `--without-ibc`) and re-exported by `thetagang/entry.py` for the `thetagang` console
  script.
- Runtime startup wiring (config loading, IBKR/IBC setup, event loop) lives in
  `thetagang/thetagang.py`. Config is loaded directly from TOML — there is no migration
  layer.
- Broker integrations and order helpers sit in `thetagang/ibkr.py`,
  `thetagang/orders.py`, `thetagang/trades.py`, and `thetagang/trading_operations.py`.
- The grid strategy is implemented in two files:
  - `thetagang/strategies/grid_spread_engine.py` — `GridCreditSpreadEngine`: computes
    grid levels, applies bias, checks exposure limits, builds BAG combo orders.
  - `thetagang/strategies/grid_spread.py` — `GridStrategyDeps` dataclass and
    `run_grid_spread_stages()` async runner.
- Supporting utilities live in `thetagang/util.py`, `thetagang/options.py`,
  `thetagang/fmt.py`, `thetagang/log.py`, and `thetagang/exchange_hours.py`.
- The SQLite persistence layer is in `thetagang/db.py`.
- Tests mirror the module layout inside `tests/`; fixtures and async helpers are
  centralized in `tests/conftest.py`.

## Removed Components (vs. upstream thetagang)

The following were removed in the wheel → grid refactor:

| Removed | Reason |
|---------|--------|
| `strategies/options_engine.py` | Wheel put/call writing, rolling, closing |
| `strategies/options.py` | Options stage runner and protocols |
| `strategies/equity_engine.py` | Stock buy/sell rebalancing |
| `strategies/equity.py` | Equity stage runner |
| `strategies/regime_engine.py` | Regime-aware rebalancing |
| `strategies/post_engine.py` | VIX call hedge + cash management |
| `strategies/post.py` | Post-stage runner |
| `strategies/runtime_services.py` | Service adapters for wheel/equity engines |
| `config_migration/` directory | v1 → v2 config migration |
| `legacy_config.py` | v1 config schema |
| `config.py` wheel/regime/vix/cash models | `WheelStrategyConfig`, `RollWhenConfig`, `WriteWhenConfig`, `RegimeRebalanceStrategyConfig`, `VIXCallHedgeConfig`, `CashManagementConfig`, `RebalanceMode`, `PortfolioConfig` |

## Configuration Structure

All config is in a single TOML file (default: `thetagang.toml`). The schema version
must be `2`. The only supported strategy is `"grid"`.

```toml
[meta]
schema_version = 2

[run]
strategies = ["grid"]

[runtime.account]
number  = "DU99999"
margin_usage = 0.5     # fraction of NetLiq to treat as available capital

[runtime.option_chains]
expirations = 4
strikes     = 10

[runtime.orders]
exchange = "SMART"
price_update_delay = [30, 60]   # seconds, random interval for repricing

[runtime.database]
enabled = true
path    = "data/thetagang.db"

# One section per symbol; all fields shown with their defaults.
[strategies.grid.symbols.SPY]
lower_bound              = 450.0   # minimum short-strike price
upper_bound              = 600.0   # maximum short-strike price
grid_spacing             = 5.0     # $ between levels (mutually exclusive with grid_spacing_pct)
# grid_spacing_pct       = 0.01    # alternative: fraction of current price
spread_width             = 5.0     # $ between short and long leg of each spread
contracts_per_level      = 1
target_dte               = 21      # nearest expiry >= this many days out
min_credit               = 0.20    # skip levels where net credit < this
max_loss_per_symbol      = 5000.0  # stop opening new spreads once cumulative max-loss reaches this
max_exposure_per_symbol  = 10000.0 # stop once total margin (width × 100 × contracts) reaches this
primary_exchange         = "ARCA"

[strategies.grid.symbols.SPY.bias]
mode        = "bullish"   # "bullish" | "bearish" | "neutral"
buy_levels  = 8           # how many bull-put spread levels below price
sell_levels = 3           # how many bear-call spread levels above price
```

### Key config validations

- Exactly one of `grid_spacing` or `grid_spacing_pct` must be set per symbol.
- `upper_bound` must exceed `lower_bound`.
- `spread_width` must be smaller than `upper_bound − lower_bound`.
- `run.strategies` must contain exactly `["grid"]`; `"wheel"` and all other former
  strategy names are no longer valid.

## How the Grid Engine Works

On each `manage()` call:

1. **Fetch current price** for the symbol (midpoint or market).
2. **Compute grid levels** from `lower_bound` to `upper_bound` at `grid_spacing` intervals.
3. **Apply bias**: keep up to `buy_levels` put-spread levels below price and up to
   `sell_levels` call-spread levels above price (subject to `bias.mode`).
4. **Skip covered levels**: check open-order `orderRef` values matching the pattern
   `tg:grid-spread:{symbol}:{kind}:{strike}:{expiry}`.
5. **Check limits** before each new spread:
   - `cur_max_loss + spread_max_loss <= max_loss_per_symbol`
   - `cur_margin + spread_margin <= max_exposure_per_symbol`
6. **Qualify both option legs**, build a BAG combo contract, fetch the net credit.
7. **Skip** if `net_credit < min_credit`.
8. **Enqueue** a `SELL` limit order on the combo contract.

### Order reference pattern

```
tg:grid-spread:{SYMBOL}:{kind}:{short_strike:.2f}:{expiry_YYYYMMDD}
```

Example: `tg:grid-spread:SPY:bull_put:480.00:20241220`

### Exposure accounting

- **Margin per spread** = `spread_width × 100 × contracts_per_level`
- **Max loss per spread** = `(spread_width − min_credit) × 100 × contracts_per_level`
  (conservative: ignores actual credit received for existing positions)
- Existing spread positions are identified from `portfolio_positions` by pairing short and
  long legs on the same right and expiry.

## Build, Test, and Development Commands

```bash
uv run thetagang --config thetagang.toml --dry-run   # dry run (no live orders)
uv run pytest                                         # full test suite
uv run pytest --cov=thetagang                         # with coverage
uv run ruff check . && uv run ruff format .           # lint + format
uv run ty check                                       # static type checking
uv run pre-commit run --all-files                     # replicate CI hooks
```

## Coding Style & Naming Conventions

- Python ≥ 3.10 with 4-space indentation and Ruff-enforced 88-character lines; imports
  sorted via Ruff.
- `snake_case` for functions and variables, `CapWords` for classes, descriptive TOML keys.
- Annotate new or modified functions with precise type hints; keep module-level constants
  uppercase.
- Add configuration-driven behaviour through Pydantic models in `config_models.py`,
  ensuring defaults and validation match `thetagang.toml`.

## Testing Guidelines

- Tests use `pytest` and `pytest-asyncio`; name files `test_<module>.py` and prefer async
  tests for IBKR flows.
- Stub external calls with fixtures from `tests/` to prevent network usage.
- Use the `_base_config()` helper in `tests/test_config_new.py` as the canonical
  minimal-valid config fixture for new tests.
- Run `uv run pytest --cov=thetagang` before pushing; new features must include targeted
  assertions.

## Commit & Pull Request Guidelines

- Follow conventional commit style: `fix:`, `feat:`, `chore:` with optional scopes
  (`feat(grid): add bearish bias support`).
- Subject lines in present tense, ≤ 72 characters; use the body to explain intent, risk,
  and testing evidence.
- PR descriptions should note behavioural impacts, list validation commands, and include
  relevant dry-run output for order-generation changes.
