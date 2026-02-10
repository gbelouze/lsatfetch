import asyncio
import logging
import multiprocessing as mp
import shutil
import tempfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
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
from shapely.geometry import MultiPolygon, Polygon

from lsatfetch.const import (
    GLAD_LANDSAT_BUCKET,
    KEEP_VALUES,
    MAX_PIXEL,
    MIN_PIXEL,
)
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
from lsatfetch.utils.meta import (
    DownloadResult,
    Meta,
    ProcessResult,
    compute_pixel_statistics,
)
from lsatfetch.utils.multiprocessing import SequentialExecutor
from lsatfetch.utils.progress import default_bar, lsat_debug, temporary_task

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
) -> DownloadResult | None:
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
    DownloadResult | None
        Results of the download, or None if download failed (but not 404).
    """
    s3_key = tile_s3_key(tile, period)
    output_dir = Path(output_dir).expanduser().absolute()
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{tile.lat_name}_{tile.lon_name}" / f"{period.n}.tif"
    output_path.parent.mkdir(exist_ok=True)

    tile_id = f"{tile.lon_name}_{tile.lat_name}:{period.n}"

    s3 = _get_s3_client()

    try:
        response = s3.head_object(Bucket=GLAD_LANDSAT_BUCKET, Key=s3_key)
        file_size = response["ContentLength"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            log.debug(f"Tile not found on S3: {s3_key}. Skipping.")
            return DownloadResult(
                id=tile_id,
                path=str(output_path),
                downloaded_at=datetime.now(),
                size_bytes=None,
                is_missing=True,
            )
        log.warning(f"Error checking S3 object {GLAD_LANDSAT_BUCKET}/{s3_key}: {e}")
        return None

    try:
        with ExitStack() as stack:
            task = None
            if progress is not None:
                task = stack.enter_context(
                    temporary_task(
                        progress,
                        f"[cyan]{tile.tile_id}::{Path(s3_key).stem}",
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
            return DownloadResult(
                id=tile_id,
                path=str(output_path),
                downloaded_at=datetime.now(),
                size_bytes=file_size,
                is_missing=False,
            )
    except Exception as e:
        log.error(f"Failed to download {s3_key}: {e}")
        return None


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

        arr = np.clip(masked_data, MIN_PIXEL, MAX_PIXEL)
        arr = 255 * (arr - MIN_PIXEL) / (MAX_PIXEL - MIN_PIXEL)
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
        del profile["tiled"]
        del profile["interleave"]
        del profile["compress"]

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
    tile_id: str,
    quality: int = 50,
) -> ProcessResult:
    """
    Process a single Landsat TIFF file: filter cloudy pixels and compress to JP2.

    Parameters
    ----------
    input_path : Path
        Path to the input TIFF file.
    tile_id : str
        Unique identifier for the tile:period.
    quality : int
        JPEG2000 compression quality. Defaults to 50.
    """
    pixel_stat = compute_pixel_statistics(input_path)

    if pixel_stat["discarded"]:
        log.info(f"Discarding {tile_id}: too many invalid pixels.")
        input_path.unlink()
        return ProcessResult(
            id=tile_id,
            path=str(input_path.with_suffix(".jp2")),
            processed_at=datetime.now(),
            n_valid_initial=pixel_stat["n_valid_initial"],
            n_valid_final=pixel_stat["n_valid_final"],
            discarded=True,
            compressed_size_bytes=None,
        )

    output_path = input_path.with_suffix(".jp2")
    compress_landsat_image(input_path, output_path, quality)

    return ProcessResult(
        id=tile_id,
        path=str(output_path),
        processed_at=datetime.now(),
        n_valid_initial=pixel_stat["n_valid_initial"],
        n_valid_final=pixel_stat["n_valid_final"],
        discarded=False,
        compressed_size_bytes=output_path.stat().st_size,
    )


def get(
    aoi: Polygon | MultiPolygon,
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
    aoi : Polygon | MultiPolygon
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
        Tuple of (n_downloaded, n_processed) indicating how many tiles
        were successfully downloaded and how many were processed.
    """
    tiles = tiles_intersecting(aoi)
    periods = time_indices_for_range(start_date, end_date)
    tasks = [(tile, period) for tile in tiles for period in periods]
    log.info(f"Identified {len(tiles)} tiles and {len(periods)} periods.")

    output_dir = Path(output_dir).expanduser().absolute()
    output_dir.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_get_async(tasks, output_dir, parallel_jobs, postprocess, quality))


