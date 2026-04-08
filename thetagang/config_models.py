from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator
from rich.console import Console
from rich.table import Table

from thetagang.fmt import dfmt, pfmt

error_console = Console(stderr=True, style="bold red")


class DisplayMixin:
    def add_to_table(self, table: Table, section: str = "") -> None:
        raise NotImplementedError


class AccountConfig(BaseModel, DisplayMixin):
    number: str = Field(...)
    margin_usage: float = Field(..., ge=0.0)
    cancel_orders: bool = Field(default=True)
    market_data_type: int = Field(default=1, ge=1, le=4)

    def add_to_table(self, table: Table, section: str = "") -> None:
        table.add_row("[spring_green1]Account details")
        table.add_row("", "Account number", "=", self.number)
        table.add_row("", "Cancel existing orders", "=", f"{self.cancel_orders}")
        table.add_row(
            "",
            "Margin usage",
            "=",
            f"{self.margin_usage} ({pfmt(self.margin_usage, 0)})",
        )
        table.add_row("", "Market data type", "=", f"{self.market_data_type}")


class OptionChainsConfig(BaseModel):
    expirations: int = Field(..., ge=1)
    strikes: int = Field(..., ge=1)


class AlgoSettingsConfig(BaseModel):
    strategy: str = Field("Adaptive")
    params: List[List[str]] = Field(
        default_factory=lambda: [["adaptivePriority", "Patient"]],
        min_length=0,
        max_length=1,
    )


class OrdersConfig(BaseModel, DisplayMixin):
    minimum_credit: float = Field(default=0.0, ge=0.0)
    exchange: str = Field(default="SMART")
    algo: AlgoSettingsConfig = Field(
        default=AlgoSettingsConfig(
            strategy="Adaptive", params=[["adaptivePriority", "Patient"]]
        )
    )
    price_update_delay: List[int] = Field(
        default_factory=lambda: [30, 60], min_length=2, max_length=2
    )

    def add_to_table(self, table: Table, section: str = "") -> None:
        table.add_section()
        table.add_row("[spring_green1]Order settings")
        table.add_row("", "Exchange", "=", self.exchange)
        table.add_row("", "Params", "=", f"{self.algo.params}")
        table.add_row("", "Price update delay", "=", f"{self.price_update_delay}")
        table.add_row("", "Minimum credit", "=", f"{dfmt(self.minimum_credit)}")


class IBAsyncConfig(BaseModel):
    api_response_wait_time: int = Field(default=60, ge=0)
    logfile: Optional[str] = None


class DatabaseConfig(BaseModel, DisplayMixin):
    enabled: bool = Field(default=True)
    path: str = Field(default="data/thetagang.db")
    url: Optional[str] = None

    def add_to_table(self, table: Table, section: str = "") -> None:
        table.add_section()
        table.add_row("[spring_green1]Database")
        table.add_row("", "Enabled", "=", f"{self.enabled}")
        table.add_row("", "Path", "=", self.path)
        if self.url:
            table.add_row("", "URL", "=", self.url)

    def resolve_url(self, config_path: str) -> str:
        if self.url:
            return self.url
        base_dir = Path(config_path).resolve().parent
        db_path = Path(self.path)
        if not db_path.is_absolute():
            db_path = base_dir / db_path
        return f"sqlite:///{db_path}"


class IBCConfig(BaseModel):
    tradingMode: Literal["live", "paper"] = Field(default="paper")
    password: Optional[str] = None
    userid: Optional[str] = None
    gateway: bool = Field(default=True)
    RaiseRequestErrors: bool = Field(default=False)
    ibcPath: str = Field(default="/opt/ibc")
    ibcIni: str = Field(default="/etc/thetagang/config.ini")
    twsPath: Optional[str] = None
    twsSettingsPath: Optional[str] = None
    javaPath: str = Field(default="/opt/java/openjdk/bin")
    fixuserid: Optional[str] = None
    fixpassword: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tradingMode": self.tradingMode,
            "password": self.password,
            "userid": self.userid,
            "gateway": self.gateway,
            "ibcPath": self.ibcPath,
            "ibcIni": self.ibcIni,
            "twsPath": self.twsPath,
            "twsSettingsPath": self.twsSettingsPath,
            "javaPath": self.javaPath,
            "fixuserid": self.fixuserid,
            "fixpassword": self.fixpassword,
        }


class WatchdogConfig(BaseModel):
    class ProbeContract(BaseModel):
        currency: str = Field(default="USD")
        exchange: str = Field(default="SMART")
        secType: str = Field(default="STK")
        symbol: str = Field(default="SPY")

    appStartupTime: int = Field(default=30)
    appTimeout: int = Field(default=20)
    clientId: int = Field(default=1)
    connectTimeout: int = Field(default=2)
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=7497)
    probeTimeout: int = Field(default=4)
    readonly: bool = Field(default=False)
    retryDelay: int = Field(default=2)
    probeContract: "WatchdogConfig.ProbeContract" = Field(
        default_factory=lambda: WatchdogConfig.ProbeContract()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "appStartupTime": self.appStartupTime,
            "appTimeout": self.appTimeout,
            "clientId": self.clientId,
            "connectTimeout": self.connectTimeout,
            "host": self.host,
            "port": self.port,
            "probeTimeout": self.probeTimeout,
            "readonly": self.readonly,
            "retryDelay": self.retryDelay,
        }


