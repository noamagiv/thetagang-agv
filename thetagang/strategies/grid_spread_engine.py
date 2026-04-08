from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from ib_async import PortfolioItem, Ticker
from ib_async.contract import Contract, ComboLeg, Option, Stock

from thetagang import log
from thetagang.ibkr import IBKR, TickerField
from thetagang.options import option_dte
from thetagang.trading_operations import OrderOperations

if TYPE_CHECKING:
    from thetagang.config import Config
    from thetagang.config_models import GridBiasConfig, GridSymbolConfig


class GridCreditSpreadEngine:
    """Places and tracks a grid of credit spreads on configured symbols.

    On each run:
      1. Fetch current price for each symbol.
      2. Compute all grid levels within [lower_bound, upper_bound].
      3. Apply bias to select active buy (bull put) and sell (bear call) levels.
      4. Cross-reference open orders (via order_ref) to skip covered levels.
      5. Check exposure/loss limits before each new spread.
      6. Qualify both option legs, build a BAG combo contract, enqueue as SELL.
    """

    def __init__(
        self,
        *,
        config: "Config",
        ibkr: IBKR,
        order_ops: OrderOperations,
    ) -> None:
        self.config = config
        self.ibkr = ibkr
        self.order_ops = order_ops

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_grid(
        self,
        account_summary: Dict,
        portfolio_positions: Dict[str, List[PortfolioItem]],
    ) -> None:
        open_trades = self.ibkr.open_trades()
        open_order_refs: set[str] = {
            t.order.orderRef
            for t in open_trades
            if not t.isDone() and hasattr(t.order, "orderRef") and t.order.orderRef
        }

        for symbol, cfg in self.config.strategies.grid.symbols.items():
            try:
                await self._run_symbol(
                    symbol, cfg, portfolio_positions, open_order_refs
                )
            except Exception as exc:
                log.error(f"{symbol}: grid spread error: {exc}")

    # ------------------------------------------------------------------
    # Per-symbol logic
    # ------------------------------------------------------------------

    async def _run_symbol(
        self,
        symbol: str,
        cfg: "GridSymbolConfig",
        portfolio_positions: Dict[str, List[PortfolioItem]],
        open_order_refs: set[str],
    ) -> None:
        stock = Stock(symbol, cfg.primary_exchange, currency="USD")
        ticker = await self.ibkr.get_ticker_for_contract(
            stock,
            required_fields=[],
            optional_fields=[TickerField.MIDPOINT, TickerField.MARKET_PRICE],
        )
        price = _midpoint_or_market(ticker)
        if not price or price <= 0:
            log.warning(f"{symbol}: could not get valid price, skipping grid")
            return

        # Current exposure from existing spread positions
        cur_max_loss, cur_margin = self._current_exposure(
            portfolio_positions.get(symbol, []), cfg
        )

        levels = self._compute_levels(cfg, price)
        active = self._apply_bias(levels, price, cfg.bias)

        # Find the nearest eligible expiration once per symbol
        chains = await self.ibkr.get_chains_for_contract(stock)
        expiry = self._pick_expiry(chains, cfg.target_dte)
        if not expiry:
            log.warning(f"{symbol}: no valid expiry found for target_dte={cfg.target_dte}")
            return

        for short_strike, kind in active.items():
            right = "P" if kind == "bull_put" else "C"
            long_strike = (
                round(short_strike - cfg.spread_width, 2)
                if right == "P"
                else round(short_strike + cfg.spread_width, 2)
            )

            # Skip if outside chain bounds
            if long_strike <= 0:
                continue

            order_ref = _order_ref(symbol, kind, short_strike, expiry)
            if order_ref in open_order_refs:
                log.info(f"{symbol}: level {kind}@{short_strike} already has open order, skipping")
                continue

            # Exposure check before fetching market data
            spread_max_loss = (cfg.spread_width * 100 - cfg.min_credit * 100) * cfg.contracts_per_level
            spread_margin = cfg.spread_width * 100 * cfg.contracts_per_level

            if cur_max_loss + spread_max_loss > cfg.max_loss_per_symbol:
                log.notice(f"{symbol}: max_loss_per_symbol ${cfg.max_loss_per_symbol:,.0f} reached, stopping grid")
                break
            if cur_margin + spread_margin > cfg.max_exposure_per_symbol:
                log.notice(f"{symbol}: max_exposure_per_symbol ${cfg.max_exposure_per_symbol:,.0f} reached, stopping grid")
                break

            # Build and qualify the two-leg combo
            try:
                bag = await self._build_spread_bag(
                    symbol, cfg.primary_exchange, expiry,
                    short_strike, long_strike, right,
                )
            except Exception as exc:
                log.warning(f"{symbol}: could not qualify spread {kind}@{short_strike}/{long_strike}: {exc}")
                continue

            # Fetch net credit for the spread
            try:
                spread_ticker = await self.ibkr.get_ticker_for_contract(
                    bag,
                    required_fields=[],
                    optional_fields=[TickerField.MIDPOINT, TickerField.MARKET_PRICE],
                )
                net_credit = _midpoint_or_market(spread_ticker)
            except Exception as exc:
                log.warning(f"{symbol}: could not get spread price for {kind}@{short_strike}: {exc}")
                continue

            if not net_credit or net_credit < cfg.min_credit:
                log.notice(
                    f"{symbol}: credit {net_credit:.2f} < min {cfg.min_credit:.2f} "
                    f"for {kind}@{short_strike}, skipping"
                )
                continue

            order = self.order_ops.create_limit_order(
                action="SELL",
                quantity=cfg.contracts_per_level,
                limit_price=round(net_credit, 2),
                use_default_algo=False,  # combo orders don't support algos
                order_ref=order_ref,
            )
            self.order_ops.enqueue_order(bag, order)
            log.notice(
                f"{symbol}: queued {kind} spread {short_strike}/{long_strike} "
                f"exp {expiry} @ ${net_credit:.2f} credit"
            )

            cur_max_loss += spread_max_loss
            cur_margin += spread_margin

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_levels(self, cfg: "GridSymbolConfig", current_price: float) -> List[float]:
        """Return sorted price levels from lower_bound to upper_bound."""
        if cfg.grid_spacing:
            spacing = cfg.grid_spacing
        else:
            spacing = round(current_price * (cfg.grid_spacing_pct or 0), 2)
        levels: List[float] = []
        p = cfg.lower_bound
        while p <= cfg.upper_bound + 1e-9:
            levels.append(round(p, 2))
            p += spacing
        return levels

    def _apply_bias(
        self, levels: List[float], price: float, bias: "GridBiasConfig"
    ) -> Dict[float, str]:
        """Return {strike: 'bull_put' | 'bear_call'} respecting bias limits."""
        from thetagang.config_models import GridBiasMode

        result: Dict[float, str] = {}
        if bias.mode in (GridBiasMode.BULLISH, GridBiasMode.NEUTRAL):
            buys = sorted([l for l in levels if l < price], reverse=True)[: bias.buy_levels]
            result.update({l: "bull_put" for l in buys})
        if bias.mode in (GridBiasMode.BEARISH, GridBiasMode.NEUTRAL):
            sells = sorted([l for l in levels if l > price])[: bias.sell_levels]
            result.update({l: "bear_call" for l in sells})
        return result

    def _current_exposure(
        self,
        positions: List[PortfolioItem],
        cfg: "GridSymbolConfig",
    ) -> Tuple[float, float]:
        """Estimate (total_max_loss, total_margin) from existing spread positions.

        Identifies spread pairs: a short leg (position < 0) and a long leg
        (position > 0) on the same right and expiry.  For each matched pair,
        margin = spread_width × 100 × contracts, and max_loss is conservatively
        estimated as margin (ignores any credit already received).
        """
        from ib_async.contract import Option as IBOption

        shorts: List[PortfolioItem] = []
        longs: List[PortfolioItem] = []
        for pos in positions:
            if not isinstance(pos.contract, IBOption):
                continue
            if pos.position < 0:
                shorts.append(pos)
            elif pos.position > 0:
                longs.append(pos)

        total_margin = 0.0
        total_max_loss = 0.0
        matched_longs: set[int] = set()

        for short_pos in shorts:
            sc = short_pos.contract
            for long_pos in longs:
                lc = long_pos.contract
                if (
                    id(long_pos) in matched_longs
                    or lc.right != sc.right
                    or lc.lastTradeDateOrContractMonth != sc.lastTradeDateOrContractMonth
                ):
                    continue
                # They're on the same expiry/right — treat as a spread
                width = abs(sc.strike - lc.strike)
                contracts = min(abs(short_pos.position), abs(long_pos.position))
                margin = width * 100 * contracts
                total_margin += margin
                total_max_loss += margin  # conservative: ignore received credit
                matched_longs.add(id(long_pos))
                break

        return total_max_loss, total_margin

    async def _build_spread_bag(
        self,
        symbol: str,
        primary_exchange: str,
        expiry: str,
        short_strike: float,
        long_strike: float,
        right: str,
    ) -> Contract:
        exchange = self.order_ops.get_order_exchange()
        short_opt = Option(symbol, expiry, short_strike, right, exchange)
        long_opt = Option(symbol, expiry, long_strike, right, exchange)
        qualified = await self.ibkr.qualify_contracts(short_opt, long_opt)
        if len(qualified) != 2:
            raise ValueError(
                f"Could not qualify both legs: {short_strike}/{long_strike} {right} {expiry}"
            )
        short_opt, long_opt = qualified

        combo_legs = [
            ComboLeg(conId=short_opt.conId, ratio=1, action="SELL", exchange=exchange),
            ComboLeg(conId=long_opt.conId, ratio=1, action="BUY", exchange=exchange),
        ]
        return Contract(
            secType="BAG",
            symbol=symbol,
            currency="USD",
            exchange=exchange,
            comboLegs=combo_legs,
        )

    @staticmethod
    def _pick_expiry(chains: list, target_dte: int) -> Optional[str]:
        """Return the nearest expiration >= target_dte across all chains."""
        best: Optional[str] = None
        best_dte: Optional[int] = None
        for chain in chains:
            for exp in chain.expirations:
                dte = option_dte(exp)
                if dte >= target_dte:
                    if best_dte is None or dte < best_dte:
                        best = exp
                        best_dte = dte
        return best


def _midpoint_or_market(ticker: Ticker) -> float:
    from ib_async import util

    mid = ticker.midpoint()
    if mid and not util.isNan(mid) and mid > 0:
        return mid
    mkt = ticker.marketPrice()
    if mkt and not util.isNan(mkt) and mkt > 0:
        return mkt
    return 0.0


def _order_ref(symbol: str, kind: str, strike: float, expiry: str) -> str:
    return f"tg:grid-spread:{symbol}:{kind}:{strike:.2f}:{expiry}"
