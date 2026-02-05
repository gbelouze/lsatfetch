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


@app.command  # type: ignore[misc]
def compress(
    input_dir: Path,
    quality: int = 50,
    watch: bool = False,
    report: bool = False,
    verbose: bool = False,
) -> None:
    """
    Compress Landsat TIFF images to JPEG2000 format with cloud filtering.

    Parameters
    ----------
    input_dir : Path
        Directory containing .tif files to process.
    quality : int
        JPEG2000 compression quality (1-100). Defaults to 50.
    watch : bool
        Watch for new .tif files and process them automatically.
        Stops after 15 minutes of inactivity. Defaults to False.
    report : bool
        Print a statistics report after processing. Defaults to False.
    verbose : bool
        Enable verbose (DEBUG) logging. Defaults to False.
    """
    _setup_logging(level=logging.DEBUG if verbose else logging.INFO)
    from lsatfetch.cli.compress import compress as compress_cmd

    compress_cmd(input_dir, quality, watch, report, verbose)


if __name__ == "__main__":
    app()
