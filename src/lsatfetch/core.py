from pathlib import Path
from typing import Protocol


class DownloadProgressCallback(Protocol):
    """Protocol for download progress callbacks."""

    def __call__(self, tile_id: str, progress: float) -> None:
        """
        Report download progress.

        Parameters
        ----------
        tile_id : str
            Identifier of the tile being downloaded.
        progress : float
            Progress value between 0.0 and 1.0.
        """
        ...


def identify_tiles(aoi_bbox: tuple[float, float, float, float, str]) -> list[str]:
    """
    Identify Landsat tiles that intersect with the given AOI.

    Parameters
    ----------
    aoi_bbox : tuple[float, float, float, float, str]
        Bounding box specification (left, bottom, right, top).

    Returns
    -------
    list[str]
        List of tile identifiers that intersect the AOI.
    """
    return []


def download_tile(
    tile_id: str,
    output_dir: Path,
    time_range: tuple[str, str] | None = None,
    progress: DownloadProgressCallback | None = None,
) -> Path | None:
    """
    Download a single Landsat tile.

    Parameters
    ----------
    tile_id : str
        Landsat tile identifier.
    output_dir : Path
        Directory to save the downloaded tile.
    time_range : tuple[str, str] | None
        Optional time range (start, end) to filter data.
    progress : DownloadProgressCallback | None
        Optional progress callback.

    Returns
    -------
    Path | None
        Path to the downloaded file, or None if download failed.
    """
    return None


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


def estimate_download_size(tile_ids: list[str]) -> int:
    """
    Estimate total download size for a list of tiles.

    Parameters
    ----------
    tile_ids : list[str]
        List of tile identifiers.

    Returns
    -------
    int
        Estimated size in bytes.
    """
    return 0


def estimate_download_time(tile_ids: list[str], parallel_jobs: int) -> float:
    """
    Estimate download time for a list of tiles.

    Parameters
    ----------
    tile_ids : list[str]
        List of tile identifiers.
    parallel_jobs : int
        Number of parallel download jobs.

    Returns
    -------
    float
        Estimated time in seconds.
    """
    return 0.0
