"""Main entry point for lsatfetch CLI."""

from pathlib import Path

import cyclopts

app = cyclopts.App(
    name="lsatfetch",
    help="CLI for creating Landsat image datasets",
)


@app.command
def init(
    output: Path | None = None,
    force: bool = False,
) -> None:
    """Initialize a configuration template for Landsat dataset creation."""
    from lsatfetch.cli.init import init as init_cmd

    init_cmd(output, force)


@app.command
def get(
    config: Path,
) -> None:
    """Create a Landsat dataset based on the provided configuration."""
    from lsatfetch.cli.get import get as get_cmd

    get_cmd(config)


@app.command
def status(
    config: Path,
) -> None:
    """Show the status of a Landsat dataset."""
    from lsatfetch.cli.status import status as status_cmd

    status_cmd(config)


def main(
    verbose: bool = False,
    quiet: bool = False,
    logfile: Path | None = None,
    debug: bool = False,
) -> None:
    """Main entry point for the lsatfetch CLI."""
    from lsatfetch.utils.log import setup

    level = 0
    if verbose:
        level = logging.DEBUG
    if quiet:
        level = logging.ERROR
    if debug:
        level = logging.DEBUG
    setup(level=level, logfile=logfile)

    app()


if __name__ == "__main__":
    import logging

    main()
