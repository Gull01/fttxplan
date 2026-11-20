"""Command line interface: ``fttxplan design | osm | demo``."""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

from . import __version__
from .config import PON_CLASSES, DesignConfig


def _lonlat(text: str):
    from shapely.geometry import Point

    try:
        x, y = (float(v) for v in text.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected 'lon,lat', for example 73.0551,33.7215") from exc
    return Point(x, y)


def _budget(text: str) -> float:
    return PON_CLASSES[text.upper()] if text.upper() in PON_CLASSES else float(text)


def _config(args) -> DesignConfig:
    return DesignConfig(
        split_levels=args.split,
        spare_ratio=args.spare,
        slack_ratio=args.slack,
        budget_db=args.budget,
        cabinet_size=args.cabinet_size,
        seed=args.seed,
    )


def _common(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("design options")
    g.add_argument("--split", default="1:4x1:8", help="splitter architecture, e.g. 1:32 or 1:4x1:8 (default)")
    g.add_argument("--spare", type=float, default=0.2, help="spare fibre fraction (default 0.2)")
    g.add_argument("--slack", type=float, default=0.1, help="cable slack fraction for the BOM (default 0.1)")
    g.add_argument("--budget", type=_budget, default=PON_CLASSES["B+"], help="optical budget in dB or class B+/C+/C++ (default B+)")
    g.add_argument("--cabinet-size", type=int, default=8, help="first-level splitters per FDH cabinet (default 8)")
    g.add_argument("--seed", type=int, default=0)
    o = p.add_argument_group("outputs")
    o.add_argument("-o", "--out", default="fttx_design", help="output folder (default ./fttx_design)")
    o.add_argument("--no-map", action="store_true", help="skip the PNG and HTML maps")


def _write(design, out: Path, maps: bool = True) -> None:
    out.mkdir(parents=True, exist_ok=True)
    design.to_gpkg(out / "design.gpkg")
    design.to_kml(out / "design.kml")
    design.bom().to_csv(out / "bom.csv", index=False)
    design.loss_budget().to_csv(out / "loss_budget.csv", index=False)
    (out / "report.txt").write_text(design.report() + "\n", encoding="utf-8")
    if maps:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        ax = design.plot(figsize=(11, 11))
        ax.figure.savefig(out / "map.png", dpi=150, bbox_inches="tight")
        plt.close(ax.figure)
        design.explore().save(str(out / "map.html"))
    print(design.report())
    print(f"\nWrote design.gpkg, design.kml, bom.csv, loss_budget.csv, report.txt{', map.png, map.html' if maps else ''} to {out}/")


def cmd_design(args) -> int:
    import geopandas as gpd

    from .design import plan

    roads = gpd.read_file(args.roads, layer=args.roads_layer) if args.roads_layer else gpd.read_file(args.roads)
    prem = gpd.read_file(args.premises, layer=args.premises_layer) if args.premises_layer else gpd.read_file(args.premises)
    olt = args.olt if args.olt is not None else gpd.read_file(args.olt_file)
    design = plan(roads, olt, prem, _config(args), id_column=args.id_column)
    _write(design, Path(args.out), not args.no_map)
    return 0


def cmd_osm(args) -> int:
    try:
        import osmnx as ox
    except ImportError:
        print("This command needs OSMnx:  pip install 'fttxplan[osm]'", file=sys.stderr)
        return 2
    from .design import plan
    from .network import RoadNetwork

    if args.place:
        print(f"Downloading roads and buildings for {args.place!r} from OpenStreetMap...")
        net = RoadNetwork.from_osm(args.place)
        bld = ox.features_from_place(args.place, tags={"building": True})
    else:
        lat, lon = (float(v) for v in args.point.split(","))
        print(f"Downloading roads and buildings within {args.dist:g} m of {lat},{lon}...")
        net = RoadNetwork.from_osm(point=(lat, lon), dist=args.dist)
        bld = ox.features_from_point((lat, lon), tags={"building": True}, dist=args.dist)
    bld = bld[bld.geom_type.isin(["Polygon", "MultiPolygon"])]
    area = bld.to_crs(net.crs).area
    bld = bld[(area >= args.min_area)].reset_index()
    print(f"{len(bld)} buildings, {net}")
    if args.olt is None:
        c = bld.to_crs(net.crs).union_all().centroid
        print("No --olt given: placing the OLT at the centre of the buildings (pass --olt lon,lat for a real site).")
        import geopandas as gpd

        olt = gpd.GeoSeries([c], crs=net.crs)
    else:
        olt = args.olt
    design = plan(net, olt, bld, _config(args))
    _write(design, Path(args.out), not args.no_map)
    return 0


def cmd_demo(args) -> int:
    from .datasets import load_demo
    from .design import plan

    roads, prem, olt = load_demo()
    design = plan(roads, olt, prem, _config(args))
    _write(design, Path(args.out), not args.no_map)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fttxplan", description="Open-source FTTx / GPON network planning.")
    p.add_argument("--version", action="version", version=f"fttxplan {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("design", help="design from your own road and premises files")
    d.add_argument("roads", help="road centrelines (GeoPackage, Shapefile, GeoJSON...)")
    d.add_argument("premises", help="premises / buildings to connect (points or polygons)")
    src = d.add_mutually_exclusive_group(required=True)
    src.add_argument("--olt", type=_lonlat, help="OLT location as lon,lat")
    src.add_argument("--olt-file", help="file with the OLT point")
    d.add_argument("--roads-layer")
    d.add_argument("--premises-layer")
    d.add_argument("--id-column", help="premises column to use as identifier")
    _common(d)
    d.set_defaults(func=cmd_design)

    o = sub.add_parser("osm", help="download roads and buildings from OpenStreetMap and design")
    where = o.add_mutually_exclusive_group(required=True)
    where.add_argument("--place", help='place name, e.g. "F-7 Markaz, Islamabad, Pakistan"')
    where.add_argument("--point", help="centre as lat,lon")
    o.add_argument("--dist", type=float, default=600, help="radius in metres around --point (default 600)")
    o.add_argument("--olt", type=_lonlat, help="OLT location as lon,lat (default: centre of the buildings)")
    o.add_argument("--min-area", type=float, default=30, help="ignore buildings smaller than this, m2 (default 30)")
    _common(o)
    o.set_defaults(func=cmd_osm)

    m = sub.add_parser("demo", help="run on the bundled sample neighbourhood")
    _common(m)
    m.set_defaults(func=cmd_demo)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    with warnings.catch_warnings():
        warnings.simplefilter("default")
        return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
