import logging
from pathlib import Path
from typing import Annotated

import cyclopts
import yaml

app = cyclopts.App(name="init")

log = logging.getLogger(__name__)


@app.command
def init(
    output: Annotated[Path, cyclopts.Parameter("o")] | None = None,
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
    default_path = Path("config.yaml")
    output_path = output or default_path

    if output_path.exists() and not force:
        log.error(f"{output_path} already exists. Use --force to overwrite.")
        return

    config_dict = {
        "aoi": {
            "type": "bbox",
            "left": -180,
            "bottom": -90,
            "right": 180,
            "top": 90,
            # "vector": "path/to/aoi.geojson",
        },
        "time_range": {
            "start": "2020-01-01",
            "end": "2024-01-01",
        },
        "output_dir": "data/landsat",
        # "cloud_filter": {
        #     "max_cloud_percent": 20,
        # },
        "parallel_jobs": 4,
    }

    with output_path.open("w") as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)

    log.info("Configuration template created!")
    log.info(f"  Path: {output_path.absolute()}")
    log.info("  Edit the file to customize your dataset configuration.")
