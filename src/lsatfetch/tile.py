from dataclasses import dataclass

from shapely import box
from shapely.geometry import Polygon

__all__ = ["Tile", "generate_all_tiles", "tiles_intersecting"]


@dataclass(frozen=True)
class Tile:
    """
    A 1deg x 1deg Landsat ARD tile.

    Attributes
    ----------
    lat_name : str
        Latitude band name (e.g., "00N", "45S").
    lon_name : str
        Longitude band name (e.g., "001E", "120W").
    """

    lat_name: str
    lon_name: str

    @property
    def tile_id(self) -> str:
        """Full tile identifier (e.g., "075W_12N")."""
        return f"{self.lon_name}_{self.lat_name}"

    @property
    def lat(self) -> int:
        """
        Latitude of the tile's southern edge in degrees.

        Returns
        -------
        int
            Latitude value (positive for N, negative for S).
        """
        if self.lat_name.endswith("N"):
            return int(self.lat_name[:-1])
        return -int(self.lat_name[:-1])

    @property
    def lon(self) -> int:
        """
        Longitude of the tile's western edge in degrees.

        Returns
        -------
        int
            Longitude value (positive for E, negative for W).
        """
        if self.lon_name.endswith("E"):
            return int(self.lon_name[:-1])
        return -int(self.lon_name[:-1])

    @property
    def box(self) -> Polygon:
        """
        Bounding box of the tile in WGS84.

        Returns
        -------
        Polygon
            1deg x 1deg bounding box.
        """
        return box(self.lon, self.lat, self.lon + 1, self.lat + 1)


def _lat_names() -> list[str]:
    """Generate all valid latitude band names."""
    north = [f"{i:02d}N" for i in range(84)]
    south = [f"{i:02d}S" for i in range(1, 56)]
    return north + south


def _lon_names() -> list[str]:
    """Generate all valid longitude band names."""
    east = [f"{i:03d}E" for i in range(1, 181)]
    west = [f"{i:03d}W" for i in range(1, 181)]
    return east + west


def generate_all_tiles() -> list[Tile]:
    """
    Generate all possible Landsat ARD tiles.

    Returns
    -------
    list[Tile]
        List of all valid 1deg x 1deg tiles.
    """
    tiles = []
    for lat_name in _lat_names():
        for lon_name in _lon_names():
            tiles.append(Tile(lat_name=lat_name, lon_name=lon_name))
    return tiles


def tiles_intersecting(aoi: Polygon) -> list[str]:
    """
    Identify tiles that intersect with a given geometry.

    Parameters
    ----------
    aoi : shapely.geometry.Polygon
        Area of interest geometry.

    Returns
    -------
    list[str]
        List of tile IDs that intersect the geometry.
    """
    return [t.tile_id for t in generate_all_tiles() if t.box.intersects(aoi)]
