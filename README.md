# ThetaGang — Grid Credit Spread Bot

An [IBKR](https://www.interactivebrokers.com/) trading bot that places
**grid credit spreads** (bull put spreads and/or bear call spreads) at
evenly-spaced price levels on a configured instrument, with directional bias
and per-symbol exposure controls.

> **Fork note**: This repository is a focused fork of
> [brndnmtthws/thetagang](https://github.com/brndnmtthws/thetagang). The
> original wheel strategy, equity rebalancing, regime rebalancing, VIX hedging,
> cash management, and config migration have all been removed. Only the grid
> credit spread strategy remains.

---

## Risk Disclaimer

**Options trading involves substantial risk.** Credit spreads have defined
maximum loss, but that loss can still be significant if many grid levels are
breached simultaneously. This is not a "free money" strategy.

- Understand the maximum loss on each spread before deploying capital.
- Test thoroughly with a paper account before live trading.
- Consult a financial advisor if you are unsure.

---

## How It Works

On each scheduled run the bot:

1. Fetches the current price of each configured symbol.
2. Computes grid levels between `lower_bound` and `upper_bound` at fixed
   spacing (`grid_spacing` or `grid_spacing_pct`).
3. Applies **bias** to select active levels:
   - **Bullish**: more bull put spread levels below price, fewer call spread
     levels above.
   - **Bearish**: more bear call spread levels above price, fewer put spread
     levels below.
   - **Neutral**: equal levels on both sides.
4. Skips any level that already has an open order (identified by `orderRef`).
5. Checks per-symbol **exposure and loss limits** before opening each new
   spread.
6. Submits limit orders on BAG (combo) contracts — one short leg and one long
   (protective) leg per spread.

### Spread types

| Grid zone | Spread type | Short leg | Long leg |
|-----------|-------------|-----------|----------|
| Below current price | Bull put spread | Sell put @ strike | Buy put @ strike − width |
| Above current price | Bear call spread | Sell call @ strike | Buy call @ strike + width |

### Exposure controls

| Parameter | Description |
|-----------|-------------|
| `max_loss_per_symbol` | Stop opening new spreads once cumulative max-loss (across open positions + queued orders) reaches this dollar amount |
| `max_exposure_per_symbol` | Stop once total margin (`spread_width × 100 × contracts`) reaches this dollar amount |

---

## Requirements

- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/) package manager
- An Interactive Brokers account with options trading enabled
- [IBC](https://github.com/IbcAlpha/IBC) for managing the IB Gateway / TWS
  (or run Gateway yourself and use `--without-ibc`)

---

## Installation

```console
pip install thetagang
```

Or from source:

```console
git clone <this-repo>
cd thetagang-agv
uv sync
```

---

## Quickstart

### 1. Create a config file

Minimum required config (`thetagang.toml`):

```toml
[meta]
schema_version = 2

[run]
strategies = ["grid"]

[runtime.account]
number       = "DU99999"    # your IBKR paper account number
margin_usage = 0.5          # use 50% of net liquidation as capital

[runtime.option_chains]
expirations = 4
strikes     = 10

[runtime.ibc]
tradingMode = "paper"
userid      = "your_ibkr_user"
password    = "your_ibkr_password"

[strategies.grid.symbols.SPY]
lower_bound             = 450.0
upper_bound             = 580.0
grid_spacing            = 5.0      # one spread level every $5
spread_width            = 5.0      # $5-wide spreads (e.g. 480P / 475P)
contracts_per_level     = 1
target_dte              = 21
min_credit              = 0.20
max_loss_per_symbol     = 5000.0
max_exposure_per_symbol = 10000.0
primary_exchange        = "ARCA"

[strategies.grid.symbols.SPY.bias]
mode        = "bullish"
buy_levels  = 8
sell_levels = 3
```

### 2. Dry run

```console
thetagang --config thetagang.toml --dry-run
```

This connects to IBKR, fetches prices, computes the grid, and prints the
orders it _would_ place — without submitting anything.

### 3. Live run

```console
thetagang --config thetagang.toml
```

---

## Configuration Reference

### `[run]`

```toml
[run]
strategies = ["grid"]   # the only valid value
```

You can also use explicit stage syntax:

```toml
[run]
stages = [{ id = "equity_grid_spread", kind = "equity.grid_spread", enabled = true }]
```

### `[runtime.account]`

| Key | Type | Description |
|-----|------|-------------|
| `number` | string | IBKR account number |
| `margin_usage` | float 0–1 | Fraction of net liquidation treated as available capital |
| `cancel_orders` | bool | Cancel existing open orders for grid symbols at startup (default: `true`) |
| `market_data_type` | int 1–4 | 1=live, 2=frozen, 3=delayed, 4=delayed-frozen |

### `[runtime.option_chains]`

| Key | Type | Description |
|-----|------|-------------|
| `expirations` | int | Number of expiration dates to scan per symbol |
| `strikes` | int | Number of strikes to scan per expiration |

### `[runtime.orders]`

| Key | Default | Description |
|-----|---------|-------------|
| `exchange` | `"SMART"` | Order routing exchange |
| `price_update_delay` | `[30, 60]` | Random delay range (seconds) before repricing unfilled orders |
| `minimum_credit` | `0.0` | Global minimum credit floor |

### `[runtime.database]`

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `true` | Persist trades, executions, and events to SQLite |
| `path` | `"data/thetagang.db"` | Path relative to config file |
| `url` | — | Override with full SQLAlchemy URL |

### `[runtime.exchange_hours]`

| Key | Default | Description |
|-----|---------|-------------|
| `exchange` | `"XNYS"` | Exchange calendar to check |
| `action_when_closed` | `"exit"` | `"exit"`, `"wait"`, or `"continue"` |
| `delay_after_open` | `1800` | Seconds to wait after open before trading |
| `delay_before_close` | `1800` | Seconds before close to stop trading |
| `max_wait_until_open` | `3600` | Max seconds to wait if market is closed |

### `[strategies.grid.symbols.<SYMBOL>]`

| Key | Required | Description |
|-----|----------|-------------|
| `lower_bound` | yes | Minimum short-strike price |
| `upper_bound` | yes | Maximum short-strike price |
| `grid_spacing` | one of | Absolute $ between grid levels |
| `grid_spacing_pct` | one of | Grid spacing as fraction of current price (e.g. `0.01` = 1%) |
| `spread_width` | yes | $ distance between short and long leg |
| `contracts_per_level` | no (default 1) | Contracts per grid level |
| `target_dte` | no (default 30) | Minimum days-to-expiry for selected expiration |
| `min_credit` | no (default 0.05) | Minimum net credit to accept; skip level if below |
| `max_loss_per_symbol` | yes | Dollar cap on cumulative maximum loss |
| `max_exposure_per_symbol` | yes | Dollar cap on cumulative margin requirement |
| `primary_exchange` | no (default `"SMART"`) | Primary exchange for the underlying |

### `[strategies.grid.symbols.<SYMBOL>.bias]`

| Key | Default | Description |
|-----|---------|-------------|
| `mode` | `"neutral"` | `"bullish"`, `"bearish"`, or `"neutral"` |
| `buy_levels` | `5` | Max active bull-put spread levels below current price |
| `sell_levels` | `5` | Max active bear-call spread levels above current price |

**Bias modes:**
- `"bullish"` — only bull put spreads (below price), no call spreads
- `"bearish"` — only bear call spreads (above price), no put spreads
- `"neutral"` — both sides, limited by `buy_levels` and `sell_levels`

---

## CLI Reference

```console
thetagang [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--config PATH` | Path to TOML config file (required) |
| `--dry-run` | Print proposed orders, do not submit |
| `--without-ibc` | Connect to a Gateway/TWS you started yourself |
| `-v / --verbosity` | Increase log verbosity |

All flags support the `THETAGANG_` environment variable prefix.
Example: `THETAGANG_CONFIG=./thetagang.toml`.

---

## Running with Docker

```console
docker run --rm -i --net host \
    -v ~/thetagang:/etc/thetagang \
    brndnmtthws/thetagang:main \
    --config /etc/thetagang/thetagang.toml
```

As a daily cron (Mon–Fri at 9 am):

```crontab
0 9 * * 1-5 docker run --rm -i -v ~/thetagang:/etc/thetagang brndnmtthws/thetagang:main --config /etc/thetagang/thetagang.toml
```

---

## State Database

The bot persists order intents, executions, account snapshots, and run events
to a SQLite database. Order refs for grid spreads follow the pattern:

```
tg:grid-spread:{SYMBOL}:{kind}:{short_strike:.2f}:{expiry_YYYYMMDD}
```

Example: `tg:grid-spread:SPY:bull_put:480.00:20241220`

This is used to detect which grid levels already have open orders and avoid
duplicates across runs.

---

## Development

```console
uv run pre-commit install
uv run pytest
uv run ruff check . && uv run ruff format .
uv run ty check
```

---

## FAQ

| Error | Cause | Resolution |
|---|---|---|
| `Requested market data is not subscribed` | Missing IBKR market data subscription | Enable the relevant subscription in your IBKR account settings |
| `No market data during competing live session` | Account is logged in elsewhere | Log out of all other IBKR sessions |
| `The contract description specified for SYMBOL is ambiguous` | IBKR needs the primary exchange | Set `primary_exchange` for the symbol in config |
| IBKey / MFA authentication issues | IBKR requires MFA on the primary account | Create a secondary limited-permission sub-account without MFA |
