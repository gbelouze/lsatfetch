"""Pytest configuration and fixtures for lsatfetch tests."""

from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent


@pytest.fixture
def sample_config_path(tmp_path: Path) -> Path:
    """
    Copy sample_config.yaml to a temporary directory with small AOI and time range for fast tests.
    """
    source = TESTS_DIR / "data" / "sample_config.yaml"
    dest = tmp_path / "sample_config.yaml"
    content = source.read_text()
    content = content.replace("left: -5", "left: -0.5")
    content = content.replace("bottom: 42", "bottom: 41.5")
    content = content.replace("right: 9", "right: 0.5")
    content = content.replace("top: 51", "top: 42.5")
    content = content.replace('start: "2020-01-01"', 'start: "2020-01-01"')
    content = content.replace('end: "2024-01-01"', 'end: "2020-01-16"')
    content = content.replace("parallel_jobs: 2", "parallel_jobs: 4")
    dest.write_text(content)
    return dest


@pytest.fixture
def original_config_path(tmp_path: Path) -> Path:
    """Copy sample_config.yaml to a temporary directory without modifications."""
    source = TESTS_DIR / "data" / "sample_config.yaml"
    dest = tmp_path / "sample_config.yaml"
    dest.write_text(source.read_text())
    return dest
