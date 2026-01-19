import pytest
from shapely import box
from shapely.geometry import Polygon

from lsatfetch.tile import (
    Tile,
    generate_all_tiles,
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
