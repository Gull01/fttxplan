"""Bundled sample data and a synthetic town generator."""

from __future__ import annotations

from importlib.resources import files

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point

#: Suggested OLT (central office) site for the bundled demo area, as (lon, lat).
DEMO_OLT = (26.9431, 60.5258)


def demo_path():
    """Path to the bundled demo GeoPackage (layers ``roads`` and ``premises``)."""
    return files("fttxplan") / "data" / "finland_demo.gpkg"


def load_demo() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, Point]:
    """Real OpenStreetMap roads and building points for a ~2 x 2 km residential area in
    south-eastern Finland (the sample extract used by the pyrosm test suite).

    Returns ``(roads, premises, olt)`` in WGS 84. Data © OpenStreetMap contributors, ODbL.
    """
    p = str(demo_path())
    return gpd.read_file(p, layer="roads"), gpd.read_file(p, layer="premises"), Point(DEMO_OLT)


def synthetic_town(
    blocks: int = 4,
    block_m: float = 120.0,
    homes_per_side: int = 5,
    seed: int = 0,
    crs: str = "EPSG:32643",
    origin: tuple[float, float] = (330_000.0, 3_730_000.0),
):
    """A small grid town with slightly irregular streets and homes along both sides.

    Handy for tests and quick experiments. Default coordinates sit in UTM zone 43N
    (around Islamabad). Returns ``(roads, premises, olt_point)`` in ``crs``.
    """
    rng = np.random.default_rng(seed)
    x0, y0 = origin
    n = blocks + 1
    jx = rng.normal(0, block_m * 0.06, (n, n))
    jy = rng.normal(0, block_m * 0.06, (n, n))
    grid = [[(x0 + i * block_m + jx[i, j], y0 + j * block_m + jy[i, j]) for j in range(n)] for i in range(n)]
    roads = []
    for i in range(n):
        for j in range(n):
            if i + 1 < n:
                roads.append(LineString([grid[i][j], grid[i + 1][j]]))
            if j + 1 < n:
                roads.append(LineString([grid[i][j], grid[i][j + 1]]))
    homes = []
    for seg in roads:
        (ax, ay), (bx, by) = seg.coords
        dx, dy = bx - ax, by - ay
        L = np.hypot(dx, dy)
        nx_, ny_ = -dy / L, dx / L
        for k in range(homes_per_side):
            t = (k + 0.5) / homes_per_side
            for side in (-1, 1):
                off = rng.uniform(12, 25) * side
                homes.append(Point(ax + dx * t + nx_ * off, ay + dy * t + ny_ * off))
    roads_gdf = gpd.GeoDataFrame({"road_id": range(len(roads))}, geometry=roads, crs=crs)
    homes_gdf = gpd.GeoDataFrame({"premise_id": [f"H{i:04d}" for i in range(len(homes))]}, geometry=homes, crs=crs)
    olt = Point(grid[0][0][0] - 5, grid[0][0][1] - 5)
    return roads_gdf, homes_gdf, olt
