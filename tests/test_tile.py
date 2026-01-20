from datetime import date
from pathlib import Path

import pytest
from shapely import box
from shapely.geometry import Polygon

from lsatfetch.tile import (
    Period,
    Tile,
    generate_all_tiles,
    tile_s3_key,
    tiles_intersecting,
    time_indices_for_range,
)


class TestTile:
    """Tests for the Tile class."""

    def test_tile_id_format(self) -> None:
        """Test that tile_id is formatted correctly."""
        tile = Tile(lat_name="12N", lon_name="075W")
        assert tile.tile_id == "075W_12N"

    def test_lat_positive(self) -> None:
        """Test latitude parsing for northern hemisphere."""
        tile = Tile(lat_name="45N", lon_name="090E")
        assert tile.lat == 45

    def test_lat_negative(self) -> None:
        """Test latitude parsing for southern hemisphere."""
        tile = Tile(lat_name="30S", lon_name="120W")
        assert tile.lat == -30

    def test_lon_positive(self) -> None:
        """Test longitude parsing for eastern hemisphere."""
        tile = Tile(lat_name="00N", lon_name="090E")
        assert tile.lon == 90

    def test_lon_negative(self) -> None:
        """Test longitude parsing for western hemisphere."""
        tile = Tile(lat_name="00N", lon_name="045W")
        assert tile.lon == -45

    def test_tile_box_extent(self) -> None:
        """Test that tile box is 1x1 degree."""
        tile = Tile(lat_name="10N", lon_name="20E")
        bbox = tile.box
        assert bbox.bounds == (20, 10, 21, 11)

    def test_tile_equality(self) -> None:
        """Test that frozen dataclass equality works."""
        tile1 = Tile(lat_name="12N", lon_name="075W")
        tile2 = Tile(lat_name="12N", lon_name="075W")
        assert tile1 == tile2

    def test_tile_hashable(self) -> None:
        """Test that Tile is hashable (frozen dataclass)."""
        tile = Tile(lat_name="12N", lon_name="075W")
        tiles_set = {tile}
        assert tile in tiles_set


class TestGenerateAllTiles:
    """Tests for generate_all_tiles function."""

    def test_total_tile_count(self) -> None:
        """Test that all possible tiles are generated."""
        tiles = generate_all_tiles()
        assert len(tiles) == 50040

    def test_north_lat_range(self) -> None:
        """Test northern latitude bands: 00N to 83N."""
        tiles = generate_all_tiles()
        lat_names = {t.lat_name for t in tiles if t.lat_name.endswith("N")}
        assert "00N" in lat_names
        assert "83N" in lat_names
        assert len([n for n in lat_names if n.endswith("N")]) == 84

    def test_south_lat_range(self) -> None:
        """Test southern latitude bands: 00S to 55S."""
        tiles = generate_all_tiles()
        lat_names = {t.lat_name for t in tiles if t.lat_name.endswith("S")}
        assert "00S" not in lat_names
        assert "01S" in lat_names
        assert "55S" in lat_names
        assert len([n for n in lat_names if n.endswith("S")]) == 55

    def test_lon_range_complete(self) -> None:
        """Test longitude bands: 001E to 180E and 001W to 180W."""
        tiles = generate_all_tiles()
        lon_names = {t.lon_name for t in tiles}
        assert "001E" in lon_names
        assert "180E" in lon_names
        assert "001W" in lon_names
        assert "180W" in lon_names
        assert len(lon_names) == 360


@pytest.mark.parametrize(
    ("left", "bottom", "right", "top", "expected_count"),
    [
        # France (roughly)
        (-5, 41, 10, 52, 208),
        # Paris area (spans 3x3 degree area, so 9 tiles)
        (2, 48, 3, 49, 9),
        # Small box at origin (intersects 2 tiles: 00N and 01S)
        (0, 0, 0.0001, 0.0001, 2),
        # Large area - continental US (roughly)
        (-130, 25, -65, 50, 1809),
        # Small box in Atlantic (intersects 4 tiles at -40, -40)
        (-40, -40, -39.999, -39.999, 4),
        # Entire world (all valid tiles, no ocean-only tiles)
        (-180, -90, 180, 90, 50040),
    ],
)
def test_tiles_intersecting_bbox(
    left: float,
    bottom: float,
    right: float,
    top: float,
    expected_count: int,
) -> None:
    """Test tile identification with various bounding boxes."""
    aoi = box(left, bottom, right, top)
    tiles = tiles_intersecting(aoi)
    assert len(tiles) == expected_count


