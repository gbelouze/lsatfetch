import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    Task,
    TaskID,
    TextColumn,
)
from rich.text import Text

__all__ = ["default_bar", "lsat_debug"]


log = logging.getLogger(__name__)


class LSATStatsColumn(ProgressColumn):
    """Shows filter rates and averages for TIF and JP2 files."""

    def render(self, task: Task) -> Text:
        stats = task.fields.get("stats", {})
        if not stats:
            return Text("")

        dl_f = stats.get("dl_filter_rate", 0) * 100
        pp_f = stats.get("pp_filter_rate", 0) * 100

        tif_avg = (stats.get("avg_tif_size") or 0) / 1_000_000
        jp2_avg = (stats.get("avg_jp2_size") or 0) / 1_000_000

        return Text(
            f"F: {dl_f:>.0f}%(dl) / {pp_f:>.0f}%(pp) | "
            f"Avg: {tif_avg:.0f}(tif) /{jp2_avg:.0f}(jp2) MB",
            style="dim yellow",
        )


class LSATPredictiveBytesColumn(ProgressColumn):
    """Shows [Completed Bytes] / [Estimated Total Bytes]."""

    def render(self, task: Task) -> Text:
        completed = (task.fields.get("completed_bytes") or 0) / 1_000_000_000
        total = (task.fields.get("total_predicted_bytes") or 0) / 1_000_000_000
        return Text(f"{completed:.1f}/{total:.1f} GB", style="cyan")


class LSATTimeColumn(ProgressColumn):
    """Shows [Elapsed] < [Remaining] for the whole session."""

    def render(self, task: Task) -> Text:
        elapsed = task.elapsed
        remaining = task.time_remaining
        if elapsed is None:
            return Text("- < -", style="dim")

        e_str = self._format_time(elapsed)
        r_str = self._format_time(remaining) if remaining is not None else "-"
        return Text(f"{e_str} < {r_str}", style="dim cyan")

    def _format_time(self, seconds: float) -> str:
        minutes, seconds = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


def lsat_debug() -> bool:
    match os.getenv("LSATFETCH_DEBUG"):
        case "true":
            return True
        case "1":
            return True
        case _:
            return False


def default_bar() -> Progress:
    disabled = lsat_debug()
    if disabled:
        log.warning("progress bar is disabled.")
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        LSATPredictiveBytesColumn(),
        LSATStatsColumn(),
        LSATTimeColumn(),
        refresh_per_second=1,
        disable=disabled,
    )


@contextmanager
def temporary_task(progress: Progress, *args: Any, **kwargs: Any) -> Iterator[TaskID]:
    """
    Context manager that adds a progress task and ensures it is removed
    when the context exits, regardless of success or failure.

    Parameters
    ----------
    progress : Progress
        A `rich.progress.Progress` instance managing the tasks.
    *args : Any
        Positional arguments passed to `progress.add_task`.
    **kwargs : Any
        Keyword arguments passed to `progress.add_task`.

    Yields
    ------
    TaskID
        The task ID returned by `progress.add_task`.

    Notes
    -----
    - The task is first hidden (`visible=False`) and then removed from
      the progress display when the context exits.
    - Any exception raised within the context is propagated after
      cleanup.

    Examples
    --------
    >>> from rich.progress import Progress
    >>> progress = Progress()
    >>> with progress:
    ...     with add_task_finally_remove(progress, "Processing", total=100) as task:
    ...         for i in range(100):
    ...             progress.update(task, advance=1)
    """
    task = None
    try:
        task = progress.add_task(*args, **kwargs)
        yield task
    finally:
        if task is not None:
            progress.update(task, visible=False)
            progress.remove_task(task)


if __name__ == "__main__":
    log.info(f"{lsat_debug()=}")
