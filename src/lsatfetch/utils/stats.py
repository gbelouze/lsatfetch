import time
from pathlib import Path
from typing import Any

from rich.progress import Progress, TaskID

from lsatfetch.tile import Period, Tile
from lsatfetch.utils.meta import Meta


class SessionStats:
    """Tracks download and processing statistics for a session using Meta as truth."""

    def __init__(
        self,
        tasks: list[tuple[Tile, Period]],
        output_dir: Path,
        meta: Meta,
        postprocess_enabled: bool,
        update_interval: float = 0.5,
    ):
        self.task_ids = [f"{t.lon_name}_{t.lat_name}:{p.n}" for t, p in tasks]
        self.postprocess_enabled = postprocess_enabled
        self.update_interval = update_interval
        self.last_update = time.monotonic()

        # Initial snapshots
        self._global_stats: dict[str, Any] = meta.get_stats()
        self._session_summary: dict[str, Any] = meta.get_session_summary(
            self.task_ids, postprocess_enabled
        )

    def update_ui(
        self,
        meta: Meta,
        progress: Progress,
        dl_bar: TaskID | None,
        pp_bar: TaskID | None,
        force: bool = False,
    ) -> None:
        """Update the progress bar tasks with current stats from Meta."""
        now = time.monotonic()
        if not force and (now - self.last_update < self.update_interval):
            return

        self.last_update = now
        self._global_stats = meta.get_stats()
        self._session_summary = meta.get_session_summary(self.task_ids, self.postprocess_enabled)

        if dl_bar is not None:
            progress.update(dl_bar, **self.get_progress_fields("dl"))
        if pp_bar is not None:
            progress.update(pp_bar, **self.get_progress_fields("pp"))

    def get_progress_fields(self, mode: str = "dl") -> dict[str, Any]:
        """Calculate fields for Rich progress bars based on current snapshots."""
        gs = self._global_stats
        ss = self._session_summary

        if mode == "dl":
            total = ss.get("dl_total", 0)
            rate = (
                ss.get("dl_missing", 0) / total if total > 0 else (gs.get("dl_filter_rate") or 0.0)
            )
            avg_size = gs.get("avg_tif_size") or 130_000_000
            completed_bytes = ss.get("dl_bytes", 0)

            # For DL, a task is 'done' if it's in the downloads table (missing or success)
            n_done = ss.get("dl_total", 0)
            pending = max(0, len(self.task_ids) - n_done)

            est_size_per_task = (1 - rate) * avg_size
            total_predicted = completed_bytes + (pending * est_size_per_task)
        else:
            total = ss.get("pp_total", 0)
            rate = (
                ss.get("pp_discarded", 0) / total
                if total > 0
                else (gs.get("pp_filter_rate") or 0.0)
            )
            avg_size = gs.get("avg_jp2_size") or 30_000_000
            completed_bytes = ss.get("pp_bytes", 0)

            # For PP, a task is 'done' if it's in the postprocessing table (discarded or success)
            n_done = ss.get("pp_total", 0)
            pending = max(0, len(self.task_ids) - n_done)

            est_size_per_task = (1 - rate) * avg_size
            total_predicted = completed_bytes + (pending * est_size_per_task)

        return {
            "stats": {
                "filter_rate": rate,
                "avg_size": avg_size,
            },
            "completed_bytes": completed_bytes,
            "total_predicted_bytes": total_predicted,
        }