@pytest.mark.parametrize(
    "geometry",
    [
        # Small polygon - triangle within one tile
        Polygon([(2, 48), (2.5, 48), (2.25, 48.5), (2, 48)]),
        # Irregular polygon spanning multiple tiles
        Polygon([(0, 0), (2, 0), (2, 2), (1, 3), (0, 2), (0, 0)]),
    ],
)
def test_tiles_intersecting_polygon(geometry: Polygon) -> None:
    """Test tile identification with arbitrary polygon geometries."""
    tiles = tiles_intersecting(geometry)
    assert len(tiles) >= 1
    for tile in tiles:
        assert isinstance(tile, Tile)
        assert "_" in tile.tile_id


def test_tiles_intersecting_returns_consistent_order() -> None:
    """Test that tiles are returned in a consistent, reproducible order."""
    aoi = box(-5, 41, 10, 52)
    tiles1 = tiles_intersecting(aoi)
    tiles2 = tiles_intersecting(aoi)
    assert tiles1 == tiles2
    # Verify deterministic order by checking multiple runs produce same result
    for _ in range(5):
        tiles = tiles_intersecting(aoi)
        assert tiles == tiles1


def test_tile_id_format_in_results() -> None:
    """Test that returned tiles have correct format."""
    aoi = box(2, 48, 3, 49)
    tiles = tiles_intersecting(aoi)
    # This bbox spans tiles 47N-49N and 001E-003E, so 9 tiles
    assert len(tiles) == 9
    for tile in tiles:
        # Format: LON_NAME_LAT_NAME
        parts = tile.tile_id.split("_")
        assert len(parts) == 2
        assert parts[0][-1] in "EW"
        assert parts[1][-1] in "NS"


class TestPeriod:
    """Tests for the Period class."""

    @pytest.mark.parametrize(
        ("n", "expected_year", "expected_interval"),
        [
            (1013, 2024, 1),  # First interval of 2024
            (1012, 2023, 23),  # Last interval of 2023
        ],
    )
    def test_from_n(self, n: int, expected_year: int, expected_interval: int) -> None:
        """Test conversion from n to Period."""
        p = Period.from_n(n)
        assert p.year == expected_year
        assert p.interval == expected_interval

    def test_n_calculation(self) -> None:
        """Test that n is calculated correctly."""
        p = Period(year=2024, interval=1)
        assert p.n == (2024 - 1980) * 23 + 1

    def test_from_date(self) -> None:
        """Test finding interval for a date."""
        p = Period.from_date(date(2024, 3, 15))
        assert p.year == 2024
        # March 15 is day 75, interval = (75-1)//16 + 1 = 5
        assert p.interval == 5

    @pytest.mark.parametrize(
        ("year", "interval", "expected_start"),
        [
            (2024, 1, date(2024, 1, 1)),
            (2024, 10, date(2024, 5, 24)),
        ],
    )
    def test_start_date(self, year: int, interval: int, expected_start: date) -> None:
        """Test start_date calculation."""
        p = Period(year=year, interval=interval)
        assert p.start_date() == expected_start

    @pytest.mark.parametrize(
        ("year", "interval", "expected_end"),
        [
            (2024, 1, date(2024, 1, 16)),
            (2024, 23, date(2025, 1, 2)),
        ],
    )
    def test_end_date(self, year: int, interval: int, expected_end: date) -> None:
        """Test end_date calculation (16 days inclusive)."""
        p = Period(year=year, interval=interval)
        assert p.end_date() == expected_end

    @pytest.mark.parametrize(
        ("d", "expected"),
        [
            (date(2024, 1, 1), True),
            (date(2024, 1, 8), True),
            (date(2024, 1, 16), True),
            (date(2023, 12, 31), False),
            (date(2024, 1, 17), False),
        ],
    )
    def test_covers(self, d: date, expected: bool) -> None:
        """Test date coverage check."""
        p = Period(year=2024, interval=1)
        assert p.covers(d) == expected


