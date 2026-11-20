"""Road network graph that fibre is routed along."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import shapely
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra as cs_dijkstra
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, substring, unary_union
from shapely.strtree import STRtree


def _iter_lines(geom) -> Iterable[LineString]:
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, LineString):
        yield geom
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            yield from _iter_lines(g)
    elif hasattr(geom, "boundary") and geom.geom_type in ("Polygon", "MultiPolygon"):
        yield from _iter_lines(geom.boundary)


def _as_geoseries(data, crs=None) -> gpd.GeoSeries:
    if isinstance(data, (str, Path)):
        data = gpd.read_file(data)
    if isinstance(data, gpd.GeoDataFrame):
        return data.geometry
    if isinstance(data, gpd.GeoSeries):
        return data if crs is None else data.set_crs(crs, allow_override=True)
    return gpd.GeoSeries(list(data), crs=crs)


class RoadNetwork:
    """An undirected road graph in a metric CRS.

    Nodes carry ``x`` and ``y``; edges carry ``length`` (metres), ``geometry`` (a LineString)
    and ``start`` (the node the geometry starts at). Build one with :meth:`from_lines`
    or :meth:`from_osm`.
    """

    def __init__(self, graph: nx.Graph, crs):
        self.graph = graph
        self.crs = crs
        self._next_id = max(graph.nodes, default=-1) + 1
        self.dropped_nodes = 0
        self._csr_cache = None

    def __repr__(self) -> str:
        km = sum(d["length"] for _, _, d in self.graph.edges(data=True)) / 1000
        return f"RoadNetwork({self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges, {km:.1f} km, crs={self.crs})"

    # ------------------------------------------------------------------ build
    @classmethod
    def from_lines(cls, roads, crs=None, snap_tolerance: float = 0.5, keep_largest: bool = True) -> RoadNetwork:
        """Build a network from road centrelines.

        ``roads`` may be a GeoDataFrame, GeoSeries, a list of LineStrings (with ``crs``) or a
        path to any file GeoPandas can read. Geographic coordinates are projected to the local
        UTM zone. Lines are noded at every intersection, and only the largest connected part
        is kept (unless ``keep_largest=False``).
        """
        gs = _as_geoseries(roads, crs)
        if gs.crs is None:
            raise ValueError("Road geometries have no CRS. Pass crs=... or set it on the GeoDataFrame.")
        if gs.crs.is_geographic:
            gs = gs.to_crs(gs.estimate_utm_crs())
        lines = [ln for geom in gs for ln in _iter_lines(geom)]
        lines = [shapely.set_precision(ln, snap_tolerance / 10) for ln in lines]
        lines = [ln for ln in lines if not ln.is_empty and ln.length > 0]
        if not lines:
            raise ValueError("No line geometries found in the road data.")
        noded = unary_union(lines)

        G = nx.Graph()
        index: dict[tuple[int, int], int] = {}

        def node(xy) -> int:
            key = (round(xy[0] / snap_tolerance), round(xy[1] / snap_tolerance))
            if key not in index:
                nid = len(index)
                index[key] = nid
                G.add_node(nid, x=float(xy[0]), y=float(xy[1]))
            return index[key]

        def add(seg: LineString) -> None:
            coords = list(seg.coords)
            u, v = node(coords[0]), node(coords[-1])
            if u == v or G.has_edge(u, v):
                # closed ring or a second road between the same two nodes: split it in half
                if seg.length < 2 * snap_tolerance:
                    return
                half = seg.length / 2
                add(substring(seg, 0, half))
                add(substring(seg, half, seg.length))
                return
            G.add_edge(u, v, length=float(seg.length), geometry=seg, start=u)

        for seg in _iter_lines(noded):
            if seg.length >= snap_tolerance:
                add(seg)
        if G.number_of_nodes() == 0:
            raise ValueError("Road data produced an empty graph.")

        dropped = 0
        if keep_largest and not nx.is_connected(G):
            comp = max(nx.connected_components(G), key=len)
            dropped = G.number_of_nodes() - len(comp)
            G = G.subgraph(comp).copy()
        net = cls(G, gs.crs)
        net.dropped_nodes = dropped
        return net

    @classmethod
    def from_osm(
        cls,
        place: str | None = None,
        *,
        point: tuple[float, float] | None = None,
        dist: float = 1000,
        bbox: tuple[float, float, float, float] | None = None,
        network_type: str = "drive_service",
    ) -> RoadNetwork:
        """Download roads from OpenStreetMap with OSMnx (``pip install fttxplan[osm]``).

        Give one of ``place`` (e.g. ``"F-7, Islamabad, Pakistan"``), ``point`` as ``(lat, lon)``
        with ``dist`` in metres, or ``bbox`` as ``(west, south, east, north)``.
        """
        try:
            import osmnx as ox
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise ImportError("Downloading from OpenStreetMap needs OSMnx: pip install 'fttxplan[osm]'") from exc
        if place:
            G = ox.graph_from_place(place, network_type=network_type)
        elif point:
            G = ox.graph_from_point(point, dist=dist, network_type=network_type)
        elif bbox:
            G = ox.graph_from_bbox(bbox, network_type=network_type)
        else:
            raise ValueError("Give place=, point= or bbox=")
        edges = ox.graph_to_gdfs(G, nodes=False)
        return cls.from_lines(edges[["geometry"]].reset_index(drop=True))

    # ---------------------------------------------------------------- helpers
    def xy(self, n: int) -> tuple[float, float]:
        d = self.graph.nodes[n]
        return d["x"], d["y"]

    def point(self, n: int) -> Point:
        return Point(self.xy(n))

    @property
    def total_length(self) -> float:
        return float(sum(d["length"] for _, _, d in self.graph.edges(data=True)))

    def edges_gdf(self) -> gpd.GeoDataFrame:
        rows = [{"u": u, "v": v, "length_m": d["length"], "geometry": d["geometry"]} for u, v, d in self.graph.edges(data=True)]
        return gpd.GeoDataFrame(rows, geometry="geometry", crs=self.crs)

    def to_network_crs(self, data, crs=None) -> gpd.GeoSeries:
        gs = _as_geoseries(data, crs)
        if gs.crs is None:
            raise ValueError("Point geometries have no CRS.")
        return gs.to_crs(self.crs)

    # --------------------------------------------------------------- attaching
    def attach(self, points: Sequence[Point], tol: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
        """Connect points to the network at their nearest road position.

        The nearest edge of every point is split at the projected position, creating a new
        node (or reusing an end node when the projection lands within ``tol`` of it).
        Returns ``(node_ids, offsets_m)`` where offset is the straight distance from the point
        to the road, i.e. the last part of the drop cable.
        """
        pts = np.asarray(points, dtype=object)
        self._csr_cache = None
        edges = list(self.graph.edges(data=True))
        tree = STRtree([d["geometry"] for _, _, d in edges])
        nearest = tree.query_nearest(pts, all_matches=False)
        hit = np.empty(len(pts), dtype=int)
        hit[nearest[0]] = nearest[1]

        groups: dict[int, list[tuple[int, float]]] = defaultdict(list)
        offsets = np.zeros(len(pts))
        for i, p in enumerate(pts):
            geom = edges[hit[i]][2]["geometry"]
            t = geom.project(p)
            groups[hit[i]].append((i, t))
            offsets[i] = p.distance(geom.interpolate(t))

        nodes = np.empty(len(pts), dtype=int)
        G = self.graph
        for ei, items in groups.items():
            u, v, d = edges[ei]
            geom, s = d["geometry"], d["start"]
            e = v if s == u else u
            L = geom.length
            cuts: list[float] = []
            for _, t in sorted(items, key=lambda it: it[1]):
                if tol < t < L - tol and (not cuts or t - cuts[-1] > tol):
                    cuts.append(t)
            node_at: list[tuple[float, int]] = [(0.0, s)]
            if cuts:
                G.remove_edge(u, v)
                prev_n, prev_t = s, 0.0
                for t in cuts:
                    nid = self._next_id
                    self._next_id += 1
                    p = geom.interpolate(t)
                    G.add_node(nid, x=float(p.x), y=float(p.y))
                    G.add_edge(prev_n, nid, length=t - prev_t, geometry=substring(geom, prev_t, t), start=prev_n)
                    node_at.append((t, nid))
                    prev_n, prev_t = nid, t
                G.add_edge(prev_n, e, length=L - prev_t, geometry=substring(geom, prev_t, L), start=prev_n)
            node_at.append((L, e))
            ts = np.array([t for t, _ in node_at])
            for i, t in items:
                nodes[i] = node_at[int(np.argmin(np.abs(ts - t)))][1]
        return nodes, offsets

    # ----------------------------------------------------------------- routing
    def _csr(self):
        """Sparse adjacency matrix of the graph (built once, reset by :meth:`attach`)."""
        if self._csr_cache is None:
            nodes = list(self.graph.nodes)
            idx = {n: i for i, n in enumerate(nodes)}
            rows, cols, w = [], [], []
            for u, v, d in self.graph.edges(data=True):
                i, j = idx[u], idx[v]
                rows += [i, j]
                cols += [j, i]
                w += [max(d["length"], 1e-6)] * 2
            mat = csr_matrix((w, (rows, cols)), shape=(len(nodes), len(nodes)))
            self._csr_cache = (mat, np.array(nodes), idx)
        return self._csr_cache

    def distance_matrix(self, sources: Sequence[int], targets: Sequence[int], limit: float = np.inf, chunk: int = 256) -> np.ndarray:
        """Road distances from every source node to every target node (``inf`` beyond ``limit``)."""
        mat, _, idx = self._csr()
        src = np.array([idx[int(s)] for s in sources])
        tgt = np.array([idx[int(t)] for t in targets])
        out = np.empty((len(src), len(tgt)))
        for a in range(0, len(src), chunk):
            out[a : a + chunk] = cs_dijkstra(mat, directed=False, indices=src[a : a + chunk], limit=limit)[:, tgt]
        return out

    def paths_from(self, source: int, targets: Sequence[int], limit: float = np.inf) -> list[tuple[float, list[int]]]:
        """Shortest ``(distance, node_path)`` from ``source`` to each target."""
        mat, nodes, idx = self._csr()
        dist, pred = cs_dijkstra(mat, directed=False, indices=idx[int(source)], limit=limit, return_predecessors=True)
        out = []
        for t in targets:
            j = idx[int(t)]
            if not np.isfinite(dist[j]):
                if np.isfinite(limit):
                    return self.paths_from(source, targets)
                raise ValueError(f"Node {t} is not reachable from {source}")
            path = [j]
            while path[-1] != idx[int(source)]:
                path.append(pred[path[-1]])
            out.append((float(dist[j]), [int(nodes[k]) for k in reversed(path)]))
        return out

    def shortest_paths(self, source: int, cutoff: float | None = None) -> tuple[dict, dict]:
        """Dijkstra from ``source``: returns ``(distances, paths)`` dictionaries."""
        return nx.single_source_dijkstra(self.graph, source, cutoff=cutoff, weight="length")

    def distances(self, source: int, cutoff: float | None = None) -> dict:
        return nx.single_source_dijkstra_path_length(self.graph, source, cutoff=cutoff, weight="length")

    def path_geometry(self, path: Sequence[int]) -> LineString | None:
        """Merge the edge geometries along a node path into one line."""
        if len(path) < 2:
            return None
        parts = [self.graph[a][b]["geometry"] for a, b in zip(path, path[1:])]
        merged = linemerge(MultiLineString(parts))
        return merged if isinstance(merged, LineString) else merged
