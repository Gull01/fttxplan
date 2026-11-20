import math
import warnings

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point

import fttxplan


def test_every_premise_is_connected(design, town):
    _, homes, _ = town
    p = design.premises
    assert len(p) == len(homes)
    assert p.fat_id.notna().all() and p.fdh_id.notna().all()
    assert set(p.premise_id) == set(homes.premise_id)


def test_splitter_ports_never_exceed_ratio(design):
    sp = design.splitters
    assert (sp.ports_used <= sp.ratio).all()
    fat_load = design.premises.fat_id.value_counts()
    assert fat_load.max() <= 8
    kids = sp[sp.level == 1].parent_id.value_counts()
    assert kids.max() <= 4


def test_pon_ports_and_cabinets(design):
    s = design.summary()
    n = s["premises"]
    assert s["pon_ports"] >= math.ceil(n / 32)
    assert s["pon_ports"] == (design.splitters.level == 0).sum()
    assert s["cabinets"] <= s["pon_ports"]
    assert design.splitters[design.splitters.level == 0].groupby("cabinet_id").size().max() <= design.config.cabinet_size


def test_feeder_fibres_leave_the_olt(design):
    """Every PON port's fibre starts at the OLT node: fibres on edges touching it add up."""
    net = design.network
    olt_node, _ = net.attach([design.olt.geometry.iloc[0]])
    olt_node = int(olt_node[0])
    feeders = design.cables[design.cables.tier == "feeder"]
    touching = feeders[feeders.geometry.apply(lambda g: Point(net.xy(olt_node)).distance(g) < 0.01)]
    at_olt = (design.splitters.level == 0) & (design.splitters.node == olt_node)
    assert touching.fibres_used.sum() == (design.splitters.level == 0).sum() - at_olt.sum()


def test_cables_are_big_enough(design):
    c = design.cables[design.cables.tier != "drop"]
    assert (c.cable_size * c.n_cables >= c.fibres_required).all()
    assert (c.fibres_required >= c.fibres_used).all()
    assert set(c.cable_size) <= set(fttxplan.CABLE_SIZES)


def test_budget_columns(design):
    p = design.premises
    assert (p.loss_db > design.config.splitter_loss_db).all()
    assert np.allclose(p.margin_db, design.config.budget_db - p.loss_db, atol=0.02)
    assert p.budget_ok.all()
    lb = design.loss_budget()
    assert lb.margin_db.is_monotonic_increasing


def test_trench_is_shared(design):
    s = design.summary()
    assert 0 < s["trench_km"] <= s["road_km"]
    assert s["trench_saving_pct"] > 0


def test_single_level_architecture(town):
    roads, homes, olt = town
    d = fttxplan.plan(roads, olt, homes, crs=roads.crs, split_levels="1:32")
    assert set(d.splitters.role) == {"SPL"}
    assert d.premises.fat_id.value_counts().max() <= 32
    assert "fdh_id" not in d.premises.columns
    assert d.summary()["pon_ports"] == len(d.splitters)


def test_results_are_reproducible(town):
    roads, homes, olt = town
    a = fttxplan.plan(roads, olt, homes, crs=roads.crs, seed=3)
    b = fttxplan.plan(roads, olt, homes, crs=roads.crs, seed=3)
    assert list(a.premises.fat_id) == list(b.premises.fat_id)
    assert a.summary()["trench_km"] == b.summary()["trench_km"]


def test_accepts_network_polygons_and_lonlat(town):
    roads, homes, olt = town
    net = fttxplan.RoadNetwork.from_lines(roads)
    buildings = homes.copy()
    buildings["geometry"] = homes.buffer(6)
    olt_ll = gpd.GeoSeries([olt], crs=roads.crs).to_crs(4326).iloc[0]
    d = fttxplan.plan(net, (olt_ll.x, olt_ll.y), buildings)
    assert len(d.premises) == len(homes)
    assert net.graph.number_of_nodes() < d.network.graph.number_of_nodes()  # caller's network untouched


def test_budget_failure_warns(town):
    roads, homes, olt = town
    with pytest.warns(UserWarning, match="optical budget"):
        d = fttxplan.plan(roads, olt, homes, crs=roads.crs, split_levels="1:64x1:2", budget_db=20)
    assert d.summary()["budget_failures"] == len(homes)


def test_bom(design):
    bom = design.bom()
    q = dict(zip(bom.item, bom.quantity))
    n = len(design.premises)
    assert q["ONT / ONU"] == n
    assert q["PLC splitter 1:8 (level 2)"] == (design.splitters.level == 1).sum()
    assert q["OLT PON port"] == design.summary()["pon_ports"]
    assert q["Drop cable 1F"] == pytest.approx(design.premises.drop_total_m.sum() * 1.1, rel=1e-3)
    priced = design.bom({"ONT / ONU": 25.0})
    assert priced.loc[priced.item == "ONT / ONU", "cost"].iloc[0] == 25.0 * n


def test_report_mentions_key_numbers(design):
    r = design.report()
    assert "PON ports" in r and "Trench" in r and str(len(design.premises)) in r


def test_no_warnings_on_normal_design(town):
    roads, homes, olt = town
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fttxplan.plan(roads, olt, homes, crs=roads.crs)
