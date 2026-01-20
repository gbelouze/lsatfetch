from dataclasses import dataclass
from datetime import date, timedelta

from shapely import box
from shapely.geometry import Polygon

__all__ = [
    "Tile",
    "Period",
    "generate_all_tiles",
    "tiles_intersecting",
    "time_indices_for_range",
    "tile_s3_key",
]


@dataclass(frozen=True)
class Period:
    """
    Represents a 16-day interval within a year.

    Attributes
    ----------
    year : int
        Year of the interval (e.g., 2024).
    interval : int
        Interval number within the year (1-23).
    """

    year: int
    interval: int

    def __post_init__(self) -> None:
        if not self.year >= 1980:
            msg = f"year must be >= 1980, got {self.year}"
            raise ValueError(msg)
        if not 1 <= self.interval <= 23:
            msg = f"interval must be 1-23, got {self.interval}"
            raise ValueError(msg)

    @property
    def n(self) -> int:
        """
        Filename integer for this interval.

        Returns
        -------
        int
            The n value used in filenames (n.tif).
        """
        return (self.year - 1980) * 23 + self.interval

    @classmethod
    def from_n(cls, n: int) -> "Period":
        """
        Create Period from filename integer.

        Parameters
        ----------
        n : int
            Filename integer (n.tif).

        Returns
        -------
        Period
            Corresponding Period.
        """
        year = 1980 + n // 23
        interval = n % 23
        if interval == 0:
            interval = 23
            year -= 1
        return cls(year=year, interval=interval)

    @classmethod
    def from_date(cls, d: date) -> "Period":
        """
        Find which 16-day interval contains the given date.

        Parameters
        ----------
        d : date
            Date to find interval for.

        Returns
        -------
        Period
            Period containing the date.
        """
        year = d.year
        day_of_year = d.timetuple().tm_yday
        interval = (day_of_year - 1) // 16 + 1
        interval = min(interval, 23)
        return cls(year=year, interval=interval)

    def start_date(self) -> date:
        """
        Start date of this 16-day interval.

        Returns
        -------
        date
            First day of the interval.
        """
        return date(self.year, 1, 1) + timedelta(days=(self.interval - 1) * 16)

    def end_date(self) -> date:
        """
        End date of this 16-day interval (inclusive).

        Returns
        -------
        date
            Last day of the interval.
        """
        start = self.start_date()
        return start + timedelta(days=15)

    def covers(self, d: date) -> bool:
        """
        Check if this interval covers the given date.

        Parameters
        ----------
        d : date
            Date to check.

        Returns
        -------
        bool
            True if the date falls within this interval.
        """
        return self.start_date() <= d <= self.end_date()


def time_indices_for_range(start: date, end: date) -> list[Period]:
    """
    Generate all Period intervals that intersect [start, end].

    Parameters
    ----------
    start : date
        Start date (inclusive).
    end : date
        End date (inclusive).

    Returns
    -------
    list[Period]
        All 16-day intervals that overlap with the date range.

    Raises
    ------
    ValueError
        If start > end.
    """
    if start > end:
        msg = "start date must be <= end date"
        raise ValueError(msg)

    start_period = Period.from_date(start)
    end_period = Period.from_date(end)
    return [Period.from_n(n) for n in range(start_period.n, end_period.n + 1)]


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


def tile_s3_key(tile: Tile, period: Period) -> str:
    """
    Generate S3 key for a tile at a specific period.

    Parameters
    ----------
    tile : Tile
        Spatial tile.
    period : Period
        Time period.

    Returns
    -------
    str
        S3 key (e.g., "12N/075W_12N/1017.tif").
    """
    tile_dir = f"{tile.lon_name}_{tile.lat_name}"
    return f"data/tiles/{tile.lat_name}/{tile_dir}/{period.n}.tif"


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


def tiles_intersecting(aoi: Polygon) -> list[Tile]:
    """
    Identify tiles that intersect with a given geometry.

    Parameters
    ----------
    aoi : shapely.geometry.Polygon
        Area of interest geometry.

    Returns
    -------
    list[Tile]
        List of tiles that intersect the geometry.
    """
    return [t for t in generate_all_tiles() if t.box.intersects(aoi)]
