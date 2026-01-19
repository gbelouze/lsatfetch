"""Pytest configuration and fixtures for lsatfetch tests."""

from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent


@pytest.fixture
def sample_config_path(tmp_path: Path) -> Path:
    """Copy sample_config.yaml to a temporary directory."""
    source = TESTS_DIR / "data" / "sample_config.yaml"
    dest = tmp_path / "sample_config.yaml"
    dest.write_text(source.read_text())
    return dest
