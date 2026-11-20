"""The planning pipeline: from roads, an OLT and premises to a complete FTTx design."""

from __future__ import annotations

import math
import time
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge

from .bom import build_bom
from .budget import max_reach_m, path_loss_db
from .clustering import network_clusters
from .config import DesignConfig, cable_size_for
from .network import RoadNetwork

TIERS = ("feeder", "distribution", "drop")


def _role(level: int, n_levels: int) -> str:
    if n_levels == 1:
        return "SPL"
    if level == 0:
        return "FDH"
    if level == n_levels - 1:
        return "FAT"
    return f"SPL{level + 1}"


def _read_points(data, crs=None) -> gpd.GeoDataFrame:
    if isinstance(data, (str, Path)):
        data = gpd.read_file(data)
    if isinstance(data, gpd.GeoSeries):
        data = gpd.GeoDataFrame(geometry=data)
    if not isinstance(data, gpd.GeoDataFrame):
        data = gpd.GeoDataFrame(geometry=list(data), crs=crs)
    if data.crs is None:
        if crs is None:
            raise ValueError("Premises have no CRS. Pass crs=... or set it on the GeoDataFrame.")
        data = data.set_crs(crs)
    data = data[data.geometry.notna() & ~data.geometry.is_empty].copy()
    if not (data.geom_type == "Point").all():
        data["geometry"] = data.geometry.representative_point()
    return data.reset_index(drop=True)


def _olt_point(olt, crs=None) -> gpd.GeoSeries:
    if isinstance(olt, (str, Path)):
        olt = gpd.read_file(olt)
    if isinstance(olt, gpd.GeoDataFrame):
        olt = olt.geometry
    if isinstance(olt, gpd.GeoSeries):
        if olt.crs is None:
            olt = olt.set_crs(crs or 4326)
        return olt.iloc[:1].representative_point()
    if isinstance(olt, (tuple, list)) and len(olt) == 2:
        olt = Point(olt)
    if isinstance(olt, Point):
        return gpd.GeoSeries([olt], crs=crs or 4326)
    raise TypeError("olt must be a Point, an (x, y) tuple, a GeoDataFrame/GeoSeries or a file path")


@dataclass
class Design:
    """A complete FTTx design. All layers are GeoDataFrames in the network's metric CRS."""

    config: DesignConfig
    network: RoadNetwork
    olt: gpd.GeoDataFrame
    splitters: gpd.GeoDataFrame
    premises: gpd.GeoDataFrame
    cables: gpd.GeoDataFrame
    drops: gpd.GeoDataFrame
    trench: gpd.GeoDataFrame
    summary_stats: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- reports
    def summary(self) -> dict:
        """Headline numbers of the design."""
        return dict(self.summary_stats)

    def bom(self, unit_costs: dict[str, float] | None = None) -> pd.DataFrame:
        """Bill of materials, optionally priced. See :func:`fttxplan.bom.build_bom`."""
        return build_bom(self, unit_costs)

    def loss_budget(self) -> pd.DataFrame:
        """Per premise optical loss budget, worst first."""
        cols = ["premise_id", "fat_id", "path_m", "loss_db", "margin_db", "budget_ok"]
        return pd.DataFrame(self.premises[cols]).sort_values("margin_db").reset_index(drop=True)

    def report(self) -> str:
        """A short plain text report."""
        s = self.summary_stats
        lines = [
            f"FTTx design  ({s['architecture']} split, {s['premises']} premises)",
            f"  PON ports         {s['pon_ports']}  ({s['olt_cards']} OLT card(s))",
            "  Splitters         "
            + ", ".join(f"{v} x {k}" for k, v in s["splitters"].items())
            + (f"  in {s['cabinets']} cabinet(s)" if len(self.config.split_levels) > 1 else ""),
            f"  Feeder cable      {s['feeder_km']:.2f} km",
            f"  Distribution      {s['distribution_km']:.2f} km",
            f"  Drop cable        {s['drop_km']:.2f} km",
            f"  Trench            {s['trench_km']:.2f} km  (sharing saves {s['trench_saving_pct']:.0f}% vs separate routes)",
            f"  Longest path      {s['max_path_m']:.0f} m  (reach limit {s['reach_limit_m']:.0f} m)",
            f"  Worst margin      {s['worst_margin_db']:.2f} dB  "
            f"({s['budget_failures']} premises below the {self.config.safety_margin_db:g} dB margin)",
            f"  Long drops        {s['long_drops']}  (> {self.config.max_drop_m:g} m from a road)",
            f"  Computed in       {s['runtime_s']:.1f} s",
        ]
        return "\n".join(lines)

    # ---------------------------------------------------------------- exports
    def layers(self) -> dict[str, gpd.GeoDataFrame]:
        return {
            "olt": self.olt,
            "splitters": self.splitters,
            "premises": self.premises,
            "cables": self.cables,
            "drops": self.drops,
            "trench": self.trench,
        }

    def to_gpkg(self, path) -> Path:
        from .io import to_gpkg

        return to_gpkg(self, path)

    def to_kml(self, path) -> Path:
        from .io import to_kml

        return to_kml(self, path)

    def to_geojson(self, folder) -> list[Path]:
        from .io import to_geojson

        return to_geojson(self, folder)

    def plot(self, **kwargs):
        from .plot import plot_design

        return plot_design(self, **kwargs)

    def explore(self, **kwargs):
        from .plot import explore_design

        return explore_design(self, **kwargs)


