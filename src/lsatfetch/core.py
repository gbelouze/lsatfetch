import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from typing import Any

import boto3
import botocore
from botocore.config import Config
from botocore.exceptions import ClientError
from rich.progress import Progress
from shapely.geometry import Polygon

from lsatfetch.tile import (
    Period,
    Tile,
    tile_s3_key,
    tiles_intersecting,
    time_indices_for_range,
)
from lsatfetch.utils.progress import default_bar, temporary_task

log = logging.getLogger(__name__)

GLAD_LANDSAT_BUCKET = "glad.landsat.ard"


class DownloadError(Exception):
    pass


def _get_s3_client() -> Any:
    """Create S3 client with anonymous access for public bucket."""
    return boto3.client(
        "s3",
        config=Config(signature_version=botocore.UNSIGNED),
    )


def download_tile(
    tile: Tile, period: Period, output_dir: Path, progress: Progress | None = None
) -> Path | None:
    """
    Download a single Landsat tile for a specific period.

    Downloads the tile if it exists on S3. Uses atomic writes by downloading
    to a temporary file first, then renaming to the final path.

    Parameters
    ----------
    tile : Tile
        Tile to download.
    period : Period
        Time period to download.
    output_dir : Path
        Directory to save the downloaded file.

    Returns
    -------
    Path | None
        Path to the downloaded file, or None if not found or download failed.
    """
    s3_key = tile_s3_key(tile, period)
    output_dir = Path(output_dir).expanduser().absolute()
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{tile.lat_name}_{tile.lon_name}" / f"{period.n}.tif"
    output_path.parent.mkdir(exist_ok=True)

    s3 = _get_s3_client()

    try:
        response = s3.head_object(Bucket=GLAD_LANDSAT_BUCKET, Key=s3_key)
        file_size = response["ContentLength"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            log.debug(f"Tile not found on S3: {s3_key}. Skipping.")
            return None
        log.warning(f"Error checking S3 object {GLAD_LANDSAT_BUCKET}/{s3_key}: {e}")
        return None

    with ExitStack() as stack:
        task = None
        if progress is not None:
            task = stack.enter_context(
                temporary_task(
                    progress,
                    f"[cyan]{tile.tile_id}",
                    total=file_size // 1_000_000,
                )
            )

        def callback(bytes_transferred: int) -> None:
            assert progress is not None
            assert task is not None
            progress.update(task, advance=bytes_transferred / 1_000_000)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / f"{tile.tile_id}_{period.n}.tif"
            s3.download_file(
                Bucket=GLAD_LANDSAT_BUCKET,
                Key=s3_key,
                Filename=str(tmp_path),
                Callback=callback if progress is not None else None,
            )
            tmp_path.rename(output_path)

        log.debug(f"Downloaded tile to {output_path}")
    return output_path


def compress_image(input_path: Path, output_path: Path) -> None:
    """
    Compress an image to JPEG2000 format.

    Parameters
    ----------
    input_path : Path
        Path to the input image.
    output_path : Path
        Path to save the compressed image.
    """


def filter_cloudy(image_path: Path, max_cloud_percent: float) -> bool:
    """
    Check if an image is mostly cloudy.

    Parameters
    ----------
    image_path : Path
        Path to the image to check.
    max_cloud_percent : float
        Maximum allowed cloud percentage.

    Returns
    -------
    bool
        True if the image should be filtered out (too cloudy).
    """
    return False


def estimate_download_size(tiles: list[Tile]) -> int:
    """
    Estimate total download size for a list of tiles.

    Parameters
    ----------
    tiles : list[Tile]
        List of tiles to download.

    Returns
    -------
    int
        Estimated size in bytes.
    """
    return 0


def estimate_download_time(tiles: list[Tile], parallel_jobs: int) -> float:
    """
    Estimate download time for a list of tiles.

    Parameters
    ----------
    tiles : list[Tile]
        List of tiles to download.
    parallel_jobs : int
        Number of parallel download jobs.

    Returns
    -------
    float
        Estimated time in seconds.
    """
    return 0.0


def get(
    aoi: Polygon,
    start_date: date,
    end_date: date,
    output_dir: Path,
    parallel_jobs: int = 4,
) -> tuple[int, int]:
    """
    Download Landsat ARD tiles for the given AOI and time range.

    Downloads all tiles that intersect with the AOI for all time periods
    that fall within the given date range. Skips tiles that don't exist
    on S3 (e.g., ocean tiles, cloudy periods).

    Parameters
    ----------
    aoi : shapely.geometry.Polygon
        Area of interest geometry.
    start_date : datetime.date
        Start date of the time period of interest.
    end_date : datetime.date
        End date of the time period of interest.
    output_dir : Path
        Directory to save downloaded files.
    parallel_jobs : int
        Number of parallel download jobs. Defaults to 4.

    Returns
    -------
    tuple[int, int]
        Tuple of (n_downloaded, n_skipped) indicating how many tiles
        were successfully downloaded and how many were skipped.
    """
    tiles = tiles_intersecting(aoi)
    periods = time_indices_for_range(start_date, end_date)

    tasks = [(tile, period) for tile in tiles for period in periods]
    log.info(f"Identified {len(tiles)} tiles and {len(periods)} periods.")

    output_dir = Path(output_dir).expanduser().absolute()
    output_dir.mkdir(parents=True, exist_ok=True)

    n_downloaded = 0
    n_skipped = 0

    with default_bar() as progress:
        overall_task = progress.add_task(
            "[cyan]Downloading Landsat ARD tiles...",
            total=len(tasks),
        )

        with ThreadPoolExecutor(max_workers=parallel_jobs) as executor:
            futures = {
                executor.submit(download_tile, tile, period, output_dir, progress): (tile, period)
                for tile, period in tasks
            }
            n_failures = 0
            first_failure = None
            try:
                for future in as_completed(futures):
                    tile, period = futures[future]
                    try:
                        result = future.result()
                        if result is not None:
                            n_downloaded += 1
                        else:
                            n_skipped += 1
                    except Exception as e:
                        log.error(f"Error downloading {tile.tile_id} for period {period.n}: {e}")
                        n_failures += 1
                        first_failure = first_failure if first_failure is not None else e
                    finally:
                        progress.advance(overall_task)
            except KeyboardInterrupt:
                executor.shutdown(wait=False, cancel_futures=True)
                log.error(
                    "Keyboard interrupt. "
                    "Please wait while current download finish (up to a few minutes)."
                )
                raise
            if n_failures > 0:
                raise DownloadError(f"Failed to download {n_failures} tiles.") from first_failure

    log.info(f"[green]Finished[/]: downloaded {n_downloaded} tiles, skipped {n_skipped}")
    return n_downloaded, n_skipped
