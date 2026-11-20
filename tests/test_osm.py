"""OpenStreetMap paths, run offline against a small bundled OSM extract (© OpenStreetMap contributors, ODbL)."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest

ox = pytest.importorskip("osmnx")

import fttxplan  # noqa: E402
from fttxplan.cli import main  # noqa: E402

XML = Path(__file__).parent / "data" / "west_oakland.osm.bz2"


@pytest.fixture
def offline_osm(monkeypatch):
    graph = ox.graph_from_xml(XML)

    def fake_graph(*args, **kwargs):
        return graph

    def fake_buildings(*args, **kwargs):
        edges = ox.graph_to_gdfs(graph, nodes=False).to_crs(32610)
        rng = np.random.default_rng(0)
        pts = [g.interpolate(rng.uniform(0, g.length)) for g in edges.geometry for _ in range(3)]
        offset = gpd.GeoSeries(pts, crs=32610).translate(15, 15)
        return gpd.GeoDataFrame({"building": ["yes"] * len(offset)}, geometry=offset.buffer(7), crs=32610).to_crs(4326)

    for name in ("graph_from_place", "graph_from_point", "graph_from_bbox"):
        monkeypatch.setattr(ox, name, fake_graph)
    for name in ("features_from_place", "features_from_point"):
        monkeypatch.setattr(ox, name, fake_buildings)


def test_from_osm(offline_osm):
    net = fttxplan.RoadNetwork.from_osm("West Oakland, California")
    assert net.total_length > 5000
    assert not net.crs.is_geographic


def test_cli_osm(offline_osm, tmp_path):
    assert main(["osm", "--point", "37.81,-122.30", "--dist", "500", "-o", str(tmp_path), "--no-map"]) == 0
    assert (tmp_path / "design.gpkg").exists()
    assert "PON ports" in (tmp_path / "report.txt").read_text()
