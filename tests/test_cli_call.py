"""Tests for CLI execution."""

import subprocess
import sys
from pathlib import Path


def run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run the CLI with given arguments and return exit code, stdout, stderr."""
    result = subprocess.run(
        [sys.executable, "-m", "lsatfetch.cli.main"] + args,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def test_init_creates_file(tmp_path: Path) -> None:
    """Test that init creates a valid configuration file."""
    output_path = tmp_path / "config.yaml"
    exit_code, _stdout, _stderr = run_cli(["init", "--output", str(output_path)])

    assert exit_code == 0
    assert output_path.exists()

    content = output_path.read_text()
    assert "aoi:" in content
    assert "time_range:" in content
    assert "output_dir:" in content


def test_init_force_overwrites(tmp_path: Path) -> None:
    """Test that init --force overwrites existing file."""
    output_path = tmp_path / "config.yaml"

    exit_code1, _stdout1, _stderr1 = run_cli(["init", "--output", str(output_path)])
    assert exit_code1 == 0

    original_content = output_path.read_text()

    exit_code2, _stdout2, _stderr2 = run_cli(["init", "--output", str(output_path), "--force"])
    assert exit_code2 == 0

    new_content = output_path.read_text()
    assert new_content == original_content


def test_get_with_config(sample_config_path: Path) -> None:
    """Test that get command runs without error with valid config."""
    from unittest.mock import patch

    with patch("lsatfetch.cli.get.download_landsat") as mock_download:
        mock_download.return_value = (0, 0)
        exit_code, stdout, _stderr = run_cli(["get", "--config", str(sample_config_path)])

    assert exit_code == 0
    assert "Configuration loaded" in stdout


def test_status_with_config(sample_config_path: Path) -> None:
    """Test that status command runs without error with valid config."""
    exit_code, stdout, _stderr = run_cli(["status", "--config", str(sample_config_path)])

    assert exit_code == 0
    assert "Configuration loaded" in stdout


def test_get_missing_file_error() -> None:
    """Test that get shows proper error for missing config file."""
    exit_code, _stdout, _stderr = run_cli(["get", "--config", "nonexistent.yaml"])

    assert exit_code != 0


def test_status_missing_file_error() -> None:
    """Test that status shows proper error for missing config file."""
    exit_code, _stdout, _stderr = run_cli(["status", "--config", "nonexistent.yaml"])

    assert exit_code != 0


def test_init_generated_config_is_valid(tmp_path: Path) -> None:
    """Test that init creates a valid config that load can parse."""
    from lsatfetch.cli.config import load

    output_path = tmp_path / "config.yaml"

    exit_code, _stdout, _stderr = run_cli(["init", "--output", str(output_path)])
    assert exit_code == 0
    assert output_path.exists()

    cfg = load(output_path)
    assert cfg.aoi.type == "bbox"
    assert cfg.aoi.left == -180
    assert cfg.aoi.bottom == -90
    assert cfg.aoi.right == 180
    assert cfg.aoi.top == 90
    assert cfg.aoi.crs == "EPSG:4326"
    assert cfg.time_range.start == "2020-01-01"
    assert cfg.time_range.end == "2024-01-01"
    assert cfg.output_dir.name == output_path.name
    assert cfg.parallel_jobs == 4
