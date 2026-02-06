"""Metadata management for Landsat image processing."""

import logging
from collections.abc import Iterator, MutableMapping
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, TypedDict, TypeVar, cast

import duckdb
import rasterio as rio

from lsatfetch.const import KEEP_VALUES, NODATA_THRESHOLD

log = logging.getLogger(__name__)


class DownloadResult(TypedDict):
    """Result of a download operation."""

    id: str
    path: str
    downloaded_at: datetime
    size_bytes: int | None
    is_missing: bool


class ProcessResult(TypedDict):
    """Result of a post-processing operation."""

    id: str
    path: str
    processed_at: datetime
    n_valid_initial: int
    n_valid_final: int
    discarded: bool
    compressed_size_bytes: int | None


T = TypeVar("T", DownloadResult, ProcessResult)


class TableManager(MutableMapping[str, T], Generic[T]):
    """Helper to manage a specific table with a dict-like interface."""

    def __init__(self, meta: "Meta", table_name: str, schema: dict[str, str]):
        self.meta = meta
        self.table = table_name
        self.schema = schema
        self._columns = list(schema.keys())

    def __getitem__(self, key: str) -> T:
        query = f"SELECT * FROM {self.table} WHERE id = ?"
        row = self.meta.con.execute(query, [key]).fetchone()
        if not row:
            raise KeyError(key)
        return cast(T, dict(zip(self._columns, row, strict=True)))

    def __setitem__(self, key: str, value: T) -> None:
        cols = ", ".join(self._columns)
        placeholders = ", ".join(["?"] * len(self._columns))
        query = f"INSERT OR REPLACE INTO {self.table} ({cols}) VALUES ({placeholders})"

        # Ensure id is in the value
        value["id"] = key
        data = [value.get(col) for col in self._columns]
        self.meta.con.execute(query, data)

    def __delitem__(self, key: str) -> None:
        if key not in self:
            raise KeyError(key)
        self.meta.con.execute(f"DELETE FROM {self.table} WHERE id = ?", [key])

    def __iter__(self) -> Iterator[str]:
        res = self.meta.con.execute(f"SELECT id FROM {self.table}").fetchall()
        return iter([r[0] for r in res])

    def __len__(self) -> int:
        count = self.meta.con.execute(f"SELECT count(*) FROM {self.table}").fetchone()
        if count is None:
            raise RuntimeError("count(*) failed to return a value.")
        return int(count[0])

    def __contains__(self, key: Any) -> bool:
        res = self.meta.con.execute(f"SELECT 1 FROM {self.table} WHERE id = ?", [key]).fetchone()
        return res is not None


class Meta:
    """Centralized metadata management using DuckDB."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._con: duckdb.DuckDBPyConnection | None = None

        # Define schemas
        self._dl_schema = {
            "id": "TEXT PRIMARY KEY",
            "path": "TEXT",
            "downloaded_at": "TIMESTAMP",
            "size_bytes": "BIGINT",
            "is_missing": "BOOLEAN",
        }
        self._pp_schema = {
            "id": "TEXT PRIMARY KEY",
            "path": "TEXT",
            "processed_at": "TIMESTAMP",
            "n_valid_initial": "INTEGER",
            "n_valid_final": "INTEGER",
            "discarded": "BOOLEAN",
            "compressed_size_bytes": "BIGINT",
        }

        # Initialize tables
        with self:
            self._create_table("downloads", self._dl_schema)
            self._create_table("postprocessing", self._pp_schema)

        self.dl: TableManager[DownloadResult] = TableManager(self, "downloads", self._dl_schema)
        self.pp: TableManager[ProcessResult] = TableManager(self, "postprocessing", self._pp_schema)

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        """Get the active database connection.

        Returns
        -------
        duckdb.DuckDBPyConnection
            The active DuckDB connection.

        Raises
        ------
        RuntimeError
            If the connection is not active (i.e., not within a 'with' block).
        """
        if self._con is None:
            msg = "Database connection is not active. Use Meta as a context manager."
            raise RuntimeError(msg)
        return self._con

    def _create_table(self, name: str, schema: dict[str, str]) -> None:
        cols = ", ".join([f"{k} {v}" for k, v in schema.items()])
        self.con.execute(f"CREATE TABLE IF NOT EXISTS {name} ({cols})")

    def __enter__(self) -> "Meta":
        if self._con is None:
            self._con = duckdb.connect(str(self.db_path))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._con:
            self._con.close()
            self._con = None


def compute_pixel_statistics(tif_path: Path) -> dict[str, Any]:
    """
    Compute statistics from band 8 (QA) data.

    Parameters
    ----------
    tif_path : Path
        Path to the TIFF file.

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


def report_statistics(db_path: Path) -> None:
    """
    Print a formatted statistics report to the console.

    Parameters
    ----------
    db_path : Path
        Path to meta.duckdb file.
    """
    from rich.table import Table

    with Meta(db_path) as meta:
        # Join tables to get a comprehensive view
        query = """
            SELECT
                d.id,
                p.n_valid_initial,
                p.n_valid_final,
                p.discarded,
                d.size_bytes,
                p.compressed_size_bytes
            FROM downloads d
            LEFT JOIN postprocessing p ON d.id = p.id
            ORDER BY d.id
        """
        rows = meta.con.execute(query).fetchall()

    if not rows:
        log.info("No statistics found in database.")
        return

    table = Table(title="Landsat Processing Statistics")
    table.add_column("ID", justify="left")
    table.add_column("Valid %", justify="right")
    table.add_column("Status")
    table.add_column("Original", justify="right")
    table.add_column("Compressed", justify="right")
    table.add_column("Ratio")

    total_original = 0
    total_compressed = 0

    for row in rows:
        tile_id, n_init, n_final, discarded, size, comp_size = row

        if n_init and n_init > 0:
            valid_pct = (n_final / n_init) * 100
            valid_str = f"{valid_pct:.1f}%"
        else:
            valid_str = "N/A"

        if discarded:
            status = "DISCARDED"
            status_style = "red"
        elif comp_size:
            status = "COMPRESSED"
            status_style = "green"
        else:
            status = "DOWNLOADED"
            status_style = "blue"

        orig_str = _format_size(size) if size else "-"
        comp_str = _format_size(comp_size) if comp_size else "-"

        ratio_str = ""
        if size and comp_size and size > 0:
            ratio = (size - comp_size) / size * 100
            ratio_str = f"{ratio:.0f}%"

        total_original += size or 0
        total_compressed += comp_size or 0

        table.add_row(
            tile_id,
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

    f_size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if f_size < 1024:
            return f"{f_size:.1f} {unit}"
        f_size /= 1024
    return f"{f_size:.1f} TB"
