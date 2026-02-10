"""Tests for Landsat image processing functions."""

from pathlib import Path

import numpy as np
import rasterio as rio
from rasterio.transform import Affine

from lsatfetch.const import NODATA_THRESHOLD
from lsatfetch.core import compress_landsat_image, process_file
from lsatfetch.utils.meta import compute_pixel_statistics


def create_test_tiff(
    path: Path,
    width: int = 32,
    height: int = 32,
    nodata_pct: float = 0.0,
    valid_mask_value: int = 1,
) -> None:
    """
    Create a small test TIFF file mimicking Landsat structure.

    Parameters
    ----------
    path : Path
        Path to save the TIFF file.
    width : int
        Width of the raster. Defaults to 32.
    height : int
        Height of the raster. Defaults to 32.
    nodata_pct : float
        Percentage of pixels that are nodata (band 8 == 0). Defaults to 0.0.
    valid_mask_value : int
        Value for valid pixels in band 8. Defaults to 1.
    """
    transform = Affine.translation(0.5, 0.5) * Affine.scale(0.001, -0.001)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 8,
        "dtype": "uint16",
        "transform": transform,
    }

    np.random.seed(42)
    bands = np.random.randint(0, 2**16, size=(8, height, width), dtype=np.uint16)

    nodata_mask = np.random.random((height, width)) < nodata_pct
    band8 = np.full((height, width), valid_mask_value, dtype=np.uint16)
    band8[nodata_mask] = 0
    bands[7] = band8

    with rio.open(path, "w", **profile) as dst:
        for i in range(8):
            dst.write(bands[i], indexes=i + 1)


class TestCompressLandsatImage:
    """Tests for compress_landsat_image function."""

    def test_compress_creates_jp2_file(self, tmp_path: Path) -> None:
        """Test that compression creates a valid JP2 output file."""
        input_path = tmp_path / "test_tile.tif"
        create_test_tiff(input_path)

        output_path = tmp_path / "test_tile.jp2"
        result = compress_landsat_image(input_path, output_path)

        assert result.exists()
        assert result.suffix == ".jp2"
        assert not input_path.exists()

    def test_compress_reduces_file_size(self, tmp_path: Path) -> None:
        """Test that compression typically reduces file size."""
        input_path = tmp_path / "test_tile.tif"
        create_test_tiff(input_path, width=64, height=64)

        original_size = input_path.stat().st_size
        output_path = tmp_path / "test_tile.jp2"
        compress_landsat_image(input_path, output_path)

        compressed_size = output_path.stat().st_size
        assert compressed_size < original_size

    def test_compress_overwrites_existing_output(self, tmp_path: Path) -> None:
        """Test that compression overwrites if output already exists."""
        input_path = tmp_path / "test_tile.tif"
        create_test_tiff(input_path)

        output_path = tmp_path / "test_tile.jp2"
        output_path.write_text("existing")

        result = compress_landsat_image(input_path, output_path)

        assert result.exists()
        assert not input_path.exists()
        # Should no longer be "existing" since it's a real JP2 now
        with output_path.open("rb") as f:
            content = f.read(8)
            assert content != b"existing"

    def test_compress_with_different_quality(self, tmp_path: Path) -> None:
        """Test compression with different quality settings."""
        input_path1 = tmp_path / "test_tile1.tif"
        input_path2 = tmp_path / "test_tile2.tif"
        create_test_tiff(input_path1)
        create_test_tiff(input_path2)

        output_low = tmp_path / "low.jp2"
        output_high = tmp_path / "high.jp2"

        compress_landsat_image(input_path1, output_low, quality=10)
        compress_landsat_image(input_path2, output_high, quality=100)

        size_low = output_low.stat().st_size
        size_high = output_high.stat().st_size
        assert size_low <= size_high

    def test_compress_deletes_input_file(self, tmp_path: Path) -> None:
        """Test that input file is deleted after successful compression."""
        input_path = tmp_path / "test_tile.tif"
        create_test_tiff(input_path)

        output_path = tmp_path / "test_tile.jp2"
        compress_landsat_image(input_path, output_path)

        assert not input_path.exists()

    def test_compress_validates_output_format(self, tmp_path: Path) -> None:
        """Test that output JP2 file is valid rasterio dataset."""
        input_path = tmp_path / "test_tile.tif"
        create_test_tiff(input_path)

        output_path = tmp_path / "test_tile.jp2"
        compress_landsat_image(input_path, output_path)

        with rio.open(output_path) as src:
            assert src.driver == "JP2OpenJPEG"
            assert src.dtypes[0] == "uint8"
            assert src.count == 7


