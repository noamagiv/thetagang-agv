from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from thetagang.config_models import (
    AccountConfig,
    DatabaseConfig,
    DisplayMixin,
    ExchangeHoursConfig,
    GridCreditSpreadStrategyConfig,
    IBAsyncConfig,
    IBCConfig,
    OptionChainsConfig,
    OrdersConfig,
    WatchdogConfig,
)

STAGE_KIND_BY_ID: dict[str, str] = {
    "equity_grid_spread": "equity.grid_spread",
}

CANONICAL_STAGE_ORDER: list[str] = [
    "equity_grid_spread",
]

RUN_STRATEGY_IDS = {
    "grid",
}

STRATEGY_STAGE_IDS: dict[str, set[str]] = {
    "grid": {"equity_grid_spread"},
}

DEFAULT_RUN_STRATEGIES: list[str] = ["grid"]


class ConfigMeta(BaseModel):
    schema_version: int = Field(2)

    @model_validator(mode="after")
    def validate_schema_version(self) -> "ConfigMeta":
        if self.schema_version != 2:
            raise ValueError("meta.schema_version must be 2")
        return self


class RunStageConfig(BaseModel):
    id: str
    kind: str
    enabled: bool = True
    depends_on: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_stage_identity(self) -> "RunStageConfig":
        expected_kind = STAGE_KIND_BY_ID.get(self.id)
        if expected_kind is None:
            raise ValueError(f"run.stages contains unknown stage id: {self.id}")
        if self.kind != expected_kind:
            raise ValueError(
                f"run.stages.{self.id}.kind must be {expected_kind}, got {self.kind}"
            )
        return self


class RunConfig(BaseModel):
    stages: List[RunStageConfig] = Field(default_factory=list)
    strategies: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_run_config(self) -> "RunConfig":
        if not self.stages and not self.strategies:
            raise ValueError(
                "run must define at least one of run.strategies or run.stages"
            )
        if self.stages and self.strategies:
            raise ValueError(
                "run must define exactly one of run.strategies or run.stages, not both"
            )

        if self.strategies:
            unknown = [s for s in self.strategies if s not in RUN_STRATEGY_IDS]
            if unknown:
                raise ValueError(
                    f"run.strategies contains unknown strategy id(s): {', '.join(unknown)}"
                )
            if len(set(self.strategies)) != len(self.strategies):
                raise ValueError("run.strategies must not contain duplicates")
            return self

        stage_ids = [s.id for s in self.stages]
        if len(set(stage_ids)) != len(stage_ids):
            raise ValueError("run.stages ids must be unique")
        seen = set(stage_ids)
        index_by_id = {stage.id: idx for idx, stage in enumerate(self.stages)}
        for stage in self.stages:
            for dep in stage.depends_on:
                if dep not in seen:
                    raise ValueError(
                        f"run.stages.{stage.id} depends_on unknown stage {dep}"
                    )
                if index_by_id[dep] >= index_by_id[stage.id]:
                    raise ValueError(
                        f"run.stages.{stage.id} depends_on {dep} must appear earlier"
                    )

        enabled_by_id = {stage.id: stage.enabled for stage in self.stages}
        for stage in self.stages:
            if stage.enabled and any(
                not enabled_by_id[dep] for dep in stage.depends_on
            ):
                raise ValueError(
                    f"run.stages.{stage.id} is enabled but depends on a disabled stage"
                )

        graph: dict[str, list[str]] = defaultdict(list)
        for stage in self.stages:
            graph[stage.id].extend(stage.depends_on)
        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(node: str) -> None:
            if node in visiting:
                raise ValueError(
                    f"run.stages contains a dependency cycle involving {node}"
                )
            if node in visited:
                return
            visiting.add(node)
            for dep in graph[node]:
                dfs(dep)
            visiting.remove(node)
            visited.add(node)

        for stage_id in graph:
            dfs(stage_id)

        return self

    def resolved_stages(self) -> List[RunStageConfig]:
        if self.stages:
            return list(self.stages)

        enabled: set[str] = set()
        for strategy_id in self.strategies:
            enabled.update(STRATEGY_STAGE_IDS[strategy_id])

        ordered_ids = [
            stage_id for stage_id in CANONICAL_STAGE_ORDER if stage_id in enabled
        ]
        resolved: List[RunStageConfig] = []
        prev: Optional[str] = None
        for stage_id in ordered_ids:
            deps: List[str] = [prev] if prev else []
            resolved.append(
                RunStageConfig(
                    id=stage_id,
                    kind=STAGE_KIND_BY_ID[stage_id],
                    enabled=True,
                    depends_on=deps,
                )
            )
            prev = stage_id
        return resolved


class RuntimeConfig(BaseModel):
    account: AccountConfig
    option_chains: OptionChainsConfig
    exchange_hours: ExchangeHoursConfig = Field(default_factory=ExchangeHoursConfig)
    orders: OrdersConfig = Field(default_factory=OrdersConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    ib_async: IBAsyncConfig = Field(default_factory=IBAsyncConfig)
    ibc: IBCConfig = Field(default_factory=IBCConfig)
    watchdog: WatchdogConfig = Field(default_factory=WatchdogConfig)


class StrategiesConfig(BaseModel):
    grid: GridCreditSpreadStrategyConfig


class Config(BaseModel, DisplayMixin):
    model_config = ConfigDict(extra="forbid")

    meta: ConfigMeta = Field(default_factory=ConfigMeta)
    run: RunConfig
    runtime: RuntimeConfig
    strategies: StrategiesConfig

    @property
    def account(self) -> AccountConfig:
        return self.runtime.account

    @property
    def option_chains(self) -> OptionChainsConfig:
        return self.runtime.option_chains

    @property
    def exchange_hours(self) -> ExchangeHoursConfig:
        return self.runtime.exchange_hours

    @property
    def orders(self) -> OrdersConfig:
        return self.runtime.orders

    @property
    def database(self) -> DatabaseConfig:
        return self.runtime.database

    @property
    def ib_async(self) -> IBAsyncConfig:
        return self.runtime.ib_async

    @property
    def ibc(self) -> IBCConfig:
        return self.runtime.ibc

    @property
    def watchdog(self) -> WatchdogConfig:
        return self.runtime.watchdog

    def display(self, config_path: str) -> None:
        console = Console()
        config_table = Table(box=box.SIMPLE_HEAVY)
        config_table.add_column("Section")
        config_table.add_column("Setting")
        config_table.add_column("")
        config_table.add_column("Value")

        self.account.add_to_table(config_table)
        self.exchange_hours.add_to_table(config_table)
        self.orders.add_to_table(config_table)
        self.database.add_to_table(config_table)
        self.strategies.grid.add_to_table(config_table)

        tree = Tree(":control_knobs:")
        tree.add(Group(f":file_cabinet: Loaded from {config_path}", config_table))
        console.print(Panel(tree, title="Config"))


def enabled_stage_ids_from_run(run: RunConfig) -> List[str]:
    return [stage.id for stage in run.resolved_stages() if stage.enabled]


def stage_enabled_map(config: Config) -> Dict[str, bool]:
    return stage_enabled_map_from_run(config.run)


def stage_enabled_map_from_run(run: RunConfig) -> Dict[str, bool]:
    resolved_ids = set(enabled_stage_ids_from_run(run))
    return {stage_id: (stage_id in resolved_ids) for stage_id in STAGE_KIND_BY_ID}