def plan(
    roads,
    olt,
    premises,
    config: DesignConfig | None = None,
    *,
    crs=None,
    id_column: str | None = None,
    **overrides,
) -> Design:
    """Design an FTTx network.

    Parameters
    ----------
    roads:
        Road centrelines (GeoDataFrame, file path) or a ready :class:`RoadNetwork`.
    olt:
        Location of the OLT / central office: a shapely Point, an ``(x, y)`` tuple,
        a GeoDataFrame or a file. Plain points and tuples are read as longitude/latitude
        unless ``crs`` is given.
    premises:
        Homes or buildings to connect (points or polygons; polygons are reduced to a point).
    config:
        A :class:`DesignConfig`. Keyword ``overrides`` change single fields, for example
        ``plan(..., split_levels="1:32", spare_ratio=0.3)``.
    id_column:
        Column in ``premises`` holding an identifier. Defaults to ``premise_id`` when present.
    """
    t0 = time.perf_counter()
    cfg = config or DesignConfig()
    if overrides:
        cfg = cfg.with_(**overrides)

    if isinstance(roads, RoadNetwork):
        net = RoadNetwork(roads.graph.copy(), roads.crs)
    else:
        net = RoadNetwork.from_lines(roads, crs=crs, snap_tolerance=cfg.snap_tolerance_m)

    prem = _read_points(premises, crs).to_crs(net.crs)
    if len(prem) == 0:
        raise ValueError("No premises to connect.")
    id_column = id_column or ("premise_id" if "premise_id" in prem.columns else None)
    prem["premise_id"] = prem[id_column].astype(str) if id_column else [f"P{i + 1:05d}" for i in range(len(prem))]
    olt_geom = _olt_point(olt, crs).to_crs(net.crs).iloc[0]

    nodes, offsets = net.attach([olt_geom, *prem.geometry])
    olt_node, olt_off = int(nodes[0]), float(offsets[0])
    p_nodes, p_off = nodes[1:].astype(int), offsets[1:]

    # ---------------------------------------------------- splitter hierarchy
    levels = cfg.split_levels
    n_levels = len(levels)
    sp_rows: list[dict] = []
    by_level: dict[int, list[int]] = {}  # level -> row indices into sp_rows
    item_nodes = p_nodes
    for lvl in reversed(range(n_levels)):
        cap = levels[lvl]
        role = _role(lvl, n_levels)
        rows = []
        if lvl == 0 and n_levels > 1 and cfg.cabinet_size > 1:
            # first-level splitters live together in FDH cabinets: place cabinets, then fill them
            labels, medoids = network_clusters(net, item_nodes, cap * cfg.cabinet_size, seed=cfg.seed + lvl, radius=cfg.placement_radius_m)
            for c in range(labels.max() + 1):
                members = np.flatnonzero(labels == c)
                node = int(medoids[c])
                cx, cy = net.xy(node)
                pts = np.array([net.xy(int(m)) for m in item_nodes[members]])
                members = members[np.argsort(np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx))]  # neighbours share a splitter
                cab = f"{role}-{c + 1:02d}"
                for j in range(0, len(members), cap):
                    sp_rows.append(
                        {
                            "splitter_id": f"{cab}/S{j // cap + 1}",
                            "role": role,
                            "level": lvl,
                            "ratio": cap,
                            "node": node,
                            "children": members[j : j + cap],
                            "parent_id": None,
                            "cabinet_id": cab,
                        }
                    )
                    rows.append(len(sp_rows) - 1)
        else:
            labels, medoids = network_clusters(net, item_nodes, cap, seed=cfg.seed + lvl, radius=cfg.placement_radius_m)
            for c in range(labels.max() + 1):
                members = np.flatnonzero(labels == c)
                sid = f"{role}-{c + 1:03d}"
                sp_rows.append(
                    {
                        "splitter_id": sid,
                        "role": role,
                        "level": lvl,
                        "ratio": cap,
                        "node": int(medoids[c]),
                        "children": members,
                        "parent_id": None,
                        "cabinet_id": sid if lvl == 0 else None,
                    }
                )
                rows.append(len(sp_rows) - 1)
        by_level[lvl] = rows
        item_nodes = np.array([sp_rows[r]["node"] for r in rows])

    # ---------------------------------------------------------------- routing
    fibres: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: dict.fromkeys(TIERS, 0))
    naive_m = 0.0

    def route(src: int, dsts, tier: str):
        sx, sy = net.xy(src)
        reach = max((np.hypot(*(np.array(net.xy(int(d))) - (sx, sy))) for d in dsts), default=0.0)
        out = net.paths_from(src, dsts, limit=3 * reach + 500)
        for _, p in out:
            for a, b in zip(p, p[1:]):
                fibres[(a, b) if a < b else (b, a)][tier] += 1
        return out

    upstream = {}  # splitter row -> cable metres from the OLT
    top = by_level[0]
    for r, (d, _) in zip(top, route(olt_node, [sp_rows[r]["node"] for r in top], "feeder")):
        sp_rows[r]["parent_id"] = "OLT"
        sp_rows[r]["link_m"] = d
        upstream[r] = olt_off + d
        naive_m += d
    for lvl in range(n_levels - 1):
        children_rows = by_level[lvl + 1]
        for r in by_level[lvl]:
            kids = [children_rows[i] for i in sp_rows[r]["children"]]
            for k, (d, _) in zip(kids, route(sp_rows[r]["node"], [sp_rows[k]["node"] for k in kids], "distribution")):
                sp_rows[k]["parent_id"] = sp_rows[r]["splitter_id"]
                sp_rows[k]["link_m"] = d
                upstream[k] = upstream[r] + d
                naive_m += d

    # drops, from the last level splitters to every premise
    n = len(prem)
    fat_of = np.empty(n, dtype=object)
    road_m = np.zeros(n)
    drop_geoms: list = [None] * n
    for r in by_level[n_levels - 1]:
        kids = sp_rows[r]["children"]
        for i, (d, p) in zip(kids, route(sp_rows[r]["node"], p_nodes[kids], "drop")):
            fat_of[i] = r
            road_m[i] = d
            naive_m += d
            tail = LineString([net.xy(int(p_nodes[i])), prem.geometry.iloc[i].coords[0]]) if p_off[i] > 0.01 else None
            parts = [net.graph[a][b]["geometry"] for a, b in zip(p, p[1:])] + ([tail] if tail else [])
            xy0 = net.xy(int(p_nodes[i]))
            drop_geoms[i] = linemerge(MultiLineString(parts)) if parts else LineString([xy0, xy0])

    # trace each premise back to the top so every level's id is known
    parent_row = {r: None for r in range(len(sp_rows))}
    id_to_row = {s["splitter_id"]: r for r, s in enumerate(sp_rows)}
    for r, s in enumerate(sp_rows):
        if s["parent_id"] not in (None, "OLT"):
            parent_row[r] = id_to_row[s["parent_id"]]

    # ----------------------------------------------------------------- layers
    path_m = np.array([upstream[fat_of[i]] for i in range(n)]) + road_m + p_off
    loss = path_loss_db(path_m, cfg)
    margin = cfg.budget_db - loss
    prem["fat_id"] = [sp_rows[r]["splitter_id"] for r in fat_of]
    if n_levels > 1:
        top_of = []
        for r in fat_of:
            while parent_row[r] is not None:
                r = parent_row[r]
            top_of.append(sp_rows[r]["cabinet_id"])
        prem["fdh_id"] = top_of
    prem["attach_m"] = p_off.round(1)
    prem["drop_road_m"] = road_m.round(1)
    prem["drop_total_m"] = (road_m + p_off).round(1)
    prem["path_m"] = path_m.round(1)
    prem["loss_db"] = loss.round(2)
    prem["margin_db"] = margin.round(2)
    prem["budget_ok"] = margin >= cfg.safety_margin_db
    prem["long_drop"] = p_off > cfg.max_drop_m

    splitters = (
        gpd.GeoDataFrame(
            [
                {
                    "splitter_id": s["splitter_id"],
                    "cabinet_id": s.get("cabinet_id"),
                    "role": s["role"],
                    "level": s["level"],
                    "ratio": s["ratio"],
                    "parent_id": s["parent_id"],
                    "ports_used": len(s["children"]),
                    "utilisation": round(len(s["children"]) / s["ratio"], 2),
                    "link_m": round(s.get("link_m", 0.0), 1),
                    "upstream_m": round(upstream[r], 1),
                    "node": s["node"],
                    "geometry": net.point(s["node"]),
                }
                for r, s in enumerate(sp_rows)
            ],
            geometry="geometry",
            crs=net.crs,
        )
        .sort_values(["level", "splitter_id"])
        .reset_index(drop=True)
    )

    cable_rows = []
    for (a, b), counts in fibres.items():
        e = net.graph[a][b]
        for tier in TIERS:
            used = counts[tier]
            if not used:
                continue
            if tier == "drop":
                size, n_cab, required = 1, used, used
            else:
                required = math.ceil(used * (1 + cfg.spare_ratio))
                size, n_cab = cable_size_for(required)
            cable_rows.append(
                {
                    "tier": tier,
                    "fibres_used": used,
                    "fibres_required": required,
                    "cable_size": size,
                    "n_cables": n_cab,
                    "length_m": round(e["length"], 2),
                    "geometry": e["geometry"],
                }
            )
    cables = gpd.GeoDataFrame(cable_rows, geometry="geometry", crs=net.crs)

    trench_rows = [
        {
            "length_m": round(net.graph[a][b]["length"], 2),
            "feeder_fibres": c["feeder"],
            "distribution_fibres": c["distribution"],
            "drop_cables": c["drop"],
            "geometry": net.graph[a][b]["geometry"],
        }
        for (a, b), c in fibres.items()
    ]
    trench = gpd.GeoDataFrame(trench_rows, geometry="geometry", crs=net.crs)
    trench_m = float(trench.length_m.sum()) if len(trench) else 0.0

    drops = gpd.GeoDataFrame(
        {"premise_id": prem["premise_id"], "fat_id": prem["fat_id"], "length_m": prem["drop_total_m"]},
        geometry=drop_geoms,
        crs=net.crs,
    )

    pon_ports = len(by_level[0])
    olt_gdf = gpd.GeoDataFrame(
        {"name": ["OLT"], "pon_ports": [pon_ports], "cards": [math.ceil(pon_ports / cfg.olt_ports_per_card)]},
        geometry=[olt_geom],
        crs=net.crs,
    )

    def km(tier):
        sub = cables[cables.tier == tier] if len(cables) else cables
        return float((sub.length_m * sub.n_cables).sum()) / 1000 if tier != "drop" else float(prem.drop_total_m.sum()) / 1000

    stats = {
        "architecture": " x ".join(f"1:{r}" for r in levels) + (f" (1:{cfg.total_split})" if n_levels > 1 else ""),
        "premises": n,
        "pon_ports": pon_ports,
        "olt_cards": math.ceil(pon_ports / cfg.olt_ports_per_card),
        "splitters": {f"1:{r} {_role(lvl, n_levels)}": len(by_level[lvl]) for lvl, r in enumerate(levels)},
        "cabinets": len({sp_rows[r]["node"] for r in by_level[0]}),
        "avg_port_utilisation": round(n / (pon_ports * cfg.total_split), 3),
        "feeder_km": round(km("feeder"), 3),
        "distribution_km": round(km("distribution"), 3),
        "drop_km": round(km("drop"), 3),
        "trench_m": trench_m,
        "trench_km": round(trench_m / 1000, 3),
        "trench_saving_pct": round(100 * (1 - trench_m / naive_m), 1) if naive_m else 0.0,
        "max_path_m": float(path_m.max()),
        "mean_path_m": float(path_m.mean()),
        "reach_limit_m": round(max_reach_m(cfg)),
        "worst_margin_db": float(margin.min()),
        "budget_failures": int((margin < cfg.safety_margin_db).sum()),
        "long_drops": int((p_off > cfg.max_drop_m).sum()),
        "road_km": round(net.total_length / 1000, 3),
        "crs": str(net.crs),
        "runtime_s": time.perf_counter() - t0,
    }
    if stats["budget_failures"]:
        warnings.warn(f"{stats['budget_failures']} premises exceed the optical budget margin; see Design.loss_budget()", stacklevel=2)
    return Design(cfg, net, olt_gdf, splitters, prem, cables, drops, trench, stats)