class TestComputePixelStatistics:
    """Tests for compute_pixel_statistics function."""

    def test_statistics_all_valid(self, tmp_path: Path) -> None:
        """Test statistics with all valid pixels."""
        input_path = tmp_path / "test_tile.tif"
        create_test_tiff(input_path, nodata_pct=0.0, valid_mask_value=1)

        stats = compute_pixel_statistics(input_path)

        height, width = 32, 32
        total_pixels = height * width
        assert stats["n_valid_initial"] == total_pixels
        assert stats["n_valid_final"] == total_pixels
        assert stats["discarded"] is False

    def test_statistics_some_nodata(self, tmp_path: Path) -> None:
        """Test statistics with some nodata pixels."""
        input_path = tmp_path / "test_tile.tif"
        create_test_tiff(input_path, nodata_pct=0.1, valid_mask_value=1)

        stats = compute_pixel_statistics(input_path)

        assert stats["n_valid_initial"] < 32 * 32
        assert stats["n_valid_final"] <= stats["n_valid_initial"]

    def test_statistics_discarded_above_threshold(self, tmp_path: Path) -> None:
        """Test that files with >=80% nodata are marked as discarded."""
        input_path = tmp_path / "test_tile.tif"
        create_test_tiff(input_path, nodata_pct=NODATA_THRESHOLD + 0.01)

        stats = compute_pixel_statistics(input_path)

        assert stats["discarded"] is True

    def test_statistics_not_discarded_below_threshold(self, tmp_path: Path) -> None:
        """Test that files with <80% nodata are not marked as discarded."""
        input_path = tmp_path / "test_tile.tif"
        create_test_tiff(input_path, nodata_pct=NODATA_THRESHOLD - 0.01)

        stats = compute_pixel_statistics(input_path)

        assert stats["discarded"] is False


class TestProcessFile:
    """Tests for process_file function."""

    def test_process_file_compresses_and_returns_stats(self, tmp_path: Path) -> None:
        """Test that process_file compresses and returns statistics."""
        input_path = tmp_path / "075W_12N_1017.tif"
        create_test_tiff(input_path, width=32, height=32)

        tile_id = "075W_12N:1017"
        result = process_file(input_path, tile_id, quality=50)

        assert result is not None
        assert not input_path.exists()
        assert Path(result["path"]).exists()
        assert result["id"] == tile_id
        assert result["discarded"] is False

    def test_process_file_discards_low_quality(self, tmp_path: Path) -> None:
        """Test that process_file marks as discarded for files with too much nodata."""
        input_path = tmp_path / "075W_12N_1017.tif"
        create_test_tiff(input_path, nodata_pct=NODATA_THRESHOLD + 0.05)

        tile_id = "075W_12N:1017"
        result = process_file(input_path, tile_id, quality=50)

        assert result is not None
        assert result["discarded"] is True
        assert not input_path.exists()

    def test_process_file_records_compressed_size(self, tmp_path: Path) -> None:
        """Test that compressed size is recorded in results."""
        input_path = tmp_path / "075W_12N_1017.tif"
        create_test_tiff(input_path, width=64, height=64)

        tile_id = "075W_12N:1017"
        result = process_file(input_path, tile_id, quality=50)

        assert result is not None
        assert result["compressed_size_bytes"] is not None
        assert result["compressed_size_bytes"] > 0
