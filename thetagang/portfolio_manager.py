import asyncio
import logging
import math
import random
from asyncio import Future
from typing import Any, Coroutine, Dict, List, Optional, Tuple

from ib_async import (
    AccountValue,
    PortfolioItem,
    Ticker,
    util,
)
from ib_async.contract import Option, Stock
from ib_async.ib import IB
from rich.panel import Panel
from rich.table import Table

from thetagang import log
from thetagang.config import (
    CANONICAL_STAGE_ORDER,
    DEFAULT_RUN_STRATEGIES,
    Config,
    RunConfig,
    enabled_stage_ids_from_run,
    stage_enabled_map_from_run,
)
from thetagang.db import DataStore
from thetagang.fmt import dfmt, ffmt, ifmt, pfmt
from thetagang.ibkr import (
    IBKR,
    IBKRRequestTimeout,
    TickerField,
)
from thetagang.orders import Orders
from thetagang.strategies import GridStrategyDeps, run_grid_spread_stages
from thetagang.strategies.grid_spread_engine import GridCreditSpreadEngine
from thetagang.trades import Trades
from thetagang.trading_operations import OrderOperations
from thetagang.util import (
    account_summary_to_dict,
    midpoint_or_market_price,
    portfolio_positions_to_dict,
    position_pnl,
)

from .options import option_dte

# Turn off some of the more annoying logging output from ib_async
logging.getLogger("ib_async.ib").setLevel(logging.ERROR)
logging.getLogger("ib_async.wrapper").setLevel(logging.CRITICAL)


