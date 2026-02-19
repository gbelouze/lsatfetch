from pathlib import Path
from typing import Any

from rich.progress import Progress, TaskID

from lsatfetch.tile import Period, Tile
from lsatfetch.utils.meta import DownloadResult, Meta, ProcessResult


class SessionStats:
    """Tracks download and processing statistics for a session."""

    def __init__(
        self,
        tasks: list[tuple[Tile, Period]],
        output_dir: Path,
        meta: Meta,
        download_enabled: bool,
        postprocess_enabled: bool,
    ):
        self.output_dir = output_dir
        self.download_enabled = download_enabled
        self.postprocess_enabled = postprocess_enabled

        # Historical stats from DB
        db_stats = meta.get_stats()
        self.hist_dl_rate = db_stats["dl_filter_rate"] or 0.0
        self.hist_pp_rate = db_stats["pp_filter_rate"] or 0.0
        self.avg_tif_size = db_stats["avg_tif_size"] or 130_000_000
        self.avg_jp2_size = db_stats["avg_jp2_size"] or 30_000_000

        # Session counters for UI / filtering logic
        self.dl_total = 0
        self.dl_missing_count = 0
        self.pp_total = 0
        self.pp_discarded_count = 0

        # Pipeline counters for final reporting
        self.n_downloaded = 0
        self.n_dl_skipped = 0
        self.n_processed = 0
        self.n_pp_skipped = 0

        self.completed_bytes = 0
        self.pending_tasks = len(tasks)
        self.done_tasks: set[str] = set()

        self._initial_scan(tasks)

    def _initial_scan(self, tasks: list[tuple[Tile, Period]]) -> None:
        """Scan directory for already completed files to set baseline."""
        for tile, period in tasks:
            tile_id = f"{tile.lon_name}_{tile.lat_name}:{period.n}"
            tif_path = self.output_dir / f"{tile.lat_name}_{tile.lon_name}" / f"{period.n}.tif"
            jp2_path = tif_path.with_suffix(".jp2")

            if jp2_path.exists():
                self.completed_bytes += jp2_path.stat().st_size
                self.pending_tasks -= 1
                self.done_tasks.add(tile_id)
            elif not self.postprocess_enabled and tif_path.exists():
                self.completed_bytes += tif_path.stat().st_size
                self.pending_tasks -= 1
                self.done_tasks.add(tile_id)

    def dl_done(self, res: DownloadResult) -> None:
        """Record a successful (or 404) download result from a worker."""
        tile_id = res["id"]
        if tile_id in self.done_tasks:
            return

        self.dl_total += 1
        if res["is_missing"]:
            self.dl_missing_count += 1
            self.n_dl_skipped += 1
            self.pending_tasks -= 1
            self.done_tasks.add(tile_id)
        else:
            self.n_downloaded += 1
            if not self.postprocess_enabled:
                self.completed_bytes += res["size_bytes"] or 0
                self.pending_tasks -= 1
                self.done_tasks.add(tile_id)

            if res["size_bytes"]:
                n = self.dl_total - self.dl_missing_count
                self.avg_tif_size = (self.avg_tif_size * (n - 1) + res["size_bytes"]) / n

    def dl_skipped(
        self,
        tile_id: str,
        is_missing: bool = False,
        is_discarded: bool = False,
        will_process: bool = False,
    ) -> None:
        """Record a skipped download (e.g., already exists or established missing)."""
        self.n_dl_skipped += 1

        if is_missing:
            self.dl_total += 1
            self.dl_missing_count += 1
        if is_discarded:
            self.pp_total += 1
            self.pp_discarded_count += 1
            self.n_pp_skipped += 1

        if tile_id in self.done_tasks:
            return

        if not will_process:
            self.pending_tasks -= 1
            self.done_tasks.add(tile_id)

    def pp_done(self, res: ProcessResult) -> None:
        """Record a processing result from a worker."""
        tile_id = res["id"]

        self.pp_total += 1
        if tile_id not in self.done_tasks:
            self.pending_tasks -= 1
            self.done_tasks.add(tile_id)

        if res["discarded"]:
            self.pp_discarded_count += 1
            self.n_pp_skipped += 1
        else:
            self.n_processed += 1
            if res["compressed_size_bytes"]:
                self.completed_bytes += res["compressed_size_bytes"]
                n = self.pp_total - self.pp_discarded_count
                self.avg_jp2_size = (self.avg_jp2_size * (n - 1) + res["compressed_size_bytes"]) / n

    def pp_skipped(self, tile_id: str) -> None:
        """Record a skipped processing task (e.g., established discarded)."""
        self.n_pp_skipped += 1
        if tile_id not in self.done_tasks:
            self.pending_tasks -= 1
            self.done_tasks.add(tile_id)

    def get_progress_fields(self) -> dict[str, Any]:
        """Calculate fields for Rich progress bars."""
        dl_rate = self.dl_missing_count / self.dl_total if self.dl_total > 0 else self.hist_dl_rate
        pp_rate = (
            self.pp_discarded_count / self.pp_total if self.pp_total > 0 else self.hist_pp_rate
        )

        if self.postprocess_enabled:
            est_size = (1 - dl_rate) * (1 - pp_rate) * self.avg_jp2_size
        else:
            est_size = (1 - dl_rate) * self.avg_tif_size

        total_predicted = self.completed_bytes + (self.pending_tasks * est_size)
        breakpoint()

        return {
            "stats": {
                "dl_filter_rate": dl_rate,
                "pp_filter_rate": pp_rate,
                "avg_tif_size": self.avg_tif_size,
                "avg_jp2_size": self.avg_jp2_size,
            },
            "completed_bytes": self.completed_bytes,
            "total_predicted_bytes": total_predicted,
        }

    def update_ui(self, progress: Progress, dl_bar: TaskID | None, pp_bar: TaskID | None) -> None:
        """Update the progress bar tasks with current stats."""
        fields = self.get_progress_fields()
        if dl_bar is not None:
            progress.update(dl_bar, **fields)
        if pp_bar is not None:
            progress.update(pp_bar, **fields)
