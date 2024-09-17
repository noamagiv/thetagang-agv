from asyncio import Future
from ctypes import c_voidp

from ib_insync import IB, IBC, Watchdog, util
from ib_insync.contract import Contract
from rich.console import Console

from theta.config import apply_default_values, normalize_config, validate_config, draw_config_table

from .portfolio_manager import PortfolioManager

util.patchAsyncio()

console = Console()


def start(config_path: str, without_ibc: bool = False) -> None:
    import toml

    with open(config_path, "r", encoding="utf8") as file:
        config = toml.load(file)

    config = normalize_config(config)

    validate_config(config)

    draw_config_table(console, config, config_path)

    print(config.keys())

    draw_config_table(config, config_path)

    if config.get("ib_insync", {}).get("logfile"):
        util.logToFile(config["ib_insync"]["logfile"])  # type: ignore

    def onConnected() -> None:
        portfolio_manager.manage()

    ib = IB()
    ib.connectedEvent += onConnected

    completion_future: Future[bool] = Future()
    portfolio_manager = PortfolioManager(config, ib, completion_future)

    probeContractConfig = config["watchdog"]["probeContract"]
    watchdogConfig = config.get("watchdog", {})
    del watchdogConfig["probeContract"]
    probeContract = Contract(
        secType=probeContractConfig["secType"],
        symbol=probeContractConfig["symbol"],
        currency=probeContractConfig["currency"],
        exchange=probeContractConfig["exchange"],
    )

    if not without_ibc:
        # TWS version is pinned to current stable
        ibc_config = config.get("ibc", {})
        # Remove any config params that aren't valid keywords for IBC
        ibc_keywords = {k: ibc_config[k] for k in ibc_config if k not in ["RaiseRequestErrors"]}
        ibc = IBC(1019, **ibc_keywords)

        ib.RaiseRequestErrors = ibc_config.get("RaiseRequestErrors", False)

        watchdog = Watchdog(ibc, ib, probeContract=probeContract, **watchdogConfig)
        watchdog.start()

        ib.run(completion_future)  # type: ignore
        watchdog.stop()
        ibc.terminate()
    else:

        ib.connect(
            watchdogConfig["host"],
            watchdogConfig["port"],
            clientId=watchdogConfig["clientId"],
            timeout=watchdogConfig["probeTimeout"],
            account=config["account"]["number"],
        )
        ib.run(completion_future)  # type: ignore
        ib.disconnect()