class PortfolioManager:
    @staticmethod
    def get_close_price(ticker: Ticker) -> float:
        return ticker.close if not util.isNan(ticker.close) else ticker.marketPrice()

    def __init__(
        self,
        config: Config,
        ib: IB,
        completion_future: Future[bool],
        dry_run: bool,
        data_store: Optional[DataStore] = None,
        run_stage_flags: Optional[Dict[str, bool]] = None,
        run_stage_order: Optional[List[str]] = None,
    ) -> None:
        self.account_number = config.runtime.account.number
        self.config = config
        self.data_store = data_store
        self.ibkr = IBKR(
            ib,
            config.runtime.ib_async.api_response_wait_time,
            config.runtime.orders.exchange,
            data_store=data_store,
        )
        self.completion_future = completion_future
        self.orders: Orders = Orders()
        self.trades: Trades = Trades(self.ibkr, data_store=data_store)
        self.dry_run = dry_run
        self.last_untracked_positions: Dict[str, List[PortfolioItem]] = {}
        self.order_ops = OrderOperations(
            config=self.config,
            account_number=self.account_number,
            orders=self.orders,
            data_store=self.data_store,
        )
        self.grid_engine = GridCreditSpreadEngine(
            config=self.config,
            ibkr=self.ibkr,
            order_ops=self.order_ops,
        )

        if run_stage_flags is None:
            default_run = RunConfig(strategies=DEFAULT_RUN_STRATEGIES)
            self.run_stage_flags = stage_enabled_map_from_run(default_run)
            self.run_stage_order = enabled_stage_ids_from_run(default_run)
        else:
            self.run_stage_flags = dict(run_stage_flags)
            self.run_stage_order = [
                stage_id
                for stage_id in CANONICAL_STAGE_ORDER
                if self.run_stage_flags.get(stage_id, False)
            ]
        if run_stage_order is not None:
            self.run_stage_order = list(run_stage_order)
            enabled_set = set(self.run_stage_order)
            self.run_stage_flags = {
                stage_id: (stage_id in enabled_set)
                for stage_id in CANONICAL_STAGE_ORDER
            }

    def stage_enabled(self, stage_id: str) -> bool:
        return bool(self.run_stage_flags.get(stage_id, False))

    def _grid_strategy_deps(self, enabled_stages: set[str]) -> GridStrategyDeps:
        return GridStrategyDeps(
            enabled_stages=enabled_stages,
            service=self.grid_engine,
        )

    def get_symbols(self) -> List[str]:
        return list(self.config.strategies.grid.symbols.keys())

    def partition_positions(
        self, portfolio_positions: List[PortfolioItem]
    ) -> Tuple[List[PortfolioItem], List[PortfolioItem]]:
        symbols = set(self.get_symbols())
        tracked: List[PortfolioItem] = []
        untracked: List[PortfolioItem] = []
        for item in portfolio_positions:
            if item.account != self.account_number or item.position == 0:
                continue
            if item.contract.symbol in symbols:
                tracked.append(item)
            else:
                untracked.append(item)
        return tracked, untracked

    async def get_portfolio_positions(self) -> Dict[str, List[PortfolioItem]]:
        attempts = 3
        symbols = set(self.get_symbols())
        self.last_untracked_positions = {}

        for attempt in range(1, attempts + 1):
            try:
                await self.ibkr.refresh_account_updates(self.account_number)
            except IBKRRequestTimeout as exc:
                if attempt == attempts:
                    log.warning(
                        f"Attempt {attempt}/{attempts}: {exc}. "
                        "Proceeding without a fresh account update snapshot."
                    )
                else:
                    log.warning(
                        f"Attempt {attempt}/{attempts}: {exc}. Retrying account update request..."
                    )
                    await asyncio.sleep(1)
                    continue

            portfolio_positions = self.ibkr.portfolio(account=self.account_number)
            tracked, untracked = self.partition_positions(portfolio_positions)
            portfolio_by_symbol = portfolio_positions_to_dict(tracked)
            self.last_untracked_positions = portfolio_positions_to_dict(untracked)
            filtered_conids = {item.contract.conId for item in tracked}

            if portfolio_by_symbol:
                try:
                    positions_snapshot = await self.ibkr.refresh_positions()
                except IBKRRequestTimeout as exc:
                    log.warning(
                        f"Attempt {attempt}/{attempts}: {exc}. Retrying positions snapshot..."
                    )
                    if attempt == attempts:
                        raise
                    await asyncio.sleep(1)
                    continue

                tracked_snap = [
                    pos
                    for pos in positions_snapshot
                    if pos.account == self.account_number
                    and pos.contract.symbol in symbols
                    and pos.position != 0
                ]
                missing = [
                    pos for pos in tracked_snap if pos.contract.conId not in filtered_conids
                ]
                if not missing:
                    return portfolio_by_symbol

                missing_symbols = ", ".join(sorted({p.contract.symbol for p in missing}))
                log.warning(
                    f"Attempt {attempt}/{attempts}: Portfolio snapshot missing "
                    f"{len(missing)} of {len(tracked_snap)} positions ({missing_symbols}). Retrying..."
                )
                await asyncio.sleep(1)
                continue

            try:
                positions_snapshot = await self.ibkr.refresh_positions()
            except IBKRRequestTimeout as exc:
                log.warning(f"Attempt {attempt}/{attempts}: {exc}. Retrying positions snapshot...")
                if attempt == attempts:
                    raise
                await asyncio.sleep(1)
                continue

            tracked_snap = [
                pos
                for pos in positions_snapshot
                if pos.account == self.account_number
                and pos.contract.symbol in symbols
                and pos.position != 0
            ]
            if not tracked_snap:
                return portfolio_by_symbol

            log.warning(
                f"Attempt {attempt}/{attempts}: IBKR returned {len(tracked_snap)} "
                "tracked positions but empty portfolio snapshot. Retrying..."
            )
            await asyncio.sleep(1)

        raise RuntimeError(
            "Failed to load IBKR portfolio positions after multiple attempts."
        )

    def initialize_account(self) -> None:
        self.ibkr.set_market_data_type(self.config.runtime.account.market_data_type)

        if self.config.runtime.account.cancel_orders:
            open_trades = self.ibkr.open_trades()
            symbols = set(self.get_symbols())
            for trade in open_trades:
                if not trade.isDone() and trade.contract.symbol in symbols:
                    log.warning(f"{trade.contract.symbol}: Canceling order {trade.order}")
                    self.ibkr.cancel_order(trade.order)

    async def summarize_account(
        self,
    ) -> Tuple[Dict[str, AccountValue], Dict[str, List[PortfolioItem]]]:
        account_summary = await self.ibkr.account_summary(self.account_number)
        account_summary = account_summary_to_dict(account_summary)

        if "NetLiquidation" not in account_summary:
            raise RuntimeError(
                f"Account {self.config.runtime.account.number} appears invalid (no account data returned)"
            )

        table = Table(title="Account summary")
        table.add_column("Item")
        table.add_column("Value", justify="right")
        table.add_row("Net liquidation", dfmt(account_summary["NetLiquidation"].value, 0))
        table.add_row("Excess liquidity", dfmt(account_summary["ExcessLiquidity"].value, 0))
        table.add_row("Initial margin", dfmt(account_summary["InitMarginReq"].value, 0))
        table.add_row("Maintenance margin", dfmt(account_summary["FullMaintMarginReq"].value, 0))
        table.add_row("Buying power", dfmt(account_summary["BuyingPower"].value, 0))
        table.add_row("Total cash", dfmt(account_summary["TotalCashValue"].value, 0))
        table.add_row("Cushion", pfmt(account_summary["Cushion"].value, 0))
        log.print(Panel(table))

        portfolio_positions = await self.get_portfolio_positions()
        untracked_positions = self.last_untracked_positions

        if self.data_store:
            self.data_store.record_account_snapshot(account_summary)
            combined: Dict[str, List[PortfolioItem]] = dict(portfolio_positions)
            for symbol, positions in untracked_positions.items():
                if symbol in combined:
                    combined[symbol].extend(positions)
                else:
                    combined[symbol] = positions
            self.data_store.record_positions_snapshot(combined)

        position_values: Dict[int, Dict[str, str]] = {}

        async def load_position_task(pos: PortfolioItem) -> None:
            qty = pos.position
            qty_display = ifmt(int(qty)) if isinstance(qty, float) and qty.is_integer() else ffmt(qty, 4)
            position_values[pos.contract.conId] = {
                "qty": qty_display,
                "mktprice": dfmt(pos.marketPrice),
                "avgprice": dfmt(pos.averageCost),
                "value": dfmt(pos.marketValue, 0),
                "cost": dfmt(pos.averageCost * pos.position, 0),
                "unrealized": dfmt(pos.unrealizedPNL, 0),
                "p&l": pfmt(position_pnl(pos), 1),
                "itm?": "",
            }
            if isinstance(pos.contract, Option):
                position_values[pos.contract.conId]["avgprice"] = dfmt(
                    pos.averageCost / float(pos.contract.multiplier)
                )
                position_values[pos.contract.conId]["strike"] = dfmt(pos.contract.strike)
                position_values[pos.contract.conId]["dte"] = str(
                    option_dte(pos.contract.lastTradeDateOrContractMonth)
                )
                position_values[pos.contract.conId]["exp"] = str(
                    pos.contract.lastTradeDateOrContractMonth
                )

        tasks: List[Coroutine[Any, Any, None]] = []
        for _, positions in portfolio_positions.items():
            for position in positions:
                tasks.append(load_position_task(position))
        for _, positions in untracked_positions.items():
            for position in positions:
                tasks.append(load_position_task(position))
        await log.track_async(tasks, "Loading portfolio positions...")

        table = Table(title="Portfolio positions", collapse_padding=True)
        table.add_column("Symbol")
        table.add_column("R")
        table.add_column("Qty", justify="right")
        table.add_column("MktPrice", justify="right")
        table.add_column("AvgPrice", justify="right")
        table.add_column("Value", justify="right")
        table.add_column("Cost", justify="right")
        table.add_column("Unrealized P&L", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Strike", justify="right")
        table.add_column("Exp", justify="right")
        table.add_column("DTE", justify="right")
        table.add_column("ITM?")

        def getval(col: str, conId: int) -> str:
            return position_values[conId].get(col, "")

        def add_symbol_positions(symbol: str, positions: List[PortfolioItem]) -> None:
            table.add_row(symbol)
            sorted_positions = sorted(
                positions,
                key=lambda p: (
                    option_dte(p.contract.lastTradeDateOrContractMonth)
                    if isinstance(p.contract, Option)
                    else -1
                ),
            )
            for pos in sorted_positions:
                conId = pos.contract.conId
                if isinstance(pos.contract, Stock):
                    table.add_row(
                        "", "S",
                        getval("qty", conId), getval("mktprice", conId),
                        getval("avgprice", conId), getval("value", conId),
                        getval("cost", conId), getval("unrealized", conId),
                        getval("p&l", conId),
                    )
                elif isinstance(pos.contract, Option):
                    table.add_row(
                        "", pos.contract.right,
                        getval("qty", conId), getval("mktprice", conId),
                        getval("avgprice", conId), getval("value", conId),
                        getval("cost", conId), getval("unrealized", conId),
                        getval("p&l", conId),
                        getval("strike", conId), getval("exp", conId),
                        getval("dte", conId), getval("itm?", conId),
                    )

        first = True
        for symbol, position in portfolio_positions.items():
            if not first:
                table.add_section()
            first = False
            add_symbol_positions(symbol, position)

        if untracked_positions:
            table.add_section()
            table.add_row("Not tracked")
            table.add_section()
            first_untracked = True
            for symbol, position in untracked_positions.items():
                if not first_untracked:
                    table.add_section()
                first_untracked = False
                add_symbol_positions(symbol, position)

        log.print(table)
        return account_summary, portfolio_positions

    async def manage(self) -> None:
        had_error = False
        try:
            if self.data_store:
                self.data_store.record_event("run_start", {"dry_run": self.dry_run})
            self.initialize_account()
            account_summary, portfolio_positions = await self.summarize_account()

            enabled_stages = set(self.run_stage_order)

            for stage_id in self.run_stage_order:
                if stage_id == "equity_grid_spread":
                    await run_grid_spread_stages(
                        self._grid_strategy_deps(enabled_stages),
                        account_summary,
                        portfolio_positions,
                    )

            if self.dry_run:
                log.warning("Dry run enabled, no trades will be executed.")
                self.orders.print_summary()
            else:
                self.submit_orders()

                try:
                    await self.ibkr.wait_for_submitting_orders(self.trades.records())
                except RuntimeError as exc:
                    log.warning(f"Order submission wait timed out: {exc}")

                await self.adjust_prices()

                try:
                    await self.ibkr.wait_for_submitting_orders(self.trades.records())
                except RuntimeError as exc:
                    log.warning(f"Post-adjust order submission wait timed out: {exc}")

                working_statuses = {"PendingSubmit", "PreSubmitted", "Submitted"}
                incomplete_trades = [t for t in self.trades.records() if t and not t.isDone()]
                still_working = [
                    t for t in incomplete_trades
                    if getattr(t.orderStatus, "status", "") in working_statuses
                ]
                unexpected_state = [t for t in incomplete_trades if t not in still_working]

                if still_working:
                    open_orders = ", ".join(
                        f"{t.contract.symbol} (OrderId: {t.order.orderId}, "
                        f"status={getattr(t.orderStatus, 'status', 'UNKNOWN')})"
                        for t in still_working
                    )
                    log.info(f"Working orders still open at broker: {open_orders}")

                if unexpected_state:
                    unexpected_orders = ", ".join(
                        f"{t.contract.symbol} (OrderId: {t.order.orderId}, "
                        f"status={getattr(t.orderStatus, 'status', 'UNKNOWN')})"
                        for t in unexpected_state
                    )
                    log.warning(f"Non-working incomplete orders at broker: {unexpected_orders}")

            log.info("ThetaGang is done, shutting down! Cya next time. :sparkles:")
        except:
            had_error = True
            log.error("ThetaGang terminated with error...")
            raise
        finally:
            if self.data_store:
                self.data_store.record_event("run_end", {"success": not had_error})
            self.completion_future.set_result(True)

    def get_buying_power(self, account_summary: Dict[str, AccountValue]) -> int:
        margin_usage = float(self.config.runtime.account.margin_usage)
        return math.floor(float(account_summary["NetLiquidation"].value) * margin_usage)

    def submit_orders(self) -> None:
        for contract, order, intent_id in self.orders.records():
            self.trades.submit_order(contract, order, intent_id=intent_id)

    async def adjust_prices(self) -> None:
        symbols = self.get_symbols()
        for idx, (contract, order, _) in enumerate(self.orders.records()):
            if contract is None or contract.symbol not in symbols:
                continue
            symbol_cfg = self.config.strategies.grid.symbols.get(contract.symbol)
            if not symbol_cfg:
                continue
            trade = self.trades.get(idx)
            if trade is None or trade.isDone():
                continue

            delay = random.randint(
                self.config.runtime.orders.price_update_delay[0],
                self.config.runtime.orders.price_update_delay[1],
            )
            await asyncio.sleep(delay)

            if trade.isDone():
                continue

            try:
                ticker = await self.ibkr.get_ticker_for_contract(
                    contract,
                    required_fields=[],
                    optional_fields=[TickerField.MIDPOINT, TickerField.MARKET_PRICE],
                )
                new_price = round(float(midpoint_or_market_price(ticker)), 2)
                if new_price <= 0:
                    continue
                self.ibkr.cancel_order(trade.order)
                new_order = self.order_ops.create_limit_order(
                    action=order.action,
                    quantity=order.totalQuantity,
                    limit_price=new_price,
                    use_default_algo=False,
                    order_ref=getattr(order, "orderRef", None),
                )
                self.trades.submit_order(contract, new_order, idx=idx)
            except Exception as exc:
                log.warning(f"{contract.symbol}: Price adjustment failed: {exc}")
