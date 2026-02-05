"""Main entry point for lsatfetch CLI."""

import logging
from pathlib import Path

import cyclopts

app = cyclopts.App(
    name="lsatfetch",
    help="CLI for creating Landsat image datasets",
)


def _setup_logging(level: int = logging.INFO) -> None:
    from lsatfetch.utils.log import setup

    setup(level=level)


@app.command  # type: ignore[misc]
def init(
    output: Path | None = None,
    force: bool = False,
) -> None:
    """
    Initialize a configuration template for Landsat dataset creation.

    Parameters
    ----------
    output : Path | None
        Path to save the configuration template.
        If not provided, saves to current directory or output_dir if specified.
    force : bool
        Overwrite existing configuration file. Defaults to False.
    """
    _setup_logging()
    from lsatfetch.cli.init import init as init_cmd

    init_cmd(output, force)


@app.command  # type: ignore[misc]
def get(
    config: Path,
    verbose: bool = False,
) -> None:
    """
    Create a Landsat dataset based on the provided configuration.

    Parameters
    ----------
    config : Path
        Path to the configuration YAML file.
    verbose : bool
        Enable verbose (DEBUG) logging. Defaults to False.
    """
    _setup_logging(level=logging.DEBUG if verbose else logging.INFO)
    from lsatfetch.cli.get import get as get_cmd

    get_cmd(config)


@app.command
def status(
    config: Path,
) -> None:
    """
    Show the status of a Landsat dataset.

    Parameters
    ----------
    config : Path
        Path to the configuration YAML file.
    """
    _setup_logging()
    from lsatfetch.cli.status import status as status_cmd

    status_cmd(config)


if __name__ == "__main__":
    app()
