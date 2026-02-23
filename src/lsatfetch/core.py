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
    BAND_7_RANGE,
    BAND_123_RANGE,
    BAND_456_RANGE,
    GLAD_LANDSAT_BUCKET,
    KEEP_VALUES,
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
from lsatfetch.utils.stats import SessionStats

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
    tile_id = f"{tile.lon_name}_{tile.lat_name}:{period.n}"
    log.debug(f"Downloading tile {tile_id}")

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
            return DownloadResult(
                id=tile_id,
                path=str(output_path),
                downloaded_at=datetime.now(),
                size_bytes=None,
                is_missing=True,
                file_exists=False,
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
                shutil.move(tmp_path, output_path)

            log.debug(f"Downloaded tile to {output_path}")
            return DownloadResult(
                id=tile_id,
                path=str(output_path),
                downloaded_at=datetime.now(),
                size_bytes=file_size,
                is_missing=False,
                file_exists=True,
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

        nbands = bands_data.shape[0]
        valid_mask = np.isin(band8, list(KEEP_VALUES))
        bands_data[:, ~valid_mask] = 0

        # Normalize band groups independently
        # Band 1, 2, 3: 0 to 8000
        low, high = BAND_123_RANGE
        bands_data[0:3] = np.clip(bands_data[0:3], low, high)
        bands_data[0:3] = 255 * (bands_data[0:3] - low) / (high - low)

        # Band 4, 5, 6: 0 to 20000
        low, high = BAND_456_RANGE
        bands_data[3:6] = np.clip(bands_data[3:6], low, high)
        bands_data[3:6] = 255 * (bands_data[3:6] - low) / (high - low)

        # Band 7: 28000 to 30000
        low, high = BAND_7_RANGE
        bands_data[6] = np.clip(bands_data[6], low, high)
        bands_data[6] = 255 * (bands_data[6] - low) / (high - low)

        arr = bands_data.astype("uint8")

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
    log.debug(f"Processing tile {tile_id}")
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
            file_exists=False,
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
        file_exists=True,
    )


def get(
    aoi: Polygon | MultiPolygon,
    start_date: date,
    end_date: date,
    output_dir: Path,
    n_workers_dl: int = 4,
    n_workers_pp: int = 4,
    download: bool = True,
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
    n_workers_dl : int
        Number of parallel download jobs. Defaults to 4.
    n_workers_pp : int
        Number of parallel preprocessing jobs. Defaults to 4.
    download : bool
        Enable downloading of tiles. If False, only already downloaded tiles are processed.
        Defaults to True.
    postprocess : bool
        Enable post-processing (compression to JP2). Defaults to False.
    quality : int
        JPEG2000 compression quality (1-100). Defaults to 50.

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
    return asyncio.run(
        _get_async(tasks, output_dir, n_workers_dl, n_workers_pp, download, postprocess, quality)
    )


async def _get_async(
    tasks: list[tuple[Tile, Period]],
    output_dir: Path,
    n_workers_dl: int,
    n_workers_pp: int,
    download: bool,
    postprocess: bool,
    quality: int,
) -> tuple[int, int]:
    if not download and not postprocess:
        log.info("download and postprocess are False. Nothing to do.")
        return 0, 0

    loop = asyncio.get_running_loop()

    with mp.Manager() as manager:
        log_queue = cast(LogQueue, manager.Queue())
        pp_executor = ProcessPoolExecutor if not lsat_debug() else SequentialExecutor

        with (
            pp_executor(
                max_workers=n_workers_pp,
                initializer=init_log_queue_for_children,
                initargs=(log_queue,),
            ) as pp_pool,
            ThreadPoolExecutor(max_workers=n_workers_dl) as dl_pool,
            LogQueueConsumer(log_queue),
            default_bar() as progress,
            Meta(output_dir / "meta.duckdb") as meta,
        ):
            stats = SessionStats(tasks, output_dir, meta, postprocess)
            meta.reconcile_existence(stats.task_ids)

            pp_bar = progress.add_task(
                "[cyan]Processing downloaded tiles...[/]",
                total=1,
                **stats.get_progress_fields("pp"),
            )
            if not postprocess:
                progress.update(pp_bar, visible=False)

            dl_bar = progress.add_task(
                "[cyan]Downloading Landsat ARD tiles...[/]",
                total=len(tasks),
                **stats.get_progress_fields("dl"),
            )
            if not download:
                progress.update(dl_bar, visible=False)

            n_pp_submitted = 0
            pp_futures: dict[asyncio.Future[ProcessResult], str] = {}
            dl_futures: dict[asyncio.Future[DownloadResult | None], tuple[Tile, Period, str]] = {}

            n_failures = 0
            n_downloaded = 0
            n_processed = 0
            n_dl_skipped = 0
            n_pp_skipped = 0
            first_failure = None

            # sort for spatial exhaustivity first, temporal second
            tasks = sorted(tasks, key=lambda tp: (-tp[1].n, tp[0].lat, tp[0].lon))
            # Filter tasks before submitting
            for tile, period in tasks:
                tile_id = f"{tile.lon_name}_{tile.lat_name}:{period.n}"
                tif_path = output_dir / f"{tile.lat_name}_{tile.lon_name}" / f"{period.n}.tif"
                jp2_path = tif_path.with_suffix(".jp2")

                # Check if we should skip download
                skip_dl = not download
                if not skip_dl:
                    if tile_id in meta.dl and meta.dl[tile_id]["is_missing"]:
                        log.debug(f"Skipping {tile_id}: established as missing on S3.")
                        skip_dl = True
                    elif tile_id in meta.pp and meta.pp[tile_id]["discarded"]:
                        log.debug(f"Skipping {tile_id}: established as too cloudy.")
                        skip_dl = True
                    elif jp2_path.exists():
                        log.debug(f"Skipping {tile_id}: JP2 already exists.")
                        skip_dl = True
                    elif tif_path.exists():
                        log.debug(f"Skipping {tile_id}: TIFF already exists.")
                        skip_dl = True

                if skip_dl:
                    n_dl_skipped += 1

                    # If tif exists but not processed, we still want to process it
                    if postprocess and tif_path.exists() and not jp2_path.exists():
                        if tile_id in meta.pp and meta.pp[tile_id]["discarded"]:
                            log.debug(f"{tif_path} exists but is marked as filtered out. Removing.")
                            tif_path.unlink()
                            # Mark as not existing in downloads
                            if tile_id in meta.dl:
                                d = meta.dl[tile_id]
                                d["file_exists"] = False
                                meta.dl[tile_id] = d
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
                            progress.update(pp_bar, total=n_pp_submitted)

                    progress.advance(dl_bar)
                    stats.update_ui(meta, progress, dl_bar, pp_bar)
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
                                    # New downloads always exist on disk
                                    dl_res["file_exists"] = True
                                    meta.dl[tile_id] = cast(dict[str, Any], dl_res)
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
                                            progress.update(pp_bar, total=n_pp_submitted)
                                else:
                                    n_failures += 1
                            except Exception as e:
                                log.error(f"Error downloading {tile_id}: {e}")
                                n_failures += 1
                                first_failure = first_failure if first_failure is not None else e
                            finally:
                                if dl_bar is not None:
                                    progress.advance(dl_bar)
                                stats.update_ui(meta, progress, dl_bar, pp_bar)

                        elif task in pp_futures:
                            task = cast(asyncio.Future[ProcessResult], task)
                            tile_id = pp_futures.pop(task)
                            try:
                                pp_res: ProcessResult = task.result()
                                pp_res["file_exists"] = not pp_res["discarded"]
                                meta.pp[tile_id] = cast(dict[str, Any], pp_res)

                                # When a JP2 is created or a TIF is discarded, the TIF is deleted.
                                # Update downloads table to reflect disk usage.
                                if tile_id in meta.dl:
                                    d = meta.dl[tile_id]
                                    d["file_exists"] = False
                                    meta.dl[tile_id] = d
                                if pp_res["discarded"]:
                                    n_pp_skipped += 1
                                else:
                                    n_processed += 1
                            except Exception as e:
                                log.error(f"Error processing {tile_id}: {e}")
                                n_failures += 1
                                first_failure = first_failure if first_failure is not None else e
                            finally:
                                progress.advance(pp_bar)
                                stats.update_ui(meta, progress, dl_bar, pp_bar)
            except (KeyboardInterrupt, asyncio.CancelledError):
                log.warning("[yellow]Interrupt received. Please wait for cleanup...[/]")
                for fut in dl_futures:
                    fut.cancel()
                dl_pool.shutdown(wait=False, cancel_futures=True)
                pp_pool.shutdown(wait=False, cancel_futures=True)
                raise

            # Final forced UI update
            stats.update_ui(meta, progress, dl_bar, pp_bar, force=True)

            if n_failures > 0:
                raise DownloadError(
                    f"{n_failures} failure(s) during download/processing."
                ) from first_failure

            if download:
                log.info(
                    f"[green]Finished[/]: downloaded {n_downloaded} tiles, skipped {n_dl_skipped}"
                )
            else:
                log.info("[green]Finished[/]: skipped download stage")

            if postprocess:
                log.info(f"Processed {n_processed} tiles. Discarded {n_pp_skipped} tiles.")

    return n_downloaded, n_processed
