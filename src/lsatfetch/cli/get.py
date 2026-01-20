import logging
from pathlib import Path

from shapely import box

from lsatfetch.cli.config import load
from lsatfetch.core import (
    estimate_download_size,
    estimate_download_time,
)
from lsatfetch.tile import tiles_intersecting

log = logging.getLogger(__name__)


def get(config: Path) -> None:
    log.info("Loading configuration...")
    cfg = load(config)
    log.info(f"Configuration loaded from {config}")
    log.info(f"  Output directory: {cfg.output_dir}")
    log.info(f"  AOI type: {cfg.aoi.type}")
    log.info(f"  Parallel jobs: {cfg.parallel_jobs}")

    log.info("Identifying tiles...")
    if cfg.aoi.type == "bbox" and cfg.aoi.left is not None:
        aoi_box = box(
            cfg.aoi.left,
            cfg.aoi.bottom,
            cfg.aoi.right,
            cfg.aoi.top,
        )
    else:
        log.warning("No AOI geometry found. Skipping tile identification.")
        return

    tile_ids = tiles_intersecting(aoi_box)
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
