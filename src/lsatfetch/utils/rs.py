import logging

import geopandas
import pooch
import shapely
from thefuzz import process

log = logging.getLogger(__name__)

COUNTRY_BORDERS_URL = (
    "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
    "world-administrative-boundaries/exports/geojson"
)


def load_country_filter_polygon(
    country: str | list[str] | None,
) -> shapely.Polygon | shapely.MultiPolygon | None:
    """
    Load the mainland shape of a country.

    Parameters
    ----------
    country : str | list[str] | None
        Country name(s) to load borders for, e.g. France. Can be a single country name (str),
        a list of country names (list[str]), or None.

    Returns
    -------
    shapely.Polygon | shapely.MultiPolygon | None
        The combined polygon(s) for the specified country(ies), or None if country
        is None or an empty list.
    """
    match country:
        case str():
            country = [country]
        case None | []:
            return None
        case list() if all(isinstance(x, str) for x in country):
            pass
        case _:
            raise TypeError(
                f"Unexpected type {type(country)} for country. "
                "Must be `str`, `list[str]` or `None`."
            )

    country_borders_path = pooch.retrieve(url=COUNTRY_BORDERS_URL, known_hash=None)
    log.debug(f"Country borders is downloaded to {country_borders_path}")
    country_borders = geopandas.read_file(country_borders_path)
    polygons = []
    for c in country:
        if c not in country_borders.name.values:
            best_match, _ = process.extractOne(c, country_borders.name.values)
            raise ValueError(f"Unknown country {c}. Did you mean {best_match} ?")
        borders = country_borders[country_borders.name == c].iloc[0].geometry
        polygons.append(borders)
    return shapely.ops.unary_union(polygons)
