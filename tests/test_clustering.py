import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point

from fttxplan import RoadNetwork
from fttxplan.clustering import capacitated_clusters, network_clusters, network_medoid


@pytest.mark.parametrize("n, cap", [(1, 8), (8, 8), (9, 8), (100, 8), (257, 32), (50, 4)])
def test_capacity_is_respected(n, cap):
    xy = np.random.default_rng(0).uniform(0, 1000, (n, 2))
    labels = capacitated_clusters(xy, cap)
    counts = np.bincount(labels)
    assert counts.max() <= cap
    assert len(counts) == int(np.ceil(n / cap))
    assert (counts > 0).all()


def test_clusters_are_compact():
    rng = np.random.default_rng(1)
    blobs = np.vstack([rng.normal((0, 0), 5, (8, 2)), rng.normal((1000, 0), 5, (8, 2))])
    labels = capacitated_clusters(blobs, 8)
    assert len(set(labels[:8])) == 1 and len(set(labels[8:])) == 1


def test_medoid_on_a_line_is_the_middle():
    net = RoadNetwork.from_lines(gpd.GeoDataFrame(geometry=[LineString([(0, 0), (100, 0)])], crs=32643))
    nodes, _ = net.attach([Point(x, 1) for x in (10, 20, 50, 60, 95)])
    assert net.xy(network_medoid(net, nodes))[0] == pytest.approx(50)


def test_network_clusters_respect_road_distance():
    # two streets that are close in a straight line but only connected far away
    roads = gpd.GeoDataFrame(
        geometry=[
            LineString([(0, 0), (500, 0)]),
            LineString([(0, 30), (500, 30)]),
            LineString([(500, 0), (2000, 0), (2000, 30), (500, 30)]),
        ],
        crs=32643,
    )
    net = RoadNetwork.from_lines(roads)
    pts = [Point(x, 5) for x in range(20, 120, 25)] + [Point(x, 25) for x in range(20, 120, 25)]
    nodes, _ = net.attach(pts)
    labels, medoids = network_clusters(net, nodes, capacity=4)
    assert len(set(labels[:4])) == 1 and len(set(labels[4:])) == 1
    assert labels[0] != labels[4]
    assert len(medoids) == 2
