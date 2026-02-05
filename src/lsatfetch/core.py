import logging
import multiprocessing as mp
import shutil
import tempfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import boto3
import botocore
import numpy as np
import rasterio as rio
from botocore.config import Config
from botocore.exceptions import ClientError
from rich.progress import Progress
from shapely.geometry import Polygon

from lsatfetch.const import GLAD_LANDSAT_BUCKET
from lsatfetch.tile import (
    Period,
    Tile,
    tile_s3_key,
    tiles_intersecting,
    time_indices_for_range,
)
from lsatfetch.utils.log_multiprocessing import (
    LogQueue,
    LogQueueConsumer,
    init_log_queue_for_children,
)
from lsatfetch.utils.progress import default_bar, temporary_task
from lsatfetch.utils.stats import (
    ImageStatistics,
    Statistics,
    compute_pixel_statistics,
)

log = logging.getLogger(__name__)


class DownloadError(Exception):
    pass


def _get_s3_client() -> Any:
    """Create S3 client with anonymous access for public bucket."""
    return boto3.client(
        "s3",
        config=Config(signature_version=botocore.UNSIGNED),
    )


def download_tile(
    tile: Tile,
    period: Period,
    output_dir: Path,
    progress: Progress | None = None,
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
    progress : Progress | None
        Rich progress tracker. Defaults to None.

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

    if output_path.exists():
        log.debug(f"Tile already exists: {s3_key}. Skipping.")

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


def compress_landsat_image(input_path: Path, output_path: Path, quality: int = 50) -> Path:
    """
    Compress a TIFF image to JPEG2000 format with cloud/shadow masking.

    Reads band 8 (QA) and masks pixels that are not in KEEP_VALUES.
    Masked pixels are set to nodata (0) in the output JP2.

    Parameters
    ----------
    input_path : Path
        Path to the input TIFF image.
    output_path : Path
        Path to save the compressed JPEG2000 image.
    quality : int
        JPEG2000 compression quality (1-100). Defaults to 50.

    Returns
    -------
    output_path : Path
        Path to the created jp2 file.
    """
    from lsatfetch.utils.stats import KEEP_VALUES

    if output_path.exists():
        log.info(f"{output_path} already exists. Skipping")
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rio.open(input_path) as src:
        log.debug(f"Reading {input_path}")
        bands_data = src.read(indexes=[1, 2, 3, 4, 5, 6, 7], out_dtype="float32")
        band8 = src.read(8)
        profile = src.profile

        valid_mask = np.isin(band8, list(KEEP_VALUES))
        masked_data = bands_data.copy()
        masked_data[:, ~valid_mask] = 0

        nbands = bands_data.shape[0]

        arr = np.clip(masked_data, 0, 2**16 - 1)
        arr = (arr / 2**8) * ((255 * 2**8) / (2**16 - 1))
        arr = arr.astype("uint8")

        profile.update(
            driver="JP2OpenJPEG",
            dtype="uint8",
            count=nbands,
            compress="JPEG2000",
            quality=quality,
            tiled=True,
            blockxsize=256,
            blockysize=256,
        )

        with tempfile.NamedTemporaryFile(suffix=".jp2", delete=False) as tmp_jp2:
            log.debug(f"Writing compressed raster to {tmp_jp2.name}")
            tmp_jp2_path = Path(tmp_jp2.name)
        with rio.open(tmp_jp2_path, "w", **profile) as dst:
            dst.write(arr)

    shutil.move(str(tmp_jp2_path), str(output_path))
    log.info(f"Saved compressed file to {output_path}")

    input_path.unlink()
    log.info(f"Deleted {input_path}")
    return output_path


def process_file(
    input_path: Path,
    base_dir: Path,
    quality: int = 50,
) -> ImageStatistics | None:
    """
    Process a single Landsat TIFF file: filter cloudy pixels and compress to JP2.

    Parameters
    ----------
    input_path : Path
        Path to the input TIFF file.
    base_dir : Path
        Path to the base directory.
    quality : int
        JPEG2000 compression quality. Defaults to 50.
    """
    file_id = input_path.stem

    statistics = Statistics(base_dir / "meta.parquet")

    stat = statistics.get(file_id)
    if stat is None:
        pixel_stat = compute_pixel_statistics(input_path)
    else:
        pixel_stat = {k: stat[k] for k in ["discarded", "n_valid_initial", "n_valid_final"]}

    if pixel_stat["discarded"]:
        log.info(f"Discarding {file_id}: >=80% nodata ({pixel_stat['n_valid_final']} valid pixels)")
        return None

    output_path = base_dir / "landsat" / input_path.with_suffix(".jp2").name
    size_bytes = input_path.stat().st_size
    compress_landsat_image(input_path, output_path, quality)
    if input_path.exists():  # compression was skipped
        return None

    stat = ImageStatistics(
        file_id=file_id,
        n_valid_initial=pixel_stat["n_valid_initial"],
        n_valid_final=pixel_stat["n_valid_final"],
        discarded=pixel_stat["discarded"],
        processed_at=stat["processed_at"] if stat is not None else datetime.now(),
        size_bytes=size_bytes,
        compressed_size_bytes=output_path.stat().st_size,
    )
    statistics[file_id] = stat

    return stat


def get(
    aoi: Polygon,
    start_date: date,
    end_date: date,
    output_dir: Path,
    parallel_jobs: int = 4,
    postprocess: bool = False,
    quality: int = 50,
) -> tuple[int, int]:
    """
    Download Landsat ARD tiles for the given AOI and time range.

    Downloads all tiles that intersect with the AOI for all time periods
    that fall within the given date range. Skips tiles that don't exist
    on S3 (e.g., ocean tiles, cloudy periods).

    Parameters
    ----------
    aoi : Polygon
        Area of interest geometry.
    start_date : date
        Start date of the time period of interest.
    end_date : date
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

    with mp.Manager() as manager:
        log_queue = cast(LogQueue, manager.Queue())
        with (
            ProcessPoolExecutor(
                max_workers=parallel_jobs,
                initializer=init_log_queue_for_children,
                initargs=(log_queue,),
            ) as postprocess_executor,
            LogQueueConsumer(log_queue),
            default_bar() as progress,
        ):
            postprocess_task = (
                progress.add_task(
                    "[cyan]Processing downloaded tiles...[/]",
                    total=1,
                )
                if postprocess
                else None
            )

            with (
                ThreadPoolExecutor(max_workers=parallel_jobs) as download_executor,
                temporary_task(
                    progress,
                    "[cyan]Downloading Landsat ARD tiles...[/]",
                    total=len(tasks),
                ) as download_task,
            ):
                download_futures = {
                    download_executor.submit(download_tile, tile, period, output_dir, progress): (
                        tile,
                        period,
                    )
                    for tile, period in tasks
                }
                postprocess_futures = []

                n_failures = 0
                n_downloaded = 0
                n_filtered_out = 0
                first_failure = None
                try:
                    for future in as_completed(download_futures):
                        tile, period = download_futures[future]
                        try:
                            downloaded_path = future.result()
                            if downloaded_path is not None:
                                n_downloaded += 1
                                if postprocess:
                                    postprocess_future = postprocess_executor.submit(
                                        process_file,
                                        downloaded_path,
                                        downloaded_path.with_suffix(".jp2"),
                                        quality,
                                    )
                                    postprocess_futures.append(postprocess_future)
                                    progress.update(
                                        postprocess_task, total=postprocess_task.total + 1
                                    )
                            else:
                                n_filtered_out += 1
                        except Exception as e:
                            log.error(
                                f"Error downloading {tile.tile_id} for period {period.n}: {e}"
                            )
                            n_failures += 1
                            first_failure = first_failure if first_failure is not None else e
                        finally:
                            progress.advance(download_task)
                except KeyboardInterrupt:
                    download_executor.shutdown(wait=False, cancel_futures=True)
                    log.error(
                        "Keyboard interrupt. "
                        "Please wait while current download finish (up to a few minutes)."
                    )
                    raise
                if n_failures > 0:
                    raise DownloadError(
                        f"Failed to download {n_failures} tiles."
                    ) from first_failure

            log.info(
                f"[green]Finished[/]: downloaded {n_downloaded} tiles, skipped {n_filtered_out}"
            )

            n_processed = 0
            n_filtered_out = 0
            if postprocess:
                try:
                    for future in as_completed(postprocess_futures):
                        result = future.result()
                        if result is not None:
                            n_processed += 1
                        else:
                            n_filtered_out += 1
                        progress.advance(postprocess_task)
                except KeyboardInterrupt:
                    download_executor.shutdown(wait=False, cancel_futures=True)
                    log.error(
                        "Keyboard interrupt. "
                        "Please wait while current processing finish (up to a few minutes)."
                    )
                    raise
                log.info(
                    f"Processed {n_processed} tiles. Filtered out {n_filtered_out} tiles "
                    f"({100 * n_filtered_out / (n_processed + n_filtered_out):.1f}%)."
                )

    return n_processed if postprocess else n_downloaded