async def _get_async(
    tasks: list[tuple[Tile, Period]],
    output_dir: Path,
    parallel_jobs: int,
    postprocess: bool,
    quality: int,
) -> tuple[int, int]:
    loop = asyncio.get_running_loop()

    with mp.Manager() as manager:
        log_queue = cast(LogQueue, manager.Queue())
        pp_executor = ProcessPoolExecutor if not lsat_debug() else SequentialExecutor

        with (
            pp_executor(
                max_workers=parallel_jobs,
                initializer=init_log_queue_for_children,
                initargs=(log_queue,),
            ) as pp_pool,
            ThreadPoolExecutor(max_workers=parallel_jobs) as dl_pool,
            LogQueueConsumer(log_queue),
            default_bar() as progress,
            Meta(output_dir / "meta.duckdb") as meta,
        ):
            pp_bar = (
                progress.add_task(
                    "[cyan]Processing downloaded tiles...[/]",
                    total=1,
                )
                if postprocess
                else None
            )
            dl_bar = progress.add_task(
                "[cyan]Downloading Landsat ARD tiles...[/]", total=len(tasks)
            )

            n_pp_submitted = 0
            pp_futures: dict[asyncio.Future[ProcessResult], str] = {}
            dl_futures: dict[asyncio.Future[DownloadResult | None], tuple[Tile, Period, str]] = {}

            n_failures = 0
            n_downloaded = 0
            n_processed = 0
            n_dl_skipped = 0
            n_pp_skipped = 0
            first_failure = None

            # Filter tasks before submitting
            for tile, period in tasks:
                tile_id = f"{tile.lon_name}_{tile.lat_name}:{period.n}"
                tif_path = output_dir / f"{tile.lat_name}_{tile.lon_name}" / f"{period.n}.tif"
                jp2_path = tif_path.with_suffix(".jp2")

                # Check if we should skip download
                skip_dl = False
                if tile_id in meta.dl and meta.dl[tile_id]["is_missing"]:
                    log.debug(f"Skipping {tile_id}: established as missing on S3.")
                    skip_dl = True
                elif tile_id in meta.pp and meta.pp[tile_id]["discarded"]:
                    log.debug(f"Skipping {tile_id}: established as filtered out.")
                    skip_dl = True
                elif jp2_path.exists():
                    log.debug(f"Skipping {tile_id}: JP2 already exists.")
                    skip_dl = True
                elif tif_path.exists():
                    log.debug(f"Skipping {tile_id}: TIFF already exists.")
                    skip_dl = True

                if skip_dl:
                    n_dl_skipped += 1
                    progress.advance(dl_bar)
                    # If TIFF exists but not processed, we might still want to process it
                    if postprocess and tif_path.exists() and not jp2_path.exists():
                        if tile_id in meta.pp and meta.pp[tile_id]["discarded"]:
                            log.debug(f"{tif_path} exists but is marked as filtered out. Removing.")
                            tif_path.unlink()
                        else:
                            pp_future = loop.run_in_executor(
                                pp_pool,
                                process_file,
                                tif_path,
                                tile_id,
                                quality,
                            )
                            pp_futures[pp_future] = tile_id
                            n_pp_submitted += 1
                            if pp_bar is not None:
                                progress.update(pp_bar, total=n_pp_submitted)
                    continue

                # Submit download task
                future = loop.run_in_executor(
                    dl_pool, download_tile, tile, period, output_dir, progress
                )
                dl_futures[future] = (tile, period, tile_id)

            try:
                while dl_futures or pp_futures:
                    all_active = list(dl_futures.keys()) + list(pp_futures.keys())
                    done, _ = await asyncio.wait(all_active, return_when=asyncio.FIRST_COMPLETED)

                    for task in done:
                        if task in dl_futures:
                            task = cast(asyncio.Future[DownloadResult | None], task)
                            tile, period, tile_id = dl_futures.pop(task)
                            try:
                                dl_res: DownloadResult | None = task.result()
                                if dl_res is not None:
                                    meta.dl[tile_id] = dl_res
                                    if dl_res["is_missing"]:
                                        n_dl_skipped += 1
                                    else:
                                        n_downloaded += 1
                                        if postprocess:
                                            tif_path = Path(dl_res["path"])
                                            pp_future = loop.run_in_executor(
                                                pp_pool,
                                                process_file,
                                                tif_path,
                                                tile_id,
                                                quality,
                                            )
                                            pp_futures[pp_future] = tile_id
                                            n_pp_submitted += 1
                                            if pp_bar is not None:
                                                progress.update(pp_bar, total=n_pp_submitted)
                                else:
                                    # Unexpected None (error logged in worker)
                                    n_failures += 1
                            except Exception as e:
                                log.error(f"Error downloading {tile_id}: {e}")
                                n_failures += 1
                                first_failure = first_failure if first_failure is not None else e
                            finally:
                                progress.advance(dl_bar)

                        elif task in pp_futures:
                            task = cast(asyncio.Future[ProcessResult], task)
                            tile_id = pp_futures.pop(task)
                            try:
                                pp_res: ProcessResult = task.result()
                                meta.pp[tile_id] = pp_res
                                if pp_res["discarded"]:
                                    n_pp_skipped += 1
                                else:
                                    n_processed += 1
                            except Exception as e:
                                log.error(f"Error processing {tile_id}: {e}")
                                n_failures += 1
                                first_failure = first_failure if first_failure is not None else e
                            finally:
                                if pp_bar is not None:
                                    progress.advance(pp_bar)
            except (KeyboardInterrupt, asyncio.CancelledError):
                log.warning("[yellow]Interrupt received. Please wait for cleanup...[/]")
                for task in dl_futures:
                    task.cancel()
                dl_pool.shutdown(wait=False, cancel_futures=True)
                pp_pool.shutdown(wait=False, cancel_futures=True)
                raise

            if n_failures > 0:
                raise DownloadError(
                    f"{n_failures} failure(s) during download/processing."
                ) from first_failure

            log.info(f"[green]Finished[/]: downloaded {n_downloaded} tiles, skipped {n_dl_skipped}")

            if postprocess:
                log.info(f"Processed {n_processed} tiles. Discarded {n_pp_skipped} tiles.")

    return n_downloaded, n_processed