class TestPeriodsForRange:
    """Tests for time_indices_for_range function."""

    def test_single_interval(self) -> None:
        """Test range within single interval."""
        periods = time_indices_for_range(date(2024, 1, 1), date(2024, 1, 15))
        assert len(periods) == 1
        assert periods[0] == Period(year=2024, interval=1)

    def test_multiple_intervals_same_year(self) -> None:
        """Test range spanning multiple intervals in same year."""
        periods = time_indices_for_range(date(2024, 1, 1), date(2024, 3, 31))
        # Jan (1-16, 17-32, 33-48), Feb (49-64, 65-80), Mar (81-96, 97-112)
        # So intervals 1-6 (Jan 1 - Mar 15)
        assert len(periods) == 6

    def test_year_boundary(self) -> None:
        """Test range crossing year boundary."""
        periods = time_indices_for_range(date(2023, 12, 15), date(2024, 1, 15))
        # Dec 15 is in interval 22, Dec 15-31 covers intervals 22 and 23
        # Jan 1-15 is interval 1
        assert len(periods) == 3
        assert periods[0] == Period(year=2023, interval=22)
        assert periods[1] == Period(year=2023, interval=23)
        assert periods[2] == Period(year=2024, interval=1)

    def test_single_day(self) -> None:
        """Test range of single day."""
        periods = time_indices_for_range(date(2024, 6, 15), date(2024, 6, 15))
        # June 15 is day 167, interval = (167-1)//16 + 1 = 11
        assert len(periods) == 1
        assert periods[0].interval == 11

    def test_invalid_range(self) -> None:
        """Test that start > end raises ValueError."""
        with pytest.raises(ValueError):  # noqa: PT011
            time_indices_for_range(date(2024, 6, 15), date(2024, 1, 1))


@pytest.mark.parametrize(
    ("lat_name", "lon_name", "year", "interval", "expected_key"),
    [
        ("12N", "075W", 2024, 5, "data/tiles/12N/075W_12N/1017.tif"),
        ("00N", "001E", 2024, 1, "data/tiles/00N/001E_00N/1013.tif"),
        ("45N", "090W", 2023, 23, "data/tiles/45N/090W_45N/1012.tif"),
    ],
)
def test_tile_s3_key(
    lat_name: str, lon_name: str, year: int, interval: int, expected_key: str
) -> None:
    """Test that s3_key format is correct for various tiles and periods."""
    tile = Tile(lat_name=lat_name, lon_name=lon_name)
    period = Period(year=year, interval=interval)
    assert tile_s3_key(tile, period) == expected_key


class TestDownloadTile:
    """Tests for download_tile function."""

    @pytest.mark.parametrize(
        ("n", "exists"),
        [
            (740, True),  # File exists on S3
            (391, False),  # File does not exist
        ],
    )
    def test_download_tile(
        self, n: int, exists: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that download_tile downloads existing files and skips missing ones."""
        import boto3
        from moto import mock_aws

        from lsatfetch.core import download_tile

        tile = Tile(lat_name="45N", lon_name="003E")
        period = Period.from_n(n)
        s3_key = tile_s3_key(tile, period)

        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="glad.landsat.ard")

            def create_test_client(*args, **kwargs):
                return boto3.client("s3", region_name="us-east-1")

            monkeypatch.setattr("lsatfetch.core._get_s3_client", create_test_client)

            if exists:
                s3_client.put_object(
                    Bucket="glad.landsat.ard",
                    Key=s3_key,
                    Body=b"fake tile data",
                )

            result = download_tile(tile, period, tmp_path)

            if exists:
                assert result is not None
                assert result.exists()
                assert result.read_bytes() == b"fake tile data"
            else:
                assert result is None
