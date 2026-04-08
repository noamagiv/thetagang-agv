import logging

import click
import click_log

logger = logging.getLogger(__name__)
click_log.basic_config(logger)


CONTEXT_SETTINGS = dict(
    help_option_names=["-h", "--help"], auto_envvar_prefix="THETAGANG"
)


@click.command(context_settings=CONTEXT_SETTINGS)
@click_log.simple_verbosity_option(logger, default="WARNING")
@click.option(
    "-c",
    "--config",
    help="Path to toml config",
    required=True,
    default="thetagang.toml",
    type=click.Path(exists=True, readable=True),
)
@click.option(
    "--without-ibc",
    is_flag=True,
    help="Run without IBC. Enable this if you want to run the TWS "
    "gateway yourself, without having ThetaGang manage it for you.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Perform a dry run. Displays orders without submitting live trades.",
)
def cli(
    config: str,
    without_ibc: bool,
    dry_run: bool,
) -> None:
    """ThetaGang grid credit spread bot for IBKR."""

    if logger.getEffectiveLevel() > logging.INFO:
        logging.getLogger("alembic").setLevel(logging.WARNING)
        logging.getLogger("alembic.runtime.migration").setLevel(logging.WARNING)
        logging.getLogger("ib_async").setLevel(logging.WARNING)
        logging.getLogger("ib_async.client").setLevel(logging.WARNING)

    from .thetagang import start

    start(config, without_ibc, dry_run)
