import math
from typing import Any, Dict

from rich import box

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from schema import And, Optional, Or, Schema

import theta.config_defaults as config_defaults
from theta.dict_merge import dict_merge
from theta.fmt import pfmt, ffmt, dfmt
#from theta.thetagang import console
from theta.util import get_write_threshold_sigma, get_write_threshold_perc, get_target_delta, get_strike_limit, \
    maintain_high_water_mark

error_console = Console(stderr=True, style="bold red")

console = Console()


def normalize_config(config: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    # Do any pre-processing necessary to the config here, such as handling
    # defaults, deprecated values, config changes, etc.

    if "twsVersion" in config["ibc"]:
        error_console.print(
            "WARNING: config param ibc.twsVersion is deprecated, please remove it from your config.",
        )

        # TWS version is pinned to latest stable, delete any existing config if it's present
        del config["ibc"]["twsVersion"]

    if "maximum_new_contracts" in config["target"]:
        error_console.print(
            "WARNING: config param target.maximum_new_contracts is deprecated, please remove it from your config.",
        )

        del config["target"]["maximum_new_contracts"]

    # xor: should have weight OR parts, but not both
    if any(["weight" in s for s in config["symbols"].values()]) == any(
        ["parts" in s for s in config["symbols"].values()]
    ):
        raise RuntimeError(
            "ERROR: all symbols should have either a weight or parts specified, but parts and weights cannot be mixed."
        )

    if "parts" in list(config["symbols"].values())[0]:
        # If using "parts" instead of "weight", convert parts into weights
        total_parts = float(sum([s["parts"] for s in config["symbols"].values()]))
        for k in config["symbols"].keys():
            config["symbols"][k]["weight"] = config["symbols"][k]["parts"] / total_parts
        for s in config["symbols"].values():
            del s["parts"]

    if (
        "close_at_pnl" in config["roll_when"]
        and config["roll_when"]["close_at_pnl"]
        and config["roll_when"]["close_at_pnl"] <= config["roll_when"]["min_pnl"]
    ):
        raise RuntimeError("ERROR: roll_when.close_at_pnl needs to be greater than roll_when.min_pnl.")

    return apply_default_values(config)


def apply_default_values(config: Dict[str, Dict[str, Any]],) -> Dict[str, Dict[str, Any]]:
    return dict_merge(config_defaults.DEFAULT_CONFIG, config)


def validate_config(config: Dict[str, Dict[str, Any]]) -> None:
    if "minimum_cushion" in config["account"]:
        raise RuntimeError(
            "Config error: minimum_cushion is deprecated and replaced with margin_usage. See sample config for details."
        )

    algo_settings = {
        "strategy": And(str, len),
        "params": [And([str], lambda p: len(p) == 2)],  # type: ignore
    }

    schema = Schema(
        {
            "account": {
                "number": And(str, len),
                "cancel_orders": bool,
                "margin_usage": And(float, lambda n: 0 <= n),
                "market_data_type": And(int, lambda n: 1 <= n <= 4),
            },
            "orders": {
                Optional("exchange"): And(str, len),
                Optional("algo"): algo_settings,
                Optional("price_update_delay"): And([int], lambda p: len(p) == 2),  # type: ignore
                Optional("minimum_credit"): And(float, lambda n: 0 <= n),
            },
            "option_chains": {
                "expirations": And(int, lambda n: 1 <= n),
                "strikes": And(int, lambda n: 1 <= n),
            },
            Optional("write_when"): {
                Optional("calculate_net_contracts"): bool,
                Optional("calls"): {
                    Optional("green"): bool,
                    Optional("red"): bool,
                    Optional("cap_factor"): And(float, lambda n: 0 <= n <= 1),
                    Optional("cap_target_floor"): And(float, lambda n: 0 <= n <= 1),
                },
                Optional("puts"): {
                    Optional("green"): bool,
                    Optional("red"): bool,
                },
            },
            "roll_when": {
                "pnl": And(float, lambda n: 0 <= n <= 1),
                "dte": And(int, lambda n: 0 <= n),
                "min_pnl": float,
                Optional("close_at_pnl"): float,
                Optional("close_if_unable_to_roll"): bool,
                Optional("max_dte"): And(int, lambda n: 1 <= n),
                Optional("calls"): {
                    Optional("itm"): bool,
                    Optional("always_when_itm"): bool,
                    Optional("credit_only"): bool,
                    Optional("has_excess"): bool,
                    Optional("maintain_high_water_mark"): bool,
                },
                Optional("puts"): {
                    Optional("itm"): bool,
                    Optional("always_when_itm"): bool,
                    Optional("credit_only"): bool,
                    Optional("has_excess"): bool,
                },
            },
            "target": {
                "dte": And(int, lambda n: 0 <= n),
                "delta": And(float, lambda n: 0 <= n <= 1),
                Optional("max_dte"): And(int, lambda n: 1 <= n),
                Optional("maximum_new_contracts"): And(int, lambda n: 1 <= n),
                Optional("maximum_new_contracts_percent"): And(float, lambda n: 0 <= n <= 1),
                "minimum_open_interest": And(int, lambda n: 0 <= n),
                Optional("calls"): {
                    Optional("delta"): And(float, lambda n: 0 <= n <= 1),
                },
                Optional("puts"): {
                    Optional("delta"): And(float, lambda n: 0 <= n <= 1),
                },
            },
            "symbols": {
                object: {
                    Or("weight", "parts", only_one=True): And(
                        Or(float, int),
                        lambda n: 0 <= n <= 1 if isinstance(n, float) else n > 0,
                    ),
                    Optional("primary_exchange"): And(str, len),
                    Optional("delta"): And(float, lambda n: 0 <= n <= 1),
                    Optional("write_threshold"): And(float, lambda n: 0 <= n <= 1),
                    Optional("write_threshold_sigma"): And(float, lambda n: n > 0),
                    Optional("max_dte"): And(int, lambda n: 1 <= n),
                    Optional("dte"): And(int, lambda n: 0 <= n),
                    Optional("close_if_unable_to_roll"): bool,
                    Optional("calls"): {
                        Optional("delta"): And(float, lambda n: 0 <= n <= 1),
                        Optional("write_threshold"): And(float, lambda n: 0 <= n <= 1),
                        Optional("write_threshold_sigma"): And(float, lambda n: n > 0),
                        Optional("strike_limit"): And(float, lambda n: n > 0),
                        Optional("maintain_high_water_mark"): bool,
                        Optional("cap_factor"): And(float, lambda n: 0 <= n <= 1),
                        Optional("cap_target_floor"): And(float, lambda n: 0 <= n <= 1),
                        Optional("write_when"): {
                            Optional("green"): bool,
                            Optional("red"): bool,
                        },
                    },
                    Optional("puts"): {
                        Optional("delta"): And(float, lambda n: 0 <= n <= 1),
                        Optional("write_threshold"): And(float, lambda n: 0 <= n <= 1),
                        Optional("write_threshold_sigma"): And(float, lambda n: n > 0),
                        Optional("strike_limit"): And(float, lambda n: n > 0),
                        Optional("write_when"): {
                            Optional("green"): bool,
                            Optional("red"): bool,
                        },
                    },
                    Optional("adjust_price_after_delay"): bool,
                }
            },
            Optional("ib_insync"): {
                Optional("logfile"): And(str, len),
                Optional("api_response_wait_time"): int,
            },
            "ibc": {
                Optional("password"): And(str, len),
                Optional("userid"): And(str, len),
                Optional("gateway"): bool,
                Optional("RaiseRequestErrors"): bool,
                Optional("ibcPath"): And(str, len),
                Optional("tradingMode"): And(str, len, lambda s: s in ("live", "paper")),
                Optional("ibcIni"): And(str, len),
                Optional("twsPath"): And(str, len),
                Optional("twsSettingsPath"): And(str, len),
                Optional("javaPath"): And(str, len),
                Optional("fixuserid"): And(str, len),
                Optional("fixpassword"): And(str, len),
            },
            "watchdog": {
                Optional("appStartupTime"): int,
                Optional("appTimeout"): int,
                Optional("clientId"): int,
                Optional("connectTimeout"): int,
                Optional("host"): And(str, len),
                Optional("port"): int,
                Optional("probeTimeout"): int,
                Optional("readonly"): bool,
                Optional("retryDelay"): int,
                Optional("probeContract"): {
                    Optional("currency"): And(str, len),
                    Optional("exchange"): And(str, len),
                    Optional("secType"): And(str, len),
                    Optional("symbol"): And(str, len),
                },
            },
            Optional("vix_call_hedge"): {
                "enabled": bool,
                Optional("delta"): And(float, lambda n: 0 <= n <= 1),
                Optional("target_dte"): And(int, lambda n: n > 0),
                Optional("close_hedges_when_vix_exceeds"): float,
                Optional("ignore_dte"): And(int, lambda n: n >= 0),
                Optional("max_dte"): And(int, lambda n: 1 <= n),
                Optional("allocation"): [
                    {
                        Optional("lower_bound"): float,
                        Optional("upper_bound"): float,
                        Optional("weight"): float,
                    },
                ],
            },
            Optional("cash_management"): {
                Optional("enabled"): bool,
                Optional("cash_fund"): And(str, len),
                Optional("primary_exchange"): And(str, len),
                Optional("target_cash_balance"): int,
                Optional("buy_threshold"): And(int, lambda n: n > 0),
                Optional("sell_threshold"): And(int, lambda n: n > 0),
                Optional("primary_exchange"): And(str, len),
                Optional("orders"): {
                    "exchange": And(str, len),
                    "algo": algo_settings,
                },
            },
            Optional("constants"): {
                Optional("daily_stddev_window"): And(str, len),
                Optional("write_threshold"): And(float, lambda n: 0 <= n <= 1),
                Optional("write_threshold_sigma"): And(float, lambda n: n > 0),
                Optional("calls"): {
                    Optional("write_threshold"): And(float, lambda n: 0 <= n <= 1),
                    Optional("write_threshold_sigma"): And(float, lambda n: n > 0),
                },
                Optional("puts"): {
                    Optional("write_threshold"): And(float, lambda n: 0 <= n <= 1),
                    Optional("write_threshold_sigma"): And(float, lambda n: n > 0),
                },
            },
        }
    )
    schema.validate(config)  # type: ignore

    assert len(config["symbols"]) > 0

    assert math.isclose(1, sum([s["weight"] for s in config["symbols"].values()]), rel_tol=1e-5)


def draw_config_table(console, config: dict, config_path: str):
    config_table = Table(box=box.SIMPLE_HEAVY)
    config_table.add_column("Section")
    config_table.add_column("Setting")
    config_table.add_column("")
    config_table.add_column("Value")
    config_table.add_row("[spring_green1]Account details")
    config_table.add_row("", "Account number", "=", config["account"]["number"])
    config_table.add_row("", "Cancel existing orders", "=", f'{config["account"]["cancel_orders"]}')
    config_table.add_row(
        "",
        "Margin usage",
        "=",
        f"{config['account']['margin_usage']} ({pfmt(config['account']['margin_usage'], 0)})",
    )
    config_table.add_row("", "Market data type", "=", f'{config["account"]["market_data_type"]}')
    config_table.add_section()
    config_table.add_row("[spring_green1]Constants")
    config_table.add_row(
        "",
        "Daily stddev window",
        "=",
        f"{config['constants']['daily_stddev_window']}",
    )
    c_write_thresh = (
        f"{ffmt(get_write_threshold_sigma(config, None, 'C'))}σ"
        if get_write_threshold_sigma(config, None, "C")
        else pfmt(get_write_threshold_perc(config, None, "C"))
    )
    p_write_thresh = (
        f"{ffmt(get_write_threshold_sigma(config, None, 'P'))}σ"
        if get_write_threshold_sigma(config, None, "P")
        else pfmt(get_write_threshold_perc(config, None, "P"))
    )
    config_table.add_row("", "Write threshold for puts", "=", p_write_thresh)
    config_table.add_row("", "Write threshold for calls", "=", c_write_thresh)
    config_table.add_section()
    config_table.add_row("[spring_green1]Order settings")
    config_table.add_row(
        "",
        "Exchange",
        "=",
        f"{config['orders']['exchange']}",
    )
    config_table.add_row(
        "",
        "Params",
        "=",
        f"{config['orders']['algo']['params']}",
    )
    config_table.add_row(
        "",
        "Price update delay",
        "=",
        f"{config['orders']['price_update_delay']}",
    )
    config_table.add_row(
        "",
        "Minimum credit",
        "=",
        f"{dfmt(config['orders']['minimum_credit'])}",
    )
    config_table.add_section()
    config_table.add_row("[spring_green1]Close option positions")
    config_table.add_row(
        "",
        "When P&L",
        ">=",
        f"{pfmt(config['roll_when']['close_at_pnl'], 0)}",
    )
    config_table.add_row(
        "",
        "Close if unable to roll",
        "=",
        f"{config['roll_when']['close_if_unable_to_roll']}",
    )
    config_table.add_section()
    config_table.add_row("[spring_green1]Roll options when either condition is true")
    config_table.add_row(
        "",
        "Days to expiry",
        "<=",
        f"{config['roll_when']['dte']} and P&L >= {config['roll_when']['min_pnl']} ({pfmt(config['roll_when']['min_pnl'], 0)})",
    )
    if "max_dte" in config["roll_when"]:
        config_table.add_row(
            "",
            "P&L",
            ">=",
            f"{config['roll_when']['pnl']} ({pfmt(config['roll_when']['pnl'], 0)}) and DTE <= {config['roll_when']['max_dte']}",
        )
    else:
        config_table.add_row(
            "",
            "P&L",
            ">=",
            f"{config['roll_when']['pnl']} ({pfmt(config['roll_when']['pnl'], 0)})",
        )
    config_table.add_row(
        "",
        "Puts: credit only",
        "=",
        f"{config['roll_when']['puts']['credit_only']}",
    )
    config_table.add_row(
        "",
        "Puts: roll excess",
        "=",
        f"{config['roll_when']['puts']['has_excess']}",
    )
    config_table.add_row(
        "",
        "Calls: credit only",
        "=",
        f"{config['roll_when']['calls']['credit_only']}",
    )
    config_table.add_row(
        "",
        "Calls: roll excess",
        "=",
        f"{config['roll_when']['calls']['has_excess']}",
    )
    config_table.add_row(
        "",
        "Calls: maintain high water mark",
        "=",
        f"{config['roll_when']['calls']['maintain_high_water_mark']}",
    )
    config_table.add_section()
    config_table.add_row("[spring_green1]When writing new contracts")
    config_table.add_row(
        "",
        "Calculate net contract positions",
        "=",
        f"{config['write_when']['calculate_net_contracts']}",
    )
    config_table.add_row(
        "",
        "Puts, write when red",
        "=",
        f"{config['write_when']['puts']['red']}",
    )
    config_table.add_row(
        "",
        "Puts, write when green",
        "=",
        f"{config['write_when']['puts']['green']}",
    )
    config_table.add_row(
        "",
        "Calls, write when green",
        "=",
        f"{config['write_when']['calls']['green']}",
    )
    config_table.add_row(
        "",
        "Calls, write when red",
        "=",
        f"{config['write_when']['calls']['red']}",
    )
    config_table.add_row(
        "",
        "Call cap factor",
        "=",
        f"{pfmt(config['write_when']['calls']['cap_factor'])}",
    )
    config_table.add_row(
        "",
        "Call cap target floor",
        "=",
        f"{pfmt(config['write_when']['calls']['cap_target_floor'])}",
    )
    config_table.add_section()
    config_table.add_row("[spring_green1]When contracts are ITM")
    config_table.add_row(
        "",
        "Roll puts",
        "=",
        f"{config['roll_when']['puts']['itm']}",
    )
    config_table.add_row(
        "",
        "Roll puts always",
        "=",
        f"{config['roll_when']['puts']['always_when_itm']}",
    )
    config_table.add_row(
        "",
        "Roll calls",
        "=",
        f"{config['roll_when']['calls']['itm']}",
    )
    config_table.add_row(
        "",
        "Roll calls always",
        "=",
        f"{config['roll_when']['calls']['always_when_itm']}",
    )
    config_table.add_section()
    config_table.add_row("[spring_green1]Write options with targets of")
    config_table.add_row("", "Days to expiry", ">=", f"{config['target']['dte']}")
    if "max_dte" in config["target"]:
        config_table.add_row("", "Days to expiry", "<=", f"{config['target']['max_dte']}")
    config_table.add_row("", "Default delta", "<=", f"{config['target']['delta']}")
    if "puts" in config["target"]:
        config_table.add_row(
            "",
            "Delta for puts",
            "<=",
            f"{config['target']['puts']['delta']}",
        )
    if "calls" in config["target"]:
        config_table.add_row(
            "",
            "Delta for calls",
            "<=",
            f"{config['target']['calls']['delta']}",
        )
    config_table.add_row(
        "",
        "Maximum new contracts",
        "=",
        f"{pfmt(config['target']['maximum_new_contracts_percent'], 0)} of buying power",
    )
    config_table.add_row(
        "",
        "Minimum open interest",
        "=",
        f"{config['target']['minimum_open_interest']}",
    )
    config_table.add_section()
    config_table.add_row("[spring_green1]Cash management")
    config_table.add_row("", "Enabled", "=", f"{config['cash_management']['enabled']}")
    config_table.add_row("", "Cash fund", "=", f"{config['cash_management']['cash_fund']}")
    config_table.add_row(
        "",
        "Target cash",
        "=",
        f"{dfmt(config['cash_management']['target_cash_balance'])}",
    )
    config_table.add_row(
        "",
        "Buy threshold",
        "=",
        f"{dfmt(config['cash_management']['buy_threshold'])}",
    )
    config_table.add_row(
        "",
        "Sell threshold",
        "=",
        f"{dfmt(config['cash_management']['sell_threshold'])}",
    )
    config_table.add_section()
    config_table.add_row("[spring_green1]Hedging with VIX calls")
    config_table.add_row("", "Enabled", "=", f"{config['vix_call_hedge']['enabled']}")
    config_table.add_row(
        "",
        "Target delta",
        "<=",
        f"{config['vix_call_hedge']['delta']}",
    )
    config_table.add_row(
        "",
        "Target DTE",
        ">=",
        f"{config['vix_call_hedge']['target_dte']}",
    )
    config_table.add_row(
        "",
        "Ignore DTE",
        "<=",
        f"{config['vix_call_hedge']['ignore_dte']}",
    )
    config_table.add_row(
        "",
        "Ignore DTE",
        "<=",
        f"{config['vix_call_hedge']['ignore_dte']}",
    )
    config_table.add_row(
        "",
        "Close hedges when VIX",
        ">=",
        f"{config['vix_call_hedge']['close_hedges_when_vix_exceeds']}",
    )
    for alloc in config["vix_call_hedge"]["allocation"]:
        config_table.add_row()
        if "lower_bound" in alloc:
            config_table.add_row(
                "",
                f"Allocate {pfmt(alloc['weight'])} when VIXMO",
                ">=",
                f"{alloc['lower_bound']}",
            )
        if "upper_bound" in alloc:
            config_table.add_row(
                "",
                f"Allocate {pfmt(alloc['weight'])} when VIXMO",
                "<=",
                f"{alloc['upper_bound']}",
            )
    symbols_table = Table(
        title="Configured symbols and target weights",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
    )
    symbols_table.add_column("Symbol")
    symbols_table.add_column("Weight", justify="right")
    symbols_table.add_column("Call delta", justify="right")
    symbols_table.add_column("Call strike limit", justify="right")
    symbols_table.add_column("Call threshold", justify="right")
    symbols_table.add_column("HWM", justify="right")
    symbols_table.add_column("Put delta", justify="right")
    symbols_table.add_column("Put strike limit", justify="right")
    symbols_table.add_column("Put threshold", justify="right")
    for symbol, sconfig in config["symbols"].items():
        symbols_table.add_row(
            symbol,
            pfmt(sconfig["weight"]),
            ffmt(get_target_delta(config, symbol, "C")),
            dfmt(get_strike_limit(config, symbol, "C")),
            (
                f"{ffmt(get_write_threshold_sigma(config, symbol, 'C'))}σ"
                if get_write_threshold_sigma(config, symbol, "C")
                else pfmt(get_write_threshold_perc(config, symbol, "C"))
            ),
            str(maintain_high_water_mark(config, symbol)),
            ffmt(get_target_delta(config, symbol, "P")),
            dfmt(get_strike_limit(config, symbol, "P")),
            (
                f"{ffmt(get_write_threshold_sigma(config, symbol, 'P'))}σ"
                if get_write_threshold_sigma(config, symbol, "P")
                else pfmt(get_write_threshold_perc(config, symbol, "P"))
            ),
        )
    assert round(sum([config["symbols"][s]["weight"] for s in config["symbols"].keys()]), 5) == 1.00000
    tree = Tree(":control_knobs:")
    tree.add(Group(f":file_cabinet: Loaded from {config_path}", config_table))
    tree.add(Group(":yin_yang: Symbology", symbols_table))
    console.print(Panel(tree, title="Config"))
