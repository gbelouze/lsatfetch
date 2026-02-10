from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from omegaconf import OmegaConf

if TYPE_CHECKING:
    AOIType = Literal["bbox", "vector", "country"]
    CountryType = str | list[str] | None
else:
    AOIType = str
    CountryType = Any

__all__ = [
    "AOIConfig",
    "TimeRangeConfig",
    "Config",
    "load",
]


@dataclass
class AOIConfig:
    """
    Area of Interest configuration.

    Attributes
    ----------
    type : str
        Type of AOI specification: 'bbox' or 'vector'. Defaults to 'bbox'.
    left : float | None
        Left boundary of bounding box. Only used when type is 'bbox'.
    bottom : float | None
        Bottom boundary of bounding box. Only used when type is 'bbox'.
    right : float | None
        Right boundary of bounding box. Only used when type is 'bbox'.
    top : float | None
        Top boundary of bounding box. Only used when type is 'bbox'.
    crs : str
        CRS of the bounding box (e.g., 'EPSG:4326'). Defaults to 'EPSG:4326'.
    vector : Path | None
        Path to vector file containing AOI shapes.
        Only used when type is 'vector'. Defaults to None.
    country : str | list[str] | None
        Country name(s) to load borders for.
        Only used when type is 'country'. Defaults to None.
    """

    type: str = "bbox"
    left: float | None = None
    bottom: float | None = None
    right: float | None = None
    top: float | None = None
    crs: str = "EPSG:4326"
    vector: Path | None = None
    country: CountryType = None

    def __post_init__(self) -> None:
        if self.type not in ("bbox", "vector", "country"):
            msg = f"type must be 'bbox', 'vector', or 'country', got '{self.type}'"
            raise ValueError(msg)
        if self.type == "bbox" and any(
            v is None for v in (self.left, self.bottom, self.right, self.top)
        ):
            msg = "left, bottom, right, and top must be provided when type is 'bbox'"
            raise ValueError(msg)
        if self.type == "vector" and self.vector is None:
            msg = "vector must be provided when type is 'vector'"
            raise ValueError(msg)
        if self.type == "country" and self.country is None:
            msg = "country must be provided when type is 'country'"
            raise ValueError(msg)


@dataclass
class TimeRangeConfig:
    """
    Time range configuration for filtering Landsat data.

    Attributes
    ----------
    start : str | None
        Start date in 'YYYY-MM-DD' format. Defaults to None.
    end : str | None
        End date in 'YYYY-MM-DD' format. Defaults to None.
    """

    start: str | None = None
    end: str | None = None


@dataclass
class Config:
    """
    Main configuration for Landsat dataset creation.

    Attributes
    ----------
    aoi : AOIConfig
        Area of Interest configuration.
    time_range : TimeRangeConfig
        Time range configuration.
    output_dir : Path
        Directory where the dataset will be created.
    """

    aoi: AOIConfig
    time_range: TimeRangeConfig
    output_dir: Path

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir).expanduser().absolute()


def load(path: Path) -> Config:
    """
    Load and validate a configuration from a YAML file.

    Parameters
    ----------
    path : Path
        Path to the configuration YAML file.

    Returns
    -------
    Config
        Fully validated configuration object.
    """
    from_yaml = OmegaConf.load(path)
    structured = OmegaConf.structured(Config)
    merged = OmegaConf.merge(structured, from_yaml)
    OmegaConf.resolve(merged)
    return OmegaConf.to_object(merged)  # type: ignore[no-any-return]
