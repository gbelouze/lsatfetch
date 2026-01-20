import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

__all__ = ["default_bar", "lsat_debug"]


log = logging.getLogger(__name__)


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
        TimeElapsedColumn(),
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
    try:
        task = progress.add_task(*args, **kwargs)
        yield task
    finally:
        progress.update(task, visible=False)
        progress.remove_task(task)


if __name__ == "__main__":
    log.info(f"{lsat_debug()=}")
