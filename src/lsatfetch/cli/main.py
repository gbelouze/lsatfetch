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


@app.command
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


@app.command
def get(
    config: Path,
    verbose: bool = False,
    download: bool = True,
    postprocess: bool = False,
    quality: int = 50,
    n_workers_dl: int = 4,
    n_workers_pp: int = 4,
) -> None:
    """
    Create a Landsat dataset based on the provided configuration.

    Parameters
    ----------
    config : Path
        Path to the configuration YAML file.
    verbose : bool
        Enable verbose (DEBUG) logging. Defaults to False.
    download : bool
        Enable downloading of tiles. If False, only already downloaded tiles are processed.
        Defaults to True.
    postprocess : bool
        Enable post-processing (compression to JP2). Defaults to False.
    quality : int
        JPEG2000 compression quality (1-100). Defaults to 50.
    n_workers_dl : int
        Number of parallel download jobs. Defaults to 4.
    n_workers_pp : int
        Number of parallel preprocessing jobs. Defaults to 4.
    """
    _setup_logging(level=logging.DEBUG if verbose else logging.INFO)
    from lsatfetch.cli.get import get as get_cmd

    get_cmd(config, download, postprocess, quality, n_workers_dl, n_workers_pp)


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
    from lsatfetch.cli.status import status as status_cmd

    status_cmd(config)


if __name__ == "__main__":
    app()
