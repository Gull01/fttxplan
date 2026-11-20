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


@pytest.fixture
def point_only_place(offline_osm, monkeypatch):
    """A place that OSM only has as a point, like most city sectors."""

    def no_outline(*args, **kwargs):
        raise TypeError("Nominatim did not geocode query to a geometry of type (Multi)Polygon.")

    calls = []
    monkeypatch.setattr(ox, "geocode_to_gdf", no_outline)
    monkeypatch.setattr(ox, "graph_from_place", no_outline)
    monkeypatch.setattr(ox, "features_from_place", no_outline)
    monkeypatch.setattr(ox, "geocode", lambda q: calls.append(q) or (37.81, -122.30))
    return calls


def test_from_osm(offline_osm):
    net = fttxplan.RoadNetwork.from_osm("West Oakland, California")
    assert net.total_length > 5000
    assert not net.crs.is_geographic


def test_cli_osm(offline_osm, tmp_path):
    assert main(["osm", "--point", "37.81,-122.30", "--dist", "500", "-o", str(tmp_path), "--no-map"]) == 0
    assert (tmp_path / "design.gpkg").exists()
    assert "PON ports" in (tmp_path / "report.txt").read_text()


def test_place_without_outline_falls_back_to_radius(point_only_place, tmp_path):
    net = fttxplan.RoadNetwork.from_osm("F-7, Islamabad, Pakistan")
    assert net.total_length > 5000
    assert main(["osm", "--place", "F-7, Islamabad, Pakistan", "-o", str(tmp_path), "--no-map"]) == 0
    assert (tmp_path / "design.gpkg").exists()
    assert point_only_place == ["F-7, Islamabad, Pakistan"] * 2


def test_busy_server_is_retried_on_a_mirror(offline_osm, monkeypatch, capsys):
    monkeypatch.setattr("time.sleep", lambda s: None)
    from osmnx._errors import ResponseStatusCodeError

    from fttxplan import network

    graph = ox.graph_from_xml(XML)
    used = []

    def flaky(*args, **kwargs):
        used.append(ox.settings.overpass_url)
        if len(used) == 1:
            raise ResponseStatusCodeError("'overpass-api.de' responded: 502 Bad Gateway")
        return graph

    monkeypatch.setattr(ox, "graph_from_point", flaky)
    net = fttxplan.RoadNetwork.from_osm(point=(37.81, -122.30))
    assert net.total_length > 5000
    assert used == list(network.OVERPASS_SERVERS[:2])
    assert ox.settings.overpass_url == network.OVERPASS_SERVERS[0]  # restored afterwards
    assert "busy" in capsys.readouterr().out


def test_gives_up_with_a_clear_message(offline_osm, monkeypatch):
    from osmnx._errors import ResponseStatusCodeError

    def always_busy(*args, **kwargs):
        raise ResponseStatusCodeError("502")

    monkeypatch.setattr(ox, "graph_from_point", always_busy)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert main(["osm", "--point", "37.81,-122.30", "--no-map"]) == 1
