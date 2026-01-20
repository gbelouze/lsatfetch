import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


def init(
    output: Path | None = None,
    force: bool = False,
) -> None:
    default_path = Path("config.yaml")
    output_path = output if output is not None else default_path
    output_path = output_path.expanduser().resolve().absolute()

    if output_path.exists() and not force:
        log.error(f"{output_path} already exists. Use --force to overwrite.")
        return

    if output_path.suffix == "":
        output_path.mkdir()
        output_path = output_path / "config.yaml"

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
        "output_dir": str(output_path),
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
