import logging
from datetime import datetime
from pathlib import Path

from shapely import box

from lsatfetch.cli.config import load
from lsatfetch.core import get as download_landsat
from lsatfetch.tile import tiles_intersecting

log = logging.getLogger(__name__)


def get(config_path: Path, postprocess: bool = False, quality: int = 50) -> None:
    log.debug("Loading configuration")
    cfg = load(config_path)
    log.info(f"Configuration loaded from {config_path}")
    log.info(f"Output directory: {cfg.output_dir}")
    log.debug(f"AOI type: {cfg.aoi.type}")
    log.debug(f"Parallel jobs: {cfg.parallel_jobs}")

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

    if cfg.time_range.start is None or cfg.time_range.end is None:
        log.error("Time range not specified in configuration.")
        return

    start_date = datetime.strptime(cfg.time_range.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(cfg.time_range.end, "%Y-%m-%d").date()

    download_landsat(
        aoi=aoi_box,
        start_date=start_date,
        end_date=end_date,
        output_dir=cfg.output_dir,
        parallel_jobs=cfg.parallel_jobs,
        postprocess=postprocess,
        quality=quality,
    )
