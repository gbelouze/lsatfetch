import logging
from pathlib import Path

from lsatfetch.cli.config import load

log = logging.getLogger(__name__)


def status(config: Path) -> None:
    from lsatfetch.utils.log import setup

    setup(level=logging.INFO)

    log.info("Dataset Status")

    if not config.exists():
        log.warning(f"Configuration file not found: {config}")
        raise SystemExit(1)

    cfg = load(config)
    log.info("Configuration loaded")
    log.info(f"  Output directory: {cfg.output_dir}")
    log.info(f"  AOI type: {cfg.aoi.type}")
    log.info(f"  Parallel jobs: {cfg.parallel_jobs}")

    output_dir = Path(cfg.output_dir)
    if output_dir.exists():
        log.info("Output directory exists")
        config_in_output = output_dir / "config.yaml"
        if config_in_output.exists():
            log.info(f"  Saved configuration: {config_in_output}")
    else:
        log.warning("Output directory does not exist yet")
        log.info(f"  Run 'lsatfetch get -c {config}' to create the dataset")
