import geopandas as gpd
import networkx as nx
import pytest
from shapely.geometry import LineString, Point

from fttxplan import RoadNetwork

CRS = "EPSG:32643"


def lines(*coords):
    return gpd.GeoDataFrame(geometry=[LineString(c) for c in coords], crs=CRS)


def test_crossing_lines_are_noded():
    net = RoadNetwork.from_lines(lines([(0, 0), (100, 0)], [(50, -50), (50, 50)]))
    assert net.graph.number_of_nodes() == 5
    assert net.graph.number_of_edges() == 4
    assert net.total_length == pytest.approx(200)


def test_geographic_input_is_projected():
    roads = gpd.GeoDataFrame(geometry=[LineString([(73.05, 33.70), (73.06, 33.70)])], crs=4326)
    net = RoadNetwork.from_lines(roads)
    assert not net.crs.is_geographic
    assert 900 < net.total_length < 950  # ~0.01 degree of longitude at 33.7N


def test_small_islands_are_dropped():
    net = RoadNetwork.from_lines(lines([(0, 0), (100, 0), (200, 0)], [(1000, 1000), (1010, 1000)]))
    assert nx.is_connected(net.graph)
    assert net.dropped_nodes == 2


def test_closed_ring_survives():
    ring = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
    net = RoadNetwork.from_lines(lines(ring, [(0, 0), (-50, 0)]))
    assert net.total_length == pytest.approx(450)


def test_attach_splits_edges_and_keeps_length():
    net = RoadNetwork.from_lines(lines([(0, 0), (100, 0)]))
    before = net.total_length
    nodes, offsets = net.attach([Point(30, 10), Point(70, -5), Point(30, 20), Point(0.2, 3)])
    assert net.total_length == pytest.approx(before)
    assert nodes[0] == nodes[2]  # same projection, same node
    assert list(offsets.round(3)) == [10, 5, 20, 3]
    assert net.xy(nodes[1]) == pytest.approx((70, 0))
    assert net.graph.degree(nodes[3]) == 1  # reused the end node instead of a sliver edge


def test_path_geometry():
    net = RoadNetwork.from_lines(lines([(0, 0), (100, 0), (100, 100)]))
    a, _ = net.attach([Point(0, 0)])
    b, _ = net.attach([Point(100, 100)])
    dist, paths = net.shortest_paths(int(a[0]))
    assert dist[int(b[0])] == pytest.approx(200)
    assert net.path_geometry(paths[int(b[0])]).length == pytest.approx(200)


def test_missing_crs():
    with pytest.raises(ValueError):
        RoadNetwork.from_lines([LineString([(0, 0), (1, 1)])])