class ActionWhenClosedEnum(str, Enum):
    wait = "wait"
    exit = "exit"
    continue_ = "continue"


class ExchangeHoursConfig(BaseModel, DisplayMixin):
    exchange: str = Field(default="XNYS")
    action_when_closed: ActionWhenClosedEnum = Field(default=ActionWhenClosedEnum.exit)
    delay_after_open: int = Field(default=1800, ge=0)
    delay_before_close: int = Field(default=1800, ge=0)
    max_wait_until_open: int = Field(default=3600, ge=0)

    def add_to_table(self, table: Table, section: str = "") -> None:
        table.add_row("[spring_green1]Exchange hours")
        table.add_row("", "Exchange", "=", self.exchange)
        table.add_row("", "Action when closed", "=", self.action_when_closed)
        table.add_row("", "Delay after open", "=", f"{self.delay_after_open}s")
        table.add_row("", "Delay before close", "=", f"{self.delay_before_close}s")
        table.add_row("", "Max wait until open", "=", f"{self.max_wait_until_open}s")


# ---------------------------------------------------------------------------
# Grid credit spread strategy models
# ---------------------------------------------------------------------------


class GridBiasMode(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class GridBiasConfig(BaseModel):
    mode: GridBiasMode = GridBiasMode.NEUTRAL
    buy_levels: int = Field(default=5, ge=1)
    sell_levels: int = Field(default=5, ge=1)


class GridSymbolConfig(BaseModel):
    lower_bound: float = Field(..., gt=0)
    upper_bound: float = Field(..., gt=0)
    grid_spacing: Optional[float] = Field(default=None, gt=0)
    grid_spacing_pct: Optional[float] = Field(default=None, gt=0, lt=1)
    spread_width: float = Field(..., gt=0)
    contracts_per_level: int = Field(default=1, ge=1)
    target_dte: int = Field(default=30, ge=1)
    min_credit: float = Field(default=0.05, ge=0)
    max_loss_per_symbol: float = Field(..., gt=0)
    max_exposure_per_symbol: float = Field(..., gt=0)
    primary_exchange: str = Field(default="SMART")
    bias: GridBiasConfig = Field(default_factory=GridBiasConfig)

    @model_validator(mode="after")
    def validate_spacing_and_bounds(self) -> "GridSymbolConfig":
        if self.grid_spacing is None and self.grid_spacing_pct is None:
            raise ValueError("set grid_spacing or grid_spacing_pct")
        if self.grid_spacing is not None and self.grid_spacing_pct is not None:
            raise ValueError("only one of grid_spacing / grid_spacing_pct allowed")
        if self.upper_bound <= self.lower_bound:
            raise ValueError("upper_bound must exceed lower_bound")
        if self.spread_width >= (self.upper_bound - self.lower_bound):
            raise ValueError("spread_width must be smaller than grid range")
        return self


class GridCreditSpreadStrategyConfig(BaseModel, DisplayMixin):
    symbols: Dict[str, GridSymbolConfig]

    @model_validator(mode="after")
    def check_symbols(self) -> "GridCreditSpreadStrategyConfig":
        if not self.symbols:
            raise ValueError("grid strategy requires at least one symbol")
        return self

    def add_to_table(self, table: Table, section: str = "") -> None:
        table.add_section()
        table.add_row("[spring_green1]Grid credit spread strategy")
        for symbol, cfg in self.symbols.items():
            table.add_row("", f"{symbol} range", "=", f"${cfg.lower_bound} – ${cfg.upper_bound}")
            spacing = (
                f"${cfg.grid_spacing}" if cfg.grid_spacing else f"{cfg.grid_spacing_pct:.1%}"
            )
            table.add_row("", f"{symbol} spacing", "=", spacing)
            table.add_row("", f"{symbol} spread width", "=", f"${cfg.spread_width}")
            table.add_row("", f"{symbol} target DTE", "=", f"{cfg.target_dte}")
            table.add_row("", f"{symbol} min credit", "=", f"${cfg.min_credit}")
            table.add_row("", f"{symbol} max loss", "=", f"${cfg.max_loss_per_symbol:,.0f}")
            table.add_row("", f"{symbol} max exposure", "=", f"${cfg.max_exposure_per_symbol:,.0f}")
            table.add_row("", f"{symbol} bias", "=", f"{cfg.bias.mode.value} ({cfg.bias.buy_levels}B/{cfg.bias.sell_levels}S)")
