import logging
from pathlib import Path
from typing import Annotated

import cyclopts

from landsat.cli.config import load
from landsat.core import (
    estimate_download_size,
    estimate_download_time,
    identify_tiles,
)

log = logging.getLogger(__name__)
app = cyclopts.App(name="landsat")


@app.command
def get(config: Annotated[Path, cyclopts.Parameter("c")]) -> None:
    """
    Create a Landsat dataset based on the provided configuration.

    Parameters
    ----------
    config : Path
        Path to the configuration YAML file.
    """
    log.info("Loading configuration...")
    cfg = load(config)
    log.info(f"Configuration loaded from {config}")
    log.info(f"  Output directory: {cfg.output_dir}")
    log.info(f"  AOI type: {cfg.aoi.type}")
    log.info(f"  Parallel jobs: {cfg.parallel_jobs}")

    log.info("Identifying tiles...")
    aoi_bbox = None
    if cfg.aoi.type == "bbox" and cfg.aoi.left is not None:
        aoi_bbox = (cfg.aoi.left, cfg.aoi.bottom, cfg.aoi.right, cfg.aoi.top)
    if aoi_bbox is None:
        log.warning("No AOI bbox found. Skipping tile identification.")
        return

    tile_ids = identify_tiles(aoi_bbox)
    log.info(f"Found {len(tile_ids)} tiles")

    if not tile_ids:
        log.warning("No tiles found for the specified AOI.")
        return

    log.info("Estimating download...")
    size_bytes = estimate_download_size(tile_ids)
    size_mb = size_bytes / (1024 * 1024)
    time_seconds = estimate_download_time(tile_ids, cfg.parallel_jobs)
    time_minutes = time_seconds / 60

    log.info(f"  Estimated size: {size_mb:.1f} MB")
    log.info(f"  Estimated time: {time_minutes:.1f} minutes")

    log.warning("Download not yet implemented")
    log.info("This is a placeholder for the download functionality.")
