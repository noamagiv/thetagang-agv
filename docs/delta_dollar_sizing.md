# Delta Dollar Effect, Flow, and Sizing

A concrete walkthrough of how delta, dollar delta, and sizing interact for the
grid credit spreads.

---

## Setup

SPY at **$500**. Bull put spreads, 5-point width, 21 DTE.

```
Level A:  short 490P / long 485P  (10 pts OTM)
Level B:  short 470P / long 465P  (30 pts OTM)
```

---

## Step 1 — Delta per leg (from Black-Scholes, typical values)

| Level | Short leg | Short Δ | Long leg | Long Δ | Net spread Δ (per contract) |
|-------|-----------|---------|----------|--------|-----------------------------|
| A     | 490P      | −0.35   | 485P     | −0.28  | −(−0.35) + (−0.28) = **+0.07** |
| B     | 470P      | −0.12   | 465P     | −0.09  | −(−0.12) + (−0.09) = **+0.03** |

We *sold* the short leg (flip sign) and *bought* the long leg. Net positive delta
= bullish exposure, which is correct for a bull put spread.

---

## Step 2 — Dollar delta (what a $1 SPY move is worth)

```
Dollar delta = net_delta × 100 × contracts × underlying_price
                                              ← notional scaling
```

With `contracts_per_level = 1` (current fixed approach):

| Level | Net Δ | Dollar delta per $1 SPY move |
|-------|-------|------------------------------|
| A     | 0.07  | 0.07 × 100 × 1 = **$7**     |
| B     | 0.03  | 0.03 × 100 × 1 = **$3**     |

**Problem:** Level A gives 2.3× more exposure than Level B for the same number
of contracts. The grid is not balanced.

---

## Step 3 — Delta-dollar sizing (target = $7 per $1 move at every level)

```
contracts = target_dollar_delta / (net_delta × 100)
```

| Level | Net Δ | Contracts to reach $7/pt | Actual dollar delta |
|-------|-------|--------------------------|---------------------|
| A     | 0.07  | 7 / (0.07 × 100) = 1.0   | **$7**              |
| B     | 0.03  | 7 / (0.03 × 100) = 2.3 → **2** | ~$6          |

Level B now uses 2 contracts instead of 1. Lower-delta (far OTM) levels
automatically get more contracts to equalise exposure.

---

## Step 4 — The "flow" effect (how delta moves as SPY drops)

This is why sizing matters over time:

```
SPY drops $10:  490P delta rises from −0.35 → −0.55 (gamma acceleration)
                470P delta rises from −0.12 → −0.18 (smaller gamma, far OTM)
```

| Level | Initial net Δ | Net Δ after −$10 SPY | $ PnL on the move      |
|-------|---------------|----------------------|------------------------|
| A ×1  | +0.07         | +0.15                | −$7 to −$15/pt, avg ≈ **−$110** |
| B ×2  | +0.06 (×2)    | +0.08 (×2)           | ≈ **−$70**             |

Level A bleeds more on a big down move because it is closer to the money AND
has higher gamma. The dollar delta *accelerates* for near-the-money spreads.
This is the "flow": your dollar exposure is not static; it increases as SPY
approaches the short strike.

---

## What the current code does vs. what delta sizing would add

**Current code** (`thetagang/strategies/grid_spread_engine.py`):

```python
spread_max_loss = (cfg.spread_width * 100 - cfg.min_credit * 100) * cfg.contracts_per_level
spread_margin   = cfg.spread_width * 100 * cfg.contracts_per_level
```

This uses a **fixed** `contracts_per_level` — no delta awareness. All levels are
sized identically.

**Delta-dollar sizing** would replace `contracts_per_level` with a computed value:

```python
# Pseudocode for delta-dollar sizing
target_dollar_delta = cfg.target_dollar_delta_per_level   # e.g. $700

net_delta = abs(short_delta) - abs(long_delta)            # from option chain greeks
if net_delta > 0:
    contracts = max(1, round(target_dollar_delta / (net_delta * 100)))
else:
    contracts = 1  # fallback
```

---

## Summary

| Concept | What it is | Why it matters |
|---------|-----------|----------------|
| **Delta** | Option price change per $1 underlying move | Measures directional exposure per contract |
| **Dollar delta** | `delta × 100 × contracts` | Normalises exposure across strikes; what you actually make/lose per $1 move |
| **Delta flow** | How dollar delta changes as price moves toward the strike (gamma) | Near-ATM spreads accelerate faster — they consume your loss budget faster than far-OTM ones |

The key insight: with fixed `contracts_per_level = 1`, near-ATM grid levels have
disproportionately large dollar delta AND faster-accelerating risk. Delta-dollar
sizing corrects this by giving far-OTM levels more contracts so every grid level
contributes roughly equally to your net directional exposure.
