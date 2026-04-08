from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Protocol

from ib_async import AccountValue, PortfolioItem

if TYPE_CHECKING:
    pass


class GridSpreadService(Protocol):
    async def run_grid(
        self,
        account_summary: Dict,
        portfolio_positions: Dict[str, List[PortfolioItem]],
    ) -> None: ...


@dataclass
class GridStrategyDeps:
    enabled_stages: set[str]
    service: GridSpreadService


async def run_grid_spread_stages(
    deps: GridStrategyDeps,
    account_summary: Dict[str, AccountValue],
    portfolio_positions: Dict[str, List[PortfolioItem]],
) -> None:
    if "equity_grid_spread" not in deps.enabled_stages:
        return
    await deps.service.run_grid(account_summary, portfolio_positions)
