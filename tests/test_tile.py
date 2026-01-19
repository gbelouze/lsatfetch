from datetime import date

import pytest
from shapely import box
from shapely.geometry import Polygon

from lsatfetch.tile import (
    Period,
    Tile,
    generate_all_tiles,
    time_indices_for_range,
    tiles_intersecting,
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
    for tile_id in tiles:
        assert isinstance(tile_id, str)
        assert "_" in tile_id


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
    """Test that returned tile IDs have correct format."""
    aoi = box(2, 48, 3, 49)
    tiles = tiles_intersecting(aoi)
    # This bbox spans tiles 47N-49N and 001E-003E, so 9 tiles
    assert len(tiles) == 9
    for tile_id in tiles:
        # Format: LON_NAME_LAT_NAME
        parts = tile_id.split("_")
        assert len(parts) == 2
        assert parts[0][-1] in "EW"
        assert parts[1][-1] in "NS"


class TestPeriod:
    """Tests for the Period class."""

    def test_n_calculation(self) -> None:
        """Test that n is calculated correctly."""
        p = Period(year=2024, interval=1)
        assert p.n == (2024 - 1980) * 23 + 1

    def test_from_n(self) -> None:
        """Test conversion from n to Period."""
        p = Period.from_n(1013)
        assert p.year == 2024
        assert p.interval == 1

    def test_from_n_boundary(self) -> None:
        """Test conversion at year boundary."""
        p = Period.from_n(1012)
        assert p.year == 2023
        assert p.interval == 23

    def test_from_date(self) -> None:
        """Test finding interval for a date."""
        p = Period.from_date(date(2024, 3, 15))
        assert p.year == 2024
        # March 15 is day 75, interval = (75-1)//16 + 1 = 5
        assert p.interval == 5

    def test_start_date(self) -> None:
        """Test start_date calculation."""
        p = Period(year=2024, interval=1)
        assert p.start_date() == date(2024, 1, 1)

    def test_end_date(self) -> None:
        """Test end_date calculation (16 days inclusive)."""
        p = Period(year=2024, interval=1)
        assert p.end_date() == date(2024, 1, 16)

    def test_end_date_last_interval(self) -> None:
        """Test end_date for last interval of year."""
        p = Period(year=2024, interval=23)
        # Interval 23 starts on day 352 (Dec 18 in leap year 2024)
        # and spans 16 days, ending Jan 2, 2025
        assert p.end_date() == date(2025, 1, 2)

    def test_covers_true(self) -> None:
        """Test date coverage check - inside interval."""
        p = Period(year=2024, interval=1)
        assert p.covers(date(2024, 1, 1))
        assert p.covers(date(2024, 1, 8))
        assert p.covers(date(2024, 1, 16))

    def test_covers_false(self) -> None:
        """Test date coverage check - outside interval."""
        p = Period(year=2024, interval=1)
        assert not p.covers(date(2023, 12, 31))
        assert not p.covers(date(2024, 1, 17))


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


class TestTileWithPeriod:
    """Tests for Tile with Period."""

    def test_s3_key_with_period(self) -> None:
        """Test s3_key generation with period."""
        ti = Period(year=2024, interval=5)
        tile = Tile(lat_name="12N", lon_name="075W", period=ti)
        assert tile.s3_key == "12N/075W_12N/1017.tif"

    def test_s3_key_without_period(self) -> None:
        """Test s3_key generation without period."""
        tile = Tile(lat_name="12N", lon_name="075W")
        assert tile.s3_key == "12N/075W_12N/"

    def test_tile_equality_with_period(self) -> None:
        """Test equality when period differs."""
        tile1 = Tile(lat_name="12N", lon_name="075W", period=None)
        tile2 = Tile(lat_name="12N", lon_name="075W", period=None)
        tile3 = Tile(lat_name="12N", lon_name="075W", period=Period(2024, 1))
        assert tile1 == tile2
        assert tile1 != tile3
