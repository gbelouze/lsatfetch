from pathlib import Path
from typing import Protocol

from lsatfetch.tile import Tile


class DownloadProgressCallback(Protocol):
    """Protocol for download progress callbacks."""

    def __call__(self, tile: Tile, progress: float) -> None:
        """
        Report download progress.

        Parameters
        ----------
        tile : Tile
            Tile being downloaded.
        progress : float
            Progress value between 0.0 and 1.0.
        """
        ...


def download_tile(
    tile: Tile,
    output_dir: Path,
    progress: DownloadProgressCallback | None = None,
) -> list[Path]:
    """
    Download a single Landsat tile.

    If the tile has a time_index set, downloads that specific time period.
    If time_index is None, downloads all available time periods for the tile.

    Parameters
    ----------
    tile : Tile
        Tile to download (may have time_index set).
    output_dir : Path
        Directory to save downloaded files.
    progress : DownloadProgressCallback | None
        Optional progress callback.

    Returns
    -------
    list[Path]
        Paths to successfully downloaded files (may be empty if not found).
    """
    return []


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
