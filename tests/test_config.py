"""Tests for configuration loading."""

from pathlib import Path
from textwrap import dedent

from landsat.cli.config import Config, load


def test_load_valid_config(sample_config_path: Path) -> None:
    """Test loading a valid configuration file."""
    cfg = load(sample_config_path)

    assert isinstance(cfg, Config)
    assert cfg.aoi.type == "bbox"
    assert cfg.aoi.left == -5
    assert cfg.aoi.bottom == 42
    assert cfg.aoi.right == 9
    assert cfg.aoi.top == 51
    assert cfg.time_range.start == "2020-01-01"
    assert cfg.time_range.end == "2024-01-01"
    assert cfg.output_dir == Path("/tmp/landsat_test")
    assert cfg.parallel_jobs == 2
    assert cfg.cloud_filter is None


def test_default_values_applied(tmp_path: Path) -> None:
    """Test that default values are applied when not specified in config."""
    config_content = dedent(
        """\
        aoi:
          type: bbox
          left: 0
          bottom: 0
          right: 1
          top: 1
        time_range:
          start: "2023-01-01"
          end: "2023-12-31"
        output_dir: /tmp/test
        """
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(config_content)

    cfg = load(config_path)

    assert cfg.parallel_jobs == 4
    assert cfg.cloud_filter is None


def test_output_dir_expanded(tmp_path: Path) -> None:
    """Test that output_dir is expanded and made absolute."""
    config_content = dedent(
        """\
        aoi:
          type: bbox
          left: 0
          bottom: 0
          right: 1
          top: 1
        time_range:
          start: "2023-01-01"
          end: "2023-12-31"
        output_dir: relative/path
        """
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(config_content)

    cfg = load(config_path)

    assert cfg.output_dir.is_absolute()
    assert cfg.output_dir.name == "path"


def test_cloud_filter_optional(tmp_path: Path) -> None:
    """Test that cloud_filter is optional."""
    config_content = dedent(
        """\
        aoi:
          type: bbox
          left: 0
          bottom: 0
          right: 1
          top: 1
        time_range:
          start: "2023-01-01"
          end: "2023-12-31"
        output_dir: /tmp/test
        cloud_filter:
            max_cloud_percent: 20.0
    """
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(config_content)

    cfg = load(config_path)

    assert cfg.cloud_filter is not None
    assert cfg.cloud_filter.max_cloud_percent == 20.0
