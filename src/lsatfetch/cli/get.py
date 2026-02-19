import logging
from datetime import datetime
from pathlib import Path

import geopandas as gpd
from shapely import box
from shapely.geometry import MultiPolygon, Polygon

from lsatfetch.cli.config import load
from lsatfetch.core import get as download_landsat
from lsatfetch.tile import tiles_intersecting
from lsatfetch.utils.rs import load_country_filter_polygon

log = logging.getLogger(__name__)


def get(
    config_path: Path,
    download: bool = True,
    postprocess: bool = True,
    quality: int = 50,
    n_workers_dl: int = 4,
    n_workers_pp: int = 4,
) -> None:
    log.debug("Loading configuration")
    cfg = load(config_path)
    log.info(f"Configuration loaded from {config_path}")
    log.info(f"Output directory: {cfg.output_dir}")
    log.debug(f"AOI type: {cfg.aoi.type}")
    log.debug(f"Download workers: {n_workers_dl}")
    log.debug(f"Preprocess workers: {n_workers_pp}")

    log.info("Identifying tiles...")
    if cfg.aoi.type == "bbox":
        left = cfg.aoi.left
        bottom = cfg.aoi.bottom
        right = cfg.aoi.right
        top = cfg.aoi.top
        assert left is not None
        assert bottom is not None
        assert right is not None
        assert top is not None
        aoi_geom = box(left, bottom, right, top)
    elif cfg.aoi.type == "vector":
        assert cfg.aoi.vector is not None
        log.info(f"Reading AOI from {cfg.aoi.vector}")
        gdf = gpd.read_file(cfg.aoi.vector)
        if gdf.crs is not None and gdf.crs != "EPSG:4326":
            log.info(f"Reprojecting AOI from {gdf.crs} to EPSG:4326")
            gdf = gdf.to_crs("EPSG:4326")
        aoi_geom = gdf.unary_union
        if not isinstance(aoi_geom, Polygon | MultiPolygon):
            msg = f"AOI must be a Polygon or MultiPolygon, got {type(aoi_geom)}"
            raise ValueError(msg)
    elif cfg.aoi.type == "country":
        assert cfg.aoi.country is not None
        log.info(f"Loading AOI for country: {cfg.aoi.country}")
        aoi_geom = load_country_filter_polygon(cfg.aoi.country)
        if aoi_geom is None:
            log.warning("No AOI geometry found for country. Skipping tile identification.")
            return
    else:
        log.warning("No AOI geometry found. Skipping tile identification.")
        return

    tile_ids = tiles_intersecting(aoi_geom)
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
        aoi=aoi_geom,
        start_date=start_date,
        end_date=end_date,
        output_dir=cfg.output_dir,
        n_workers_dl=n_workers_dl,
        n_workers_pp=n_workers_pp,
        download=download,
        postprocess=postprocess,
        quality=quality,
    )
