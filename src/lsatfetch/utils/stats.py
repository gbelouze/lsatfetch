"""Statistics management for Landsat image processing."""

import logging
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

import duckdb
import rasterio as rio

from lsatfetch.const import KEEP_VALUES, NODATA_THRESHOLD

log = logging.getLogger(__name__)


class ImageStatistics(TypedDict):
    """Statistics for a single processed image."""

    file_id: str
    n_valid_initial: int
    n_valid_final: int
    discarded: bool
    processed_at: datetime
    size_bytes: int | None
    compressed_size_bytes: int | None


class Statistics(MutableMapping[str, ImageStatistics]):
    def __init__(self, db_path: str, table_name: str = "image_stats"):
        self.db_path = db_path
        self.table = table_name

        # Initialize the table once at startup
        with self._connection() as con:
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    file_id TEXT PRIMARY KEY,
                    n_valid_initial INTEGER,
                    n_valid_final INTEGER,
                    discarded BOOLEAN,
                    processed_at TIMESTAMP,
                    size_bytes BIGINT,
                    compressed_size_bytes BIGINT
                )
            """)

    @contextmanager
    def _connection(self, read_only: bool = True):
        """Helper to open and automatically close the connection.
        
        Yields
        ------
        con: DuckDBPyConnection
        """
        con = duckdb.connect(self.db_path, read_only=read_only)
        try:
            yield con
        finally:
            con.close()

    def __setitem__(self, key: str, value: ImageStatistics):
        query = f"INSERT OR REPLACE INTO {self.table} VALUES (?, ?, ?, ?, ?, ?, ?)"
        with self._connection(read_only=False) as con:
            con.execute(
                query,
                [
                    key,
                    value["n_valid_initial"],
                    value["n_valid_final"],
                    value["discarded"],
                    value["processed_at"],
                    value.get("size_bytes"),
                    value.get("compressed_size_bytes"),
                ],
            )

    def __getitem__(self, key: str) -> ImageStatistics:
        with self._connection() as con:
            row = con.execute(f"SELECT * FROM {self.table} WHERE file_id = ?", [key]).fetchone()

        if not row:
            raise KeyError(key)

        return ImageStatistics(
            file_id=row[0],
            n_valid_initial=row[1],
            n_valid_final=row[2],
            discarded=row[3],
            processed_at=row[4],
            size_bytes=row[5],
            compressed_size_bytes=row[6],
        )

    def __delitem__(self, key: str):
        with self._connection(read_only=False) as con:
            # Check existence first to satisfy MutableMapping contract
            exists = con.execute(f"SELECT 1 FROM {self.table} WHERE file_id = ?", [key]).fetchone()
            if not exists:
                raise KeyError(key)
            con.execute(f"DELETE FROM {self.table} WHERE file_id = ?", [key])

    def __iter__(self) -> Iterator[str]:
        with self._connection() as con:
            res = con.execute(f"SELECT file_id FROM {self.table}").fetchall()
        return iter([r[0] for r in res])

    def __len__(self) -> int:
        with self._connection() as con:
            return con.execute(f"SELECT count(*) FROM {self.table}").fetchone()[0]

    def __contains__(self, key: Any) -> bool:
        with self._connection() as con:
            res = con.execute(f"SELECT 1 FROM {self.table} WHERE file_id = ?", [key]).fetchone()
        return res is not None


def get_file_id(tif_path: Path) -> str:
    """
    Extract file identifier from TIFF path.

    Parameters
    ----------
    tif_path : Path
        Path to the TIFF file (e.g., "075W_12N_1017.tif")

    Returns
    -------
    str
        File ID without extension (e.g., "075W_12N_1017")
    """
    return tif_path.stem


def compute_pixel_statistics(tif_path: Path) -> dict[str]:
    """
    Compute statistics from band 8 (QA) data.

    Parameters
    ----------
    band8_data
        Raw band 8 data from rasterio.

    Returns
    -------
    dict
        Dictionary with keys:
        - n_valid_initial: pixels where band8 != 0
        - n_valid_final: pixels where band8 in KEEP_VALUES
        - discarded: True if >=80% nodata
    """
    import numpy as np

    with rio.open(tif_path, "r") as src:
        band8 = src.read(8)
    height, width = band8.shape
    total_pixels = height * width

    nodata_mask = band8 == 0
    valid_mask = np.isin(band8, list(KEEP_VALUES))

    n_valid_initial = int(np.sum(~nodata_mask))
    n_valid_final = int(np.sum(valid_mask))

    discarded = (1 - n_valid_final / total_pixels) >= NODATA_THRESHOLD

    return {
        "n_valid_initial": n_valid_initial,
        "n_valid_final": n_valid_final,
        "discarded": discarded,
    }


def report_statistics(stats: Statistics) -> None:
    """
    Print a formatted statistics report to the console.

    Parameters
    ----------
    stats_path : Path
        Path to statistics.parquet file.
    """
    from rich.table import Table

    table = Table(title="Image Processing Statistics")
    table.add_column("File ID", justify="left")
    table.add_column("Valid %", justify="right")
    table.add_column("Status")
    table.add_column("Original", justify="right")
    table.add_column("Compressed", justify="right")
    table.add_column("Ratio")

    total_original = 0
    total_compressed = 0

    for file_id in stats:
        s = stats[file_id]

        if s["n_valid_initial"] > 0:
            valid_pct = (s["n_valid_final"] / s["n_valid_initial"]) * 100
            valid_str = f"{valid_pct:.1f}%"
        else:
            valid_str = "N/A"

        status = "DISCARDED" if s["discarded"] else "COMPRESSED"
        status_style = "red" if s["discarded"] else "green"

        orig_str = _format_size(s["size_bytes"]) if s["size_bytes"] else "-"
        comp_str = _format_size(s["compressed_size_bytes"]) if s["compressed_size_bytes"] else "-"

        ratio_str = ""
        if s["size_bytes"] and s["compressed_size_bytes"] and s["size_bytes"] > 0:
            ratio = (s["size_bytes"] - s["compressed_size_bytes"]) / s["size_bytes"] * 100
            ratio_str = f"{ratio:.0f}%"

        total_original += s["size_bytes"] or 0
        total_compressed += s["compressed_size_bytes"] or 0

        table.add_row(
            s["file_id"],
            valid_str,
            f"[{status_style}]{status}[/{status_style}]",
            orig_str,
            comp_str,
            ratio_str,
        )

    table.add_row(
        "",
        "",
        "[bold]TOTALS[/bold]",
        _format_size(total_original),
        _format_size(total_compressed),
        f"{(total_original - total_compressed) / total_original * 100:.0f}%"
        if total_original > 0
        else "-",
    )

    from rich import print as rprint

    rprint(table)


def _format_size(size_bytes: int | None) -> str:
    """Format byte size as human-readable string."""
    if size_bytes is None:
        return "-"

    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes = int(size_bytes / 1024)
    return f"{size_bytes:.1f} TB"
