"""Tests for CLI API consistency (help output comparison)."""

import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent


def run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run the CLI with given arguments and return exit code, stdout, stderr."""
    result = subprocess.run(
        [sys.executable, "-m", "lsatfetch.cli.main"] + args,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def test_help_consistency() -> None:
    """Test that main --help output matches expected."""
    exit_code, stdout, _ = run_cli(["--help"])

    assert exit_code == 0
    expected = (TESTS_DIR / "data" / "cli_help.txt").read_text()
    assert stdout == expected


def test_init_help_consistency() -> None:
    """Test that init --help output matches expected."""
    exit_code, stdout, _ = run_cli(["init", "--help"])

    assert exit_code == 0
    expected = (TESTS_DIR / "data" / "init_help.txt").read_text()
    assert stdout == expected


def test_get_help_consistency() -> None:
    """Test that get --help output matches expected."""
    exit_code, stdout, _ = run_cli(["get", "--help"])

    assert exit_code == 0
    expected = (TESTS_DIR / "data" / "get_help.txt").read_text()
    assert stdout == expected


def test_status_help_consistency() -> None:
    """Test that status --help output matches expected."""
    exit_code, stdout, _ = run_cli(["status", "--help"])

    assert exit_code == 0
    expected = (TESTS_DIR / "data" / "status_help.txt").read_text()
    assert stdout == expected
